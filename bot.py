import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from handlers import commands
from middlewares.throttling import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    # Анти-спам middleware (1.5 сек лимит)
    dp.message.middleware(ThrottlingMiddleware(limit_seconds=1.5))
    dp.callback_query.middleware(ThrottlingMiddleware(limit_seconds=1.5))

    dp.include_router(commands.router)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
