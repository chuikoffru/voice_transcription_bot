import asyncio
import io
import logging
from typing import BinaryIO
import json

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from models import init_db, Usage, User, db, upsert_user, upsert_chat, upsert_user_chat
from llm_service import LLMService
from user_service import process_chat_message, replace_name_with_username
from peewee import fn

# Настройка логирования
log_level = logging.DEBUG if settings.DEBUG else logging.INFO
log_handlers = [logging.StreamHandler()]

if settings.DEBUG:
    log_handlers.append(logging.FileHandler("bot_debug.log"))
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
else:
    log_format = "%(asctime)s - %(levelname)s - %(message)s"

logging.basicConfig(level=log_level, format=log_format, handlers=log_handlers)
logger = logging.getLogger(__name__)

if settings.DEBUG:
    logger.debug("Debug mode is enabled")

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
llm_service = LLMService(settings.DEEPSEEK_API_KEY)


# Логирование всех входящих обновлений
@dp.update()
async def log_update(update):
    logger.debug(f"Received update: {update.dict()}")


async def download_voice_message(file: BinaryIO) -> bytes:
    logger.debug("Starting voice message download")
    try:
        content = file.read()
        logger.debug(
            f"Successfully downloaded voice message, size: {len(content)} bytes"
        )
        return content
    except Exception as e:
        logger.error(f"Error downloading voice message: {str(e)}", exc_info=True)
        raise


async def upload_audio_to_gladia(audio_content: bytes, filename: str) -> dict:
    logger.debug(f"Starting upload for file: {filename}")
    logger.debug(f"Audio content size: {len(audio_content)} bytes")

    headers = {
        "x-gladia-key": settings.GLADIA_API_KEY,
        "accept": "application/json",
    }

    try:
        form = aiohttp.FormData()
        form.add_field(
            "audio", audio_content, filename=filename, content_type="audio/ogg"
        )

        logger.debug("Headers for upload request:")
        logger.debug(json.dumps(headers, indent=2))

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.gladia.io/v2/upload/", headers=headers, data=form
            ) as response:
                logger.debug(f"Upload response status: {response.status}")
                response_text = await response.text()
                logger.debug(f"Upload response body: {response_text}")

                if response.status != 200:
                    logger.error(f"Upload failed with status {response.status}")
                    logger.error(f"Response: {response_text}")
                    return {}

                return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error during upload: {str(e)}", exc_info=True)
        return {}


async def transcribe_audio(audio_url: str) -> dict:
    logger.debug(f"Starting transcription for URL: {audio_url}")

    headers = {
        "x-gladia-key": settings.GLADIA_API_KEY,
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    data = {
        "audio_url": audio_url,
        "language": "ru",
        "diarization": True,
    }

    try:
        logger.debug("Transcription request data:")
        logger.debug(json.dumps(data, indent=2))

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.gladia.io/v2/transcription/", headers=headers, json=data
            ) as response:
                logger.debug(f"Transcription response status: {response.status}")
                response_text = await response.text()
                logger.debug(f"Transcription response body: {response_text}")

                if response.status not in [200, 201]:
                    logger.error(f"Transcription failed with status {response.status}")
                    logger.error(f"Response: {response_text}")
                    return {}

                return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error during transcription: {str(e)}", exc_info=True)
        return {}


@dp.message(
    lambda message: message.text
    and not message.text.startswith("/")
    and not message.voice
    and not message.audio
)
async def handle_text(message: types.Message):
    """Обработчик текстовых сообщений (не команд) для сохранения информации о пользователях и чатах"""
    logger.debug(
        f"Received message type: text={bool(message.text)}, voice={bool(message.voice)}, audio={bool(message.audio)}"
    )
    logger.debug(
        f"Received text message from user {message.from_user.id} in chat {message.chat.id}"
    )
    try:
        with db:
            # Используем существующие функции upsert для оптимальной работы с БД
            user = upsert_user(message.from_user)
            chat = upsert_chat(message)
            upsert_user_chat(user, chat)
            logger.debug(
                f"Successfully processed message: user={user.id}, chat={chat.id}"
            )
    except Exception as e:
        logger.error(f"Error processing text message: {e}", exc_info=True)


async def get_transcription_result(result_url: str) -> dict:
    logger.debug(f"Starting to poll for results at URL: {result_url}")

    headers = {
        "x-gladia-key": settings.GLADIA_API_KEY,
        "accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                # Используем полный URL, который получили от API
                async with session.get(result_url, headers=headers) as response:
                    logger.debug(f"Poll response status: {response.status}")
                    response_text = await response.text()
                    logger.debug(f"Poll response body: {response_text}")

                    if response.status != 200:
                        logger.error(f"Polling failed with status {response.status}")
                        logger.error(f"Response: {response_text}")
                        raise Exception("Failed to get transcription result")

                    result = json.loads(response_text)

                    if result.get("status") == "done":
                        logger.debug("Transcription completed successfully")
                        return result
                    elif result.get("status") == "error":
                        logger.error("Transcription failed with error status")
                        raise Exception("Transcription failed")

                    logger.debug(f"Status: {result.get('status')}, waiting...")
                    await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error getting transcription result: {str(e)}", exc_info=True)
        raise


@dp.message(CommandStart())
async def handle_start(message: types.Message):
    logger.info(f"Received /start command from user {message.from_user.id}")
    with db:
        user = upsert_user(message.from_user)
        logger.info(
            f"User {user.id} ({user.username or user.firstname}) started the bot"
        )

    await message.answer(
        "Привет! Я бот для транскрибации голосовых сообщений.\n"
        "🎤 Отправь мне голосовое сообщение, и я преобразую его в текст.\n"
        "📊 Используй /stats для просмотра статистики использования."
    )


@dp.message(Command("stats"))
async def handle_stats(message: types.Message):
    logger.info(f"Received /stats command from user {message.from_user.id}")
    try:
        with db:
            user = upsert_user(message.from_user)

            # Получаем общую статистику пользователя
            total_duration = (
                Usage.select(fn.SUM(Usage.duration))
                .join(User)
                .where(User.tg_id == message.from_user.id)
                .scalar()
                or 0
            )

            total_messages = (
                Usage.select()
                .join(User)
                .where(User.tg_id == message.from_user.id)
                .count()
            )

            # Получаем последние 5 транскрибаций
            recent_usages = (
                Usage.select()
                .join(User)
                .where(User.tg_id == message.from_user.id)
                .order_by(Usage.created_at.desc())
                .limit(5)
            )

            # Формируем сообщение
            stats_message = (
                "📊 Ваша статистика использования:\n\n"
                f"🎯 Всего транскрибаций: {total_messages}\n"
                f"⏱ Общая длительность: {total_duration:.1f} сек.\n"
                f"⌛️ Среднее время: {(total_duration / total_messages if total_messages else 0):.1f} сек.\n"
            )

            if recent_usages:
                stats_message += "\n🔍 Последние транскрибации:\n"
                for usage in recent_usages:
                    chat_name = usage.chat.name or str(usage.chat.tg_chat_id)
                    chat_type = (
                        "личном чате"
                        if usage.chat.tg_chat_id == message.from_user.id
                        else f"группе {chat_name}"
                    )
                    stats_message += (
                        f"- {usage.created_at.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"в {chat_type}: {usage.duration:.1f} сек.\n"
                    )

            await message.answer(stats_message)

    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при получении статистики.")


@dp.message(lambda message: message.voice or message.audio)
async def handle_voice(message: types.Message):
    logger.info(
        f"Received {'voice' if message.voice else 'audio'} message from user {message.from_user.id}"
    )
    logger.debug(f"Message content: {message.dict()}")

    # Сохраняем информацию о пользователе и чате
    try:
        with db:
            user = upsert_user(message.from_user)
            chat = upsert_chat(message)
            upsert_user_chat(user, chat)
            logger.debug(
                f"Successfully processed voice message metadata: user={user.id}, chat={chat.id}"
            )
    except Exception as e:
        logger.error(f"Error processing voice message metadata: {e}", exc_info=True)

    processing_msg = await message.reply("🎯 Начинаю обработку голосового сообщения...")

    try:
        # Получаем информацию о файле
        if message.voice:
            await processing_msg.edit_text("⌛️ Загрузка голосового сообщения...")
            file = await bot.get_file(message.voice.file_id)
            filename = f"{message.voice.file_id}.ogg"
            logger.debug(f"Voice message file_id: {message.voice.file_id}")
        else:
            file = await bot.get_file(message.audio.file_id)
            filename = message.audio.file_name or f"{message.audio.file_id}.ogg"
            logger.debug(f"Audio message file_id: {message.audio.file_id}")

        logger.debug(f"File path: {file.file_path}")

        # Скачиваем файл
        file_content = io.BytesIO()
        await bot.download_file(file.file_path, file_content)
        file_content.seek(0)

        # Загружаем аудио на Gladia
        audio_content = await download_voice_message(file_content)
        await processing_msg.edit_text("📤 Загрузка аудио на сервер...")
        upload_response = await upload_audio_to_gladia(audio_content, filename)

        if not upload_response.get("audio_url"):
            logger.error("Failed to get audio_url from upload response")
            await processing_msg.edit_text(
                "❌ Ошибка при загрузке аудио. Пожалуйста, попробуйте еще раз."
            )
            return

        # Отправляем на транскрибацию
        await processing_msg.edit_text("🔍 Начинаю транскрибацию...")
        transcription_response = await transcribe_audio(upload_response["audio_url"])

        if not transcription_response.get("result_url"):
            logger.error("Failed to get result_url from transcription response")
            await processing_msg.edit_text(
                "❌ Ошибка при отправке на транскрибацию. Пожалуйста, попробуйте еще раз."
            )
            return

        # Получаем результат
        await processing_msg.edit_text("⏳ Ожидание результатов транскрибации...")
        result = await get_transcription_result(transcription_response["result_url"])

        logger.debug(
            f"Final result: {json.dumps(result, indent=2, ensure_ascii=False)}"
        )

        if "result" in result and "transcription" in result["result"]:
            transcription = result["result"]["transcription"]
            full_text = transcription.get("full_transcript", "")

            # Логируем полный результат для отладки
            logger.info(f"Successfully transcribed audio. Full text: {full_text}")

            # Записываем использование в базу данных
            try:
                duration = (
                    result.get("result", {})
                    .get("metadata", {})
                    .get("audio_duration", 0)
                )
                with db:
                    user = upsert_user(message.from_user)
                    chat = upsert_chat(message)
                    upsert_user_chat(user, chat)
                    Usage.create(
                        user=user,
                        chat=chat,
                        message_id=message.message_id,
                        duration=duration,
                    )
                    logger.info(
                        f"Usage recorded: user={user.id} ({user.username or user.firstname}), "
                        f"chat_id={message.chat.id}, duration={duration}s"
                    )
            except Exception as e:
                logger.error(f"Failed to record usage: {e}", exc_info=True)

            try:
                # Удаляем сообщение о процессе
                await processing_msg.delete()
            except Exception as e:
                logger.warning(f"Failed to delete processing message: {e}")

            # Отправляем текст транскрибации и обрабатываем имена
            if len(full_text) > 4000:  # Telegram limit is 4096, using 4000 to be safe
                # Разбиваем длинный текст на части
                parts = [
                    full_text[i : i + 4000] for i in range(0, len(full_text), 4000)
                ]
                # Первую часть отправляем как ответ на голосовое сообщение
                first_msg = await message.reply(
                    f"✨ Часть 1/{len(parts)}:\n\n{parts[0]}"
                )
                # Обрабатываем имена в первой части
                await process_name_mentions(first_msg, parts[0])
                # Остальные части отправляем как обычные сообщения
                for i, part in enumerate(parts[1:], 2):
                    msg = await message.answer(f"✨ Часть {i}/{len(parts)}:\n\n{part}")
                    await process_name_mentions(msg, part)
            else:
                msg = await message.reply(f"✨ Транскрибация:\n\n{full_text}")
                await process_name_mentions(msg, full_text)
        else:
            logger.error(
                f"Failed to get transcription from result. Result structure: {json.dumps(result, indent=2, ensure_ascii=False)}"
            )
            await processing_msg.edit_text(
                "❌ Не удалось получить текст транскрибации. Пожалуйста, попробуйте еще раз."
            )

    except Exception as e:
        logger.error(f"Error processing voice message: {str(e)}", exc_info=True)
        error_message = (
            "❌ Произошла ошибка при обработке голосового сообщения.\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к администратору."
        )
        try:
            await processing_msg.edit_text(error_message)
        except Exception:
            await message.reply(error_message)


@dp.callback_query(lambda c: c.data.startswith("select_user:"))
async def handle_user_selection(callback_query: types.CallbackQuery):
    try:
        # Получаем данные из callback
        _, found_name, username = callback_query.data.split(":")
        message = callback_query.message

        # Изменяем текст сообщения
        new_text = replace_name_with_username(message.text, found_name, username)
        
        logger.debug(f"Callback: replacing name '{found_name}' with @{username}")
        logger.debug(f"Callback: original text: {message.text}")
        logger.debug(f"Callback: modified text: {new_text}")

        # Обновляем сообщение без клавиатуры
        await message.edit_text(new_text)

        # Отвечаем на callback
        await callback_query.answer(f"Имя '{found_name}' заменено на @{username}")
    except Exception as e:
        logger.error(f"Error handling user selection: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при обработке выбора")


async def process_name_mentions(message: types.Message, text: str) -> str:
    """Обрабатывает упоминания имен в тексте и возвращает обновленный текст"""
    try:
        # Получаем всех пользователей чата и анализируем текст с помощью LLM
        found_name, matching_users = process_chat_message(message.chat.id, text, llm_service)

        logger.debug(f"Found name: {found_name}")
        logger.debug(f"Matching users: {matching_users}")

        if not found_name or not matching_users:
            return text

        if len(matching_users) == 1:
            # Если найден один пользователь, сразу заменяем имя
            firstname, username, _ = matching_users[0]
            new_text = replace_name_with_username(text, found_name, username)
            logger.debug(f"Replacing name '{found_name}' with @{username}")
            logger.debug(f"Original text: {text}")
            logger.debug(f"Modified text: {new_text}")
            
            # Обновляем текст сообщения
            await message.edit_text(new_text)
            return new_text
        else:
            # Если найдено несколько пользователей, добавляем кнопки выбора
            builder = InlineKeyboardBuilder()
            for firstname, username, _ in matching_users:
                builder.button(
                    text=f"{firstname} (@{username})",
                    callback_data=f"select_user:{found_name}:{username}",
                )
            builder.adjust(1)  # По одной кнопке в ряд

            # Отправляем сообщение с кнопками
            await message.edit_text(text, reply_markup=builder.as_markup())
            return text
    except Exception as e:
        logger.error(f"Error processing name mentions: {e}", exc_info=True)
        return text


async def main():
    logger.info("Starting bot")
    try:
        # Инициализация базы данных
        init_db()
        logger.info("Database initialized")

        # Регистрируем все обработчики
        logger.debug("Registered handlers:")
        for handler in dp.message.handlers:
            logger.debug(f"- Handler with filter: {handler.callback}")

        # Запуск бота
        logger.info("Starting polling...")
        await dp.start_polling(
            bot, allowed_updates=["message", "edited_message"], skip_updates=True
        )
    except Exception as e:
        logger.error(f"Error in main loop: {str(e)}", exc_info=True)
    finally:
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
