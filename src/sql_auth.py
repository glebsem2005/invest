import asyncio
import asyncpg
import logging
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

class SQLAuthChecker:
    """ТОЛЬКО исправление порта - все остальное как было"""
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool = None
        
        # Парсим строку и исправляем порт если нужно
        parsed = urllib.parse.urlparse(connection_string)
        if parsed.port != 17143:
            logger.warning(f"⚠️ Неверный порт {parsed.port}, исправляем на 17143")
            # Пересобираем строку с правильным портом
            new_netloc = f"{parsed.username}:{parsed.password}@{parsed.hostname}:17143"
            self.connection_string = urllib.parse.urlunparse((
                parsed.scheme, new_netloc, parsed.path, 
                parsed.params, parsed.query, parsed.fragment
            ))
        
        logger.info(f"🔧 Используем строку: {self.connection_string}")
        
    async def init_pool(self):
        """Создание пула с ЯВНЫМИ параметрами вместо строки"""
        try:
            logger.info("🔧 Создание пула PostgreSQL...")
            
            # Парсим строку на компоненты
            parsed = urllib.parse.urlparse(self.connection_string)
            
            # Создаем пул с явными параметрами
            self.pool = await asyncpg.create_pool(
                host=parsed.hostname,
                port=parsed.port or 17143,  # Явно указываем порт
                database=parsed.path.lstrip('/'),
                user=parsed.username,
                password=parsed.password,
                min_size=1,
                max_size=5,
                command_timeout=60,
                server_settings={
                    'application_name': 'startup_bot_reader'
                }
            )
            
            logger.info("✅ Пул создан успешно")
            
            # Тест подключения
            async with self.pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"📄 PostgreSQL: {version[:60]}...")
                
        except Exception as e:
            logger.error(f"❌ Ошибка создания пула: {e}")
            raise
    
    async def check_user_authorization(self, user_id: int) -> bool:
        """Проверка авторизации пользователя"""
        if not self.pool:
            logger.error("❌ Пул не инициализирован")
            return False
        
        try:
            async with self.pool.acquire() as conn:
                # Преобразуем int в str, так как поле users_id имеет тип TEXT
                result = await conn.fetchrow(
                    "SELECT users_id FROM users WHERE users_id = $1",
                    str(user_id)  # ИСПРАВЛЕНО: передаем строку вместо числа
                )
                
                if result:
                    logger.info(f"✅ Пользователь {user_id} авторизован")
                    return True
                else:
                    logger.info(f"❌ Пользователь {user_id} не найден")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Ошибка проверки пользователя {user_id}: {e}")
            return False
    
    async def close_pool(self):
        """Закрытие пула"""
        if self.pool:
            await self.pool.close()
            logger.info("✅ Пул закрыт")

# Глобальная переменная
auth_checker: Optional[SQLAuthChecker] = None

async def init_auth_system(connection_string: str):
    """Инициализация системы авторизации"""
    global auth_checker
    
    logger.info("🚀 Инициализация системы авторизации...")
    
    auth_checker = SQLAuthChecker(connection_string)
    await auth_checker.init_pool()
    
    logger.info("✅ Система авторизации готова")
    return auth_checker

async def check_user_authorized(user_id: int) -> bool:
    """Проверка авторизации пользователя"""
    if auth_checker:
        return await auth_checker.check_user_authorization(user_id)
    else:
        logger.error("❌ Система авторизации не инициализирована")
        return False

async def close_auth_system():
    """Закрытие системы авторизации"""
    global auth_checker
    if auth_checker:
        await auth_checker.close_pool()
        auth_checker = None