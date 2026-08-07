import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from handlers import commands, messages
from middlewares.throttling import ThrottlingMiddleware
from utils.files import cleanup_old_files

logging.basicConfig(level=logging.INFO, stream=sys.stdout)


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
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Анти-спам middleware (1.5 сек лимит)
    dp.message.middleware(ThrottlingMiddleware(limit_seconds=1.5))
    dp.callback_query.middleware(ThrottlingMiddleware(limit_seconds=1.5))

    dp.include_router(commands.router)
    dp.include_router(messages.router)

    asyncio.create_task(periodic_cleanup())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
