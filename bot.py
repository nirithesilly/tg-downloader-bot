import asyncio
import logging
import logging.handlers
import sys

import shutil

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, LOG_DIR
from handlers import commands, messages
from middlewares.throttling import ThrottlingMiddleware
from utils.files import cleanup_old_files

log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format=log_format)

file_handler = logging.handlers.RotatingFileHandler(
    f"{LOG_DIR}/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(log_format))
logging.getLogger().addHandler(file_handler)


async def periodic_cleanup():
    while True:
        await asyncio.sleep(3600)
        try:
            removed = await asyncio.to_thread(cleanup_old_files, 24)
            if removed:
                logging.info("Очищено старых файлов: %d", removed)
        except Exception as e:
            logging.error("Ошибка фоновой очистки: %s", e)


async def main():
    if not shutil.which("ffmpeg"):
        logging.warning("ВНИМАНИЕ: ffmpeg не найден в системе! Конвертация аудио и склейка видео не будут работать без установленного ffmpeg.")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.message.middleware(ThrottlingMiddleware(limit_seconds=1.5))
    dp.callback_query.middleware(ThrottlingMiddleware(limit_seconds=0.3))

    dp.include_router(commands.router)
    dp.include_router(messages.router)

    asyncio.create_task(periodic_cleanup())

    logging.info("bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

