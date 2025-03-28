from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware
import logging
from config import Config

config = Config()
logger = logging.getLogger('bot')


class AccessMiddleware(BaseMiddleware):
    """Middleware для проверки доступа пользователя к боту."""

    async def on_pre_process_message(self, message: types.Message, data: dict):
        """Проверяет доступ пользователя перед обработкой сообщения."""
        user_id = message.from_user.id
        
        if user_id in config.BLOCKED_USERS:
            logger.warning(f'Заблокированный пользователь {user_id} пытается использовать бота')
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        """Проверяет доступ пользователя перед обработкой callback query."""
        user_id = callback_query.from_user.id
        
        if user_id in config.BLOCKED_USERS:
            logger.warning(f'Заблокированный пользователь {user_id} пытается использовать бота')
            raise CancelHandler()