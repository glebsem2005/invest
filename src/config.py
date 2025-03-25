import os
from typing import List, Set
from dotenv import load_dotenv, dotenv_values


config = {
    **dotenv_values('.env'),
    **os.environ,
}

load_dotenv()


class ConfigError(Exception): ...


class Config:
    @property
    def TOKEN(self) -> str:
        TOKEN = os.getenv('TOKEN')
        if TOKEN:
            return str(TOKEN)
        raise ConfigError('Please set `TOKEN` env var.')

    @property
    def OWNER_USER(self) -> int:
        OWNER_USER = os.getenv('OWNER_USER')
        if OWNER_USER:
            return int(OWNER_USER)
        raise ConfigError('Please set `OWNER_USER` env var.')

    @property
    def ADMIN_USERS(self) -> List[str]:
        ADMIN_USERS = os.getenv('ADMIN_USER')
        if ADMIN_USERS:
            return [int(user.strip()) for user in ADMIN_USERS.strip().split(',')]
        raise ConfigError('Please set `ADMIN_USERS` env var.')

    @property
    def USERS(self) -> List[int]:
        USERS = os.getenv('USERS')
        if USERS:
            return [int(user.strip()) for user in USERS.strip().split(',')]
        raise ConfigError('Please set `USERS` env var.')

    @property
    def AUTHORIZED_USERS_IDS(self) -> Set[int]:
        return set([self.OWNER_USER] + self.ADMIN_USERS + self.USERS)
