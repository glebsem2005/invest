import asyncio
import asyncpg
import logging
from typing import Optional
logger = logging.getLogger(__name__)

class SQLAuthChecker:
    """ТОЛЬКО проверка авторизации в существующей базе. БЕЗ создания таблиц и пользователей!"""
    
    def __init__(self, connection_string: str):
        """
        Инициализация проверки авторизации
        
        Args:
            connection_string: Строка подключения к PostgreSQL
            Пример: "postgresql://user:password@host:port/database"
        """
        self.connection_string = connection_string
        self.pool = None
        
    async def init_pool(self):
        """Инициализация пула подключений"""
        try:
            self.pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=1,
                max_size=5,
                command_timeout=30
            )
            logger.info("Подключение к существующей базе данных установлено")
            
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise
    
    async def check_user_authorization(self, user_id: int) -> bool:
        """
        ТОЛЬКО проверяет авторизован ли пользователь в существующей базе
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            bool: True если пользователь найден в базе, False если нет
        """
        if not self.pool:
            logger.error("Нет подключения к базе данных")
            return False
        
        try:
            async with self.pool.acquire() as conn:
                # Проверяем есть ли пользователь в базе
                result = await conn.fetchrow(
                    "SELECT users_id, email FROM users WHERE users_id = $1",
                    user_id
                )
                
                if result:
                    logger.info(f"✅ Пользователь {user_id} найден в базе - доступ разрешен")
                    return True
                else:
                    logger.info(f"❌ Пользователь {user_id} НЕ найден в базе - доступ запрещен")
                    return False
                    
        except Exception as e:
            logger.error(f"Ошибка проверки пользователя {user_id}: {e}")
            # В случае ошибки БД - запрещаем доступ
            return False
    
    async def get_user_email(self, user_id: int) -> Optional[str]:
        """
        НОВЫЙ МЕТОД: Получает email пользователя из базы данных
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            str: Email пользователя или None если не найден
        """
        if not self.pool:
            logger.error("Нет подключения к базе данных")
            return None
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(
                    "SELECT email FROM authorized_users WHERE user_id = $1 AND is_active = TRUE",
                    user_id
                )
                
                if result and result['email']:
                    logger.info(f"Email для пользователя {user_id}: {result['email']}")
                    return result['email']
                else:
                    logger.warning(f"Email не найден для пользователя {user_id}")
                    return None
                    
        except Exception as e:
            logger.error(f"Ошибка получения email для пользователя {user_id}: {e}")
            return None
    
    async def close_pool(self):
        """Закрывает подключение к базе"""
        if self.pool:
            await self.pool.close()
            logger.info("Подключение к базе данных закрыто")

# Глобальный экземпляр проверки авторизации
auth_checker: Optional[SQLAuthChecker] = None

async def init_auth_system(connection_string: str):
    """Инициализация системы проверки авторизации"""
    global auth_checker
    auth_checker = SQLAuthChecker(connection_string)
    await auth_checker.init_pool()
    return auth_checker

async def check_user_authorized(user_id: int) -> bool:
    """Быстрая проверка авторизации пользователя"""
    if auth_checker:
        return await auth_checker.check_user_authorization(user_id)
    return False

async def get_user_email(user_id: int) -> Optional[str]:
    """НОВАЯ ФУНКЦИЯ: Получает email пользователя"""
    if auth_checker:
        return await auth_checker.get_user_email(user_id)
    return None