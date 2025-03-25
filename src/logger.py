import logging
from typing import Any, Dict


class LoggerMeta(type):
    _instances: Dict[type, Any] = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class Logger(metaclass=LoggerMeta):
    def __init__(self) -> None:
        self._setup_loggers()

    def _setup_loggers(self) -> None:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(lineno)s - %(message)s')

        bot_logger = logging.getLogger('bot')
        if not bot_logger.hasHandlers():
            bot_handler = logging.StreamHandler()
            bot_handler.setFormatter(formatter)
            bot_logger.setLevel(logging.DEBUG)
            bot_logger.addHandler(bot_handler)
            bot_logger.propagate = False
