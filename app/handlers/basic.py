from aiogram import types
from aiogram.filters import CommandStart
import logging

logger = logging.getLogger(__name__)

async def handle_start(message: types.Message):
    """Обработчик команды /start"""
    logger.info(f"Received /start command from user {message.from_user.id}")
    await message.answer(
        "Привет! Я бот для транскрибации голосовых сообщений.\n"
        "🎤 Отправь мне голосовое сообщение, и я преобразую его в текст.\n"
        "📊 Используй /stats для просмотра статистики использования."
    )

async def handle_text(message: types.Message):
    """Обработчик текстовых сообщений (не команд)"""
    logger.debug(
        f"Received message type: text={bool(message.text)}, voice={bool(message.voice)}, audio={bool(message.audio)}"
    )
    logger.debug(
        f"Received text message from user {message.from_user.id} in chat {message.chat.id}"
    )