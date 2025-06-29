import os
from typing import List, Optional, Set
from dotenv import dotenv_values, load_dotenv

config = {
    **dotenv_values('.env'),
    **os.environ,
}
load_dotenv()

class ConfigError(Exception): 
    pass

class Config:
    _users = None
    _admin_users = None  # Fixed the asterisk issue
    _blocked_users = set()
    
    @property
    def TOKEN(self) -> str:
        TOKEN = os.getenv('TOKEN')
        if TOKEN:
            return str(TOKEN)
        raise ConfigError('Please set `TOKEN` env var.')
    
    @property
    def OWNER_ID(self) -> int:
        OWNER_ID = os.getenv('OWNER_ID')
        if OWNER_ID:
            return int(OWNER_ID)
        raise ConfigError('Please set `OWNER_ID` env var.')
    
    @property
    def ADMIN_USERS(self) -> List[int]:
        if self._admin_users is not None:
            return self._admin_users
        ADMIN_USERS = os.getenv('ADMIN_USERS')
        if ADMIN_USERS:
            self._admin_users = [int(user.strip()) for user in ADMIN_USERS.strip().split(',')]
            return self._admin_users
        raise ConfigError('Please set `ADMIN_USERS` env var.')
    
    @property
    def USERS(self) -> List[int]:
        if self._users is not None:
            return self._users
        USERS = os.getenv('USERS')
        if USERS:
            self._users = [int(user.strip()) for user in USERS.strip().split(',')]
            return self._users
        raise ConfigError('Please set `USERS` env var.')

    @property
    def AUTHORIZED_USERS_IDS(self) -> Set[int]:
        return set([self.OWNER_ID] + self.ADMIN_USERS + self.USERS)
    
    @property
    def BLOCKED_USERS(self) -> Set[int]:
        return self._blocked_users
    
    @property
    def OPENAI_API_KEY(self) -> str:
        OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
        if OPENAI_API_KEY:
            return OPENAI_API_KEY
        raise ConfigError('Please set `OPENAI_API_KEY` env var.')
    
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')
    OPENAI_MAX_TOKENS = os.getenv('OPENAI_MAX_TOKENS', 1000)
    OPENAI_MAX_TOKENS_DETAIL = os.getenv('OPENAI_MAX_TOKENS_DETAIL', 3000)
    OPENAI_FILE_MODEL = os.getenv('OPENAI_FILE_MODEL', 'gpt-4o')
    
    @property
    def VECTOR_STORE_ID(self) -> Optional[str]:
        VECTOR_STORE_ID = os.getenv('VECTOR_STORE_ID')
        if VECTOR_STORE_ID:
            return str(VECTOR_STORE_ID)
        return None
    
    # SMTP Configuration - Now properly indented inside the class
    @property
    def SMTP_SERVER(self) -> str:
        return os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    
    @property  
    def SMTP_PORT(self) -> int:
        return int(os.getenv('SMTP_PORT', '587'))
    
    @property
    def EMAIL_USER(self) -> Optional[str]:
        EMAIL_USER = os.getenv('EMAIL_USER')
        if EMAIL_USER:
            return str(EMAIL_USER)
        return None
    
    @property
    def EMAIL_PASSWORD(self) -> Optional[str]:
        EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD') 
        if EMAIL_PASSWORD:
            return str(EMAIL_PASSWORD)
        return None
    
    @property
    def SENDER_NAME(self) -> str:
        return os.getenv('SENDER_NAME', 'Investment Analysis Bot')

    @property
    def SQL_CONNECTION_STRING(self) -> str:
        """
        Database connection string for admin bot (full permissions)
        """
        SQL_CONNECTION_STRING = os.getenv('SQL_CONNECTION_STRING')
        if SQL_CONNECTION_STRING:
            return str(SQL_CONNECTION_STRING)
        # Fallback to hardcoded value
        return "postgresql://postgres:jNtiIokjoySRemHIhgvjunFtmBLaRYLr@switchyard.proxy.rlwy.net:17143/railway"

    @property
    def SQL_CONNECTION_STRING_READER(self) -> str:
        """
        Database connection string for reader bots (read-only permissions)
        """
        SQL_CONNECTION_STRING_READER = os.getenv('SQL_CONNECTION_STRING_READER')
        if SQL_CONNECTION_STRING_READER:
            return str(SQL_CONNECTION_STRING_READER)
        # Fallback to hardcoded value
        return "postgresql://postgres:jNtiIokjoySRemHIhgvjunFtmBLaRYLr@switchyard.proxy.rlwy.net:17143/railway"
