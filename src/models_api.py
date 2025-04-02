from abc import ABC, abstractmethod
from typing import Dict, List
import logging
from openai import AsyncOpenAI
from openai.types.chat.completion_create_params import WebSearchOptions
from config import Config


logger = logging.getLogger('bot')
config = Config()


class ModelStrategy(ABC):
    """Абстрактный класс для стратегий взаимодействия с моделями."""

    @abstractmethod
    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Получает ответ от модели на основе списка сообщений."""
        ...


class ChatGPTStrategy(ModelStrategy):
    """Стратегия для взаимодействия с ChatGPT через OpenAI API."""

    def __init__(self) -> None:
        """Инициализирует клиент OpenAI с API-ключом из конфигурации."""
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.OPENAI_MODEL
        self.max_tokens = int(config.OPENAI_MAX_TOKENS)
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к ChatGPT и возвращает ответ."""
        try:
            logger.info(f'[{self.__class__.__name__}] Отправка запроса, модель: {self.model}')
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                web_search_options=WebSearchOptions(search_context_size='high'),
            )

            content = response.choices[0].message.content.strip()
            logger.info(f'[{self.__class__.__name__}] Получен ответ, длина: {len(content)} символов')
            return content
        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] Ошибка при запросе: {e}')
            raise ValueError(f'Не удалось получить ответ от ChatGPT: {e}')


class ChatGPTFileStrategy(ModelStrategy):
    """Стратегия для взаимодействия с ChatGPT через OpenAI API для обработки файлов."""

    def __init__(self) -> None:
        """Инициализирует клиент OpenAI с API-ключом из конфигурации."""
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.OPENAI_FILE_MODEL
        self.max_tokens = int(config.OPENAI_MAX_TOKENS)
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к ChatGPT и возвращает ответ."""
        try:
            logger.info(f'[{self.__class__.__name__}] Отправка запроса к файловой модели: {self.model}')
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
            )

            content = response.choices[0].message.content.strip()
            logger.info(
                f'[{self.__class__.__name__}] Получен ответ от файловой модели, длина: {len(content)} символов'
            )
            return content
        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] Ошибка при запросе к файловой модели: {e}')
            raise ValueError(f'Не удалось получить ответ от ChatGPT (файловая модель): {e}')


class ModelAPI:
    """Фасад для взаимодействия с различными моделями."""

    def __init__(self, strategy: ModelStrategy) -> None:
        """Инициализирует API с выбранной стратегией."""
        self._strategy = strategy
        logger.info(f'Инициализирован ModelAPI с стратегией {strategy.__class__.__name__}')

    @property
    def strategy(self) -> ModelStrategy:
        """Возвращает текущую стратегию."""
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: ModelStrategy) -> None:
        """Устанавливает новую стратегию."""
        logger.info(f'Смена стратегии с {self._strategy.__class__.__name__} на {strategy.__class__.__name__}')
        self._strategy = strategy

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Получает ответ от модели с использованием текущей стратегии."""
        logger.info(f'Запрос ответа через стратегию {self._strategy.__class__.__name__}')
        return await self._strategy.get_response(messages)
