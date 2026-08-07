import time
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit_seconds: float = 2.0):
        self.limit_seconds = limit_seconds
        self.user_timestamps: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            now = time.time()
            if len(self.user_timestamps) > 1000:
                cutoff = now - 3600
                self.user_timestamps = {
                    uid: ts for uid, ts in self.user_timestamps.items() if ts > cutoff
                }
            last_time = self.user_timestamps.get(user_id, 0)
            if now - last_time < self.limit_seconds:
                if isinstance(event, CallbackQuery):
                    await event.answer("подождите пару секунд...", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("пожалуйста, не спамьте. подождите пару секунд.")
                return
            self.user_timestamps[user_id] = now

        return await handler(event, data)
