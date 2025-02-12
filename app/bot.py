import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command

from config import settings
from models import init_db, db, upsert_user, upsert_chat, upsert_user_chat
from llm_service import LLMService
from handlers.basic import handle_start, handle_text
from handlers.stats import handle_stats
from handlers.voice import handle_voice

# Настройка логирования
log_level = logging.DEBUG if settings.DEBUG else logging.INFO
log_handlers = [logging.StreamHandler()]

if settings.DEBUG:
    log_handlers.append(logging.FileHandler("bot_debug.log"))
    log_format = "%(asctime)s - %(name)s - %(levellevel)s - %(message)s"
else:
    log_format = "%(asctime)s - %(levellevel)s - %(message)s"

logging.basicConfig(level=log_level, format=log_format, handlers=log_handlers)
logger = logging.getLogger(__name__)

if settings.DEBUG:
    logger.debug("Debug mode is enabled")

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
llm_service = LLMService(settings.DEEPSEEK_API_KEY)

# Логирование всех входящих обновлений и обновление данных пользователей
@dp.update()
async def log_update(update):
    logger.debug(f"Received update: {update.dict()}")
    
    try:
        # Проверяем, есть ли в обновлении информация о пользователе и чате
        if hasattr(update, 'message') and update.message:
            with db:
                user = upsert_user(update.message.from_user)
                chat = upsert_chat(update.message)
                upsert_user_chat(user, chat)
                logger.debug(
                    f"Successfully processed update: user={user.id}, chat={chat.id}"
                )
    except Exception as e:
        logger.error(f"Error processing update metadata: {e}", exc_info=True)

# Register handlers
dp.message.register(handle_start, CommandStart())
dp.message.register(handle_stats, Command("stats"))
dp.message.register(handle_text, lambda message: message.text and not message.text.startswith("/") and not message.voice and not message.audio)

# Register voice handler with bot and llm_service dependencies
dp.message.register(
    lambda message: handle_voice(message, bot, llm_service),
    lambda message: message.voice or message.audio
)

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
