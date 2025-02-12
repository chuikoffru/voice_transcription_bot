import io
import json
import logging
import asyncio
from typing import BinaryIO

import aiohttp
from aiogram import types, Bot

from ..config import settings
from ..models import Usage, User, db, upsert_user, upsert_chat, upsert_user_chat
from ..user_service import process_chat_message

logger = logging.getLogger(__name__)

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

async def get_transcription_result(result_url: str) -> dict:
    logger.debug(f"Starting to poll for results at URL: {result_url}")

    headers = {
        "x-gladia-key": settings.GLADIA_API_KEY,
        "accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            while True:
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

async def handle_voice(message: types.Message, bot: Bot, llm_service):
    """Обработчик голосовых и аудио сообщений"""
    logger.info(
        f"Received {'voice' if message.voice else 'audio'} message from user {message.from_user.id}"
    )
    logger.debug(f"Message content: {message.dict()}")

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

            # Обработка упоминаний до отправки текста пользователю
            found_name, matching_users = process_chat_message(message.chat.id, full_text, llm_service)

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
                await processing_msg.delete()
            except Exception as e:
                logger.warning(f"Failed to delete processing message: {e}")

            # Отправляем обработанный текст транскрибации
            if len(full_text) > 4000:  # Telegram limit is 4096, using 4000 to be safe
                parts = [
                    full_text[i : i + 4000] for i in range(0, len(full_text), 4000)
                ]
                await message.reply(f"✨ Часть 1/{len(parts)}:\n\n{parts[0]}")
                for i, part in enumerate(parts[1:], 2):
                    await message.answer(f"✨ Часть {i}/{len(parts)}:\n\n{part}")
            else:
                await message.reply(f"✨ Транскрибация:\n\n{full_text}")
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