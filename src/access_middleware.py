from typing import Dict
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import Message

from config import Config

config = Config()


class AccessMiddleware(BaseMiddleware):
    """Проверка доступа к боту."""

    async def on_process_message(self, message: Message, data: Dict):
        user_id = message.from_user.id
        if user_id not in config.AUTHORIZED_USERS_IDS:
            msg = 'Доступ запрещен'
            await message.reply(msg)
            raise CancelHandler()
