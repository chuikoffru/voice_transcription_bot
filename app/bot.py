import asyncio
import io
import logging
from typing import BinaryIO
import json
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from config import settings

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

async def download_voice_message(file: BinaryIO) -> bytes:
    logger.debug("Starting voice message download")
    try:
        content = file.read()
        logger.debug(f"Successfully downloaded voice message, size: {len(content)} bytes")
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
        form.add_field('audio', 
                      audio_content,
                      filename=filename,
                      content_type='audio/ogg')
        
        logger.debug("Headers for upload request:")
        logger.debug(json.dumps(headers, indent=2))
        
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.gladia.io/v2/upload/", 
                                  headers=headers, 
                                  data=form) as response:
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
        "Content-Type": "application/json"
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
            async with session.post("https://api.gladia.io/v2/transcription/", 
                                  headers=headers, 
                                  json=data) as response:
                logger.debug(f"Transcription response status: {response.status}")
                response_text = await response.text()
                logger.debug(f"Transcription response body: {response_text}")
                
                if response.status != 200:
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

@dp.message(CommandStart())
async def handle_start(message: types.Message):
    logger.info(f"Received /start command from user {message.from_user.id}")
    await message.answer(
        "Привет! Я бот для транскрибации голосовых сообщений. "
        "Отправь мне голосовое сообщение, и я преобразую его в текст."
    )

@dp.message(lambda message: message.voice or message.audio)
async def handle_voice(message: types.Message):
    logger.info(f"Received {'voice' if message.voice else 'audio'} message from user {message.from_user.id}")
    await message.answer("Начинаю обработку голосового сообщения...")
    
    try:
        # Получаем информацию о файле
        if message.voice:
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
        upload_response = await upload_audio_to_gladia(audio_content, filename)
        
        if not upload_response.get("audio_url"):
            logger.error("Failed to get audio_url from upload response")
            await message.answer("Ошибка при загрузке аудио. Пожалуйста, попробуйте еще раз.")
            return
        
        # Отправляем на транскрибацию
        transcription_response = await transcribe_audio(upload_response["audio_url"])
        
        if not transcription_response.get("result_url"):
            logger.error("Failed to get result_url from transcription response")
            await message.answer("Ошибка при отправке на транскрибацию. Пожалуйста, попробуйте еще раз.")
            return
        
        # Получаем результат
        result = await get_transcription_result(transcription_response["result_url"])
        
        if "result" in result and "transcription" in result["result"]:
            transcription = result["result"]["transcription"]
            logger.info("Successfully transcribed audio")
            await message.answer(f"Транскрибация:\n\n{transcription}")
        else:
            logger.error("Failed to get transcription from result")
            await message.answer("Не удалось получить текст транскрибации. Пожалуйста, попробуйте еще раз.")
            
    except Exception as e:
        logger.error(f"Error processing voice message: {str(e)}", exc_info=True)
        await message.answer(
            "Произошла ошибка при обработке голосового сообщения. "
            "Пожалуйста, попробуйте еще раз или обратитесь к администратору."
        )

async def main():
    logger.info("Starting bot")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error in main loop: {str(e)}", exc_info=True)
    finally:
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())