import logging
from abc import ABC, abstractmethod
from typing import Dict, List

from openai import AsyncOpenAI

from config import Config

logger = logging.getLogger('bot')
config = Config()


class ModelStrategy(ABC):
    """Абстрактный класс для стратегий взаимодействия с моделями."""

    @abstractmethod
    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Получает ответ от модели на основе списка сообщений."""
        ...

    @property
    @abstractmethod
    def max_tokens(self) -> int:
        """Возвращает максимальное количество токенов для ответа."""
        ...

    @max_tokens.setter
    @abstractmethod
    def max_tokens(self, value: int) -> None:
        """Устанавливает максимальное количество токенов для ответа."""
        ...


class ChatGPTStrategy(ModelStrategy):
    """Стратегия для взаимодействия с ChatGPT через OpenAI API."""

    def __init__(self) -> None:
        """Инициализирует клиент OpenAI с API-ключом из конфигурации."""
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.OPENAI_MODEL
        self._max_tokens = int(config.OPENAI_MAX_TOKENS)
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    @property
    def max_tokens(self) -> int:
        """Возвращает максимальное количество токенов для ответа."""
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        """Устанавливает максимальное количество токенов для ответа."""
        self._max_tokens = value
        logger.info(f'[{self.__class__.__name__}] Установлен лимит токенов: {value}')

    def _format_messages_for_log(self, messages: list, max_len: int = 50) -> str:
        lines = [f'Отправка сообщений в модель (всего: {len(messages)}):']
        for idx, msg in enumerate(messages, 1):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            content_len = len(content)
            if content_len > max_len:
                display_content = content[:max_len].replace('\n', ' ').replace('\r', ' ') + '... (truncated)'
            else:
                display_content = content.replace('\n', ' ').replace('\r', ' ')
            lines.append(f'  {idx}. role={role}; len={content_len}; text="{display_content}"')
        return '\n'.join(lines)

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к ChatGPT и возвращает ответ."""
        try:
            logger.info(
                f'[{self.__class__.__name__}] Отправка запроса, модель: {self.model}, max_tokens: {self._max_tokens}'
            )
            logger.debug(f'[{self.__class__.__name__}] {self._format_messages_for_log(messages)}')

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                # max_tokens=self._max_tokens,  # INFO: согласно доке теперь это параметр max_completion_tokens, попробуем временнно вообще убрать (https://platform.openai.com/docs/api-reference/chat)
                # web_search_options=WebSearchOptions(search_context_size='high'),  # COMMENT: только модель gpt-4o поддерживает поиск
                web_search_options={},
            )

            content = response.choices[0].message.content.strip()
            token_usage = response.usage.completion_tokens if hasattr(response, 'usage') else 'неизвестно'
            logger.info(
                f'[{self.__class__.__name__}] Получен ответ, длина: {len(content)} символов, использовано токенов: {token_usage}'
            )
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
        self._max_tokens = int(config.OPENAI_MAX_TOKENS)
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    @property
    def max_tokens(self) -> int:
        """Возвращает максимальное количество токенов для ответа."""
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        """Устанавливает максимальное количество токенов для ответа."""
        self._max_tokens = value
        logger.info(f'[{self.__class__.__name__}] Установлен лимит токенов: {value}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к ChatGPT и возвращает ответ."""
        try:
            logger.info(
                f'[{self.__class__.__name__}] Отправка запроса к файловой модели: {self.model}, max_tokens: {self._max_tokens}'
            )
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )

            content = response.choices[0].message.content.strip()
            token_usage = response.usage.completion_tokens if hasattr(response, 'usage') else 'неизвестно'
            logger.info(
                f'[{self.__class__.__name__}] Получен ответ от файловой модели, длина: {len(content)} символов, использовано токенов: {token_usage}'
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

    @property
    def max_tokens(self) -> int:
        """Возвращает максимальное количество токенов для ответа."""
        return self._strategy.max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        """Устанавливает максимальное количество токенов для ответа."""
        self._strategy.max_tokens = value

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Получает ответ от модели с использованием текущей стратегии."""
        logger.info(f'Запрос ответа через стратегию {self._strategy.__class__.__name__}')
        return await self._strategy.get_response(messages)
