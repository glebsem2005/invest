import os
from typing import List, Optional, Set

from dotenv import dotenv_values, load_dotenv

config = {
    **dotenv_values('.env'),
    **os.environ,
}

load_dotenv()


class ConfigError(Exception): ...


class Config:
    _users = None
    _admin_users = None
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
            return "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"
        raise ConfigError('Please set `OPENAI_API_KEY` env var.')

    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-2024-08-06')
    OPENAI_MAX_TOKENS = os.getenv('OPENAI_MAX_TOKENS', 1000)
    OPENAI_MAX_TOKENS_DETAIL = os.getenv('OPENAI_MAX_TOKENS_DETAIL', 3000)
    OPENAI_FILE_MODEL = os.getenv('OPENAI_FILE_MODEL', 'gpt-4o')

    @property
    def VECTOR_STORE_ID(self) -> Optional[str]:
        VECTOR_STORE_ID = os.getenv('VECTOR_STORE_ID')
        if VECTOR_STORE_ID:
            return str(VECTOR_STORE_ID)
        return None
