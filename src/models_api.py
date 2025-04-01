from abc import ABC, abstractmethod
from typing import Dict, List
import logging
from openai import AsyncOpenAI
from openai.types.chat.completion_create_params import WebSearchOptions
from config import Config
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
import httpx


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


class GigaChatStrategy(ModelStrategy):
    """Стратегия для взаимодействия с GigaChat."""

    def __init__(self) -> None:
        """Инициализирует клиент GigaChat с учетными данными из конфигурации."""
        self.GigaChat = GigaChat
        self.Chat = Chat
        self.Messages = Messages
        self.MessagesRole = MessagesRole

        self.client = GigaChat(
            credentials=config.GIGACHAT_API_KEY,
            verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
            scope=config.GIGACHAT_SCOPE,
        )
        self.model = config.GIGACHAT_MODEL
        self.max_tokens = config.GIGACHAT_MAX_TOKENS
        self.temperature = config.GIGACHAT_TEMPERATURE
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к GigaChat и возвращает ответ."""
        try:
            logger.info(f'[{self.__class__.__name__}] Отправка запроса, модель: {self.model}')
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            gigachat_messages = []

            for message in messages:
                role = message['role']
                content = message['content']

                gigachat_roles = {
                    'user': self.MessagesRole.USER,
                    'assistant': self.MessagesRole.ASSISTANT,
                    'system': self.MessagesRole.SYSTEM,
                }

                gigachat_role = gigachat_roles[role]
                gigachat_messages.append(self.Messages(role=gigachat_role, content=content))

            chat = self.Chat(
                messages=gigachat_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                model=self.model,
            )

            response = await self.client.achat(chat)

            content = response.choices[0].message.content.strip()
            logger.info(f'[{self.__class__.__name__}] Получен ответ, длина: {len(content)} символов')
            return content
        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] Ошибка при запросе: {e}')
            raise ValueError(f'Не удалось получить ответ от GigaChat: {e}')


class PerplexityStrategy(ModelStrategy):
    """Стратегия для взаимодействия с Perplexity API."""

    def __init__(self) -> None:
        """Инициализирует клиент Perplexity с API-ключом из конфигурации."""
        self.httpx = httpx

        self.api_key = config.PERPLEXITY_API_KEY
        self.api_url = 'https://api.perplexity.ai/chat/completions'
        self.model = config.PERPLEXITY_MODEL
        self.max_tokens = int(config.PERPLEXITY_MAX_TOKENS)
        self.temperature = float(config.PERPLEXITY_TEMPERATURE)
        self.top_p = float(config.PERPLEXITY_TOP_P)

        self.search_context_size = config.PERPLEXITY_SEARCH_CONTEXT_SIZE
        self.frequency_penalty = int(config.PERPLEXITY_FREQUENCY_PENALTY)
        self.presence_penalty = int(config.PERPLEXITY_PRESENCE_PENALTY)
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к Perplexity API и возвращает ответ."""
        try:
            logger.info(f'[{self.__class__.__name__}] Отправка запроса, модель: {self.model}')
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }

            payload = {
                'model': self.model,
                'messages': messages,
                'max_tokens': self.max_tokens,
                'temperature': self.temperature,
                'top_p': self.top_p,
                'frequency_penalty': self.frequency_penalty,
                'presence_penalty': self.presence_penalty,
                'web_search_options': {'search_context_size': self.search_context_size},
            }

            async with self.httpx.AsyncClient() as client:
                response = await client.post(self.api_url, headers=headers, json=payload, timeout=60.0)

                if response.status_code != 200:
                    error_message = f'Ошибка API Perplexity: {response.status_code} - {response.text}'
                    logger.error(f'[{self.__class__.__name__}] {error_message}')
                    raise ValueError(error_message)

                response_data = response.json()
                content = response_data['choices'][0]['message']['content'].strip()
                logger.info(f'[{self.__class__.__name__}] Получен ответ, длина: {len(content)} символов')
                return content

        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] Ошибка при запросе: {e}')
            raise ValueError(f'Не удалось получить ответ от Perplexity API: {e}')


class DeepseekStrategy(ModelStrategy):
    """Стратегия для взаимодействия с Deepseek API."""

    def __init__(self) -> None:
        """Инициализирует клиент Deepseek с API-ключом из конфигурации."""
        self.client = AsyncOpenAI(api_key=config.DEEPSEEK_API_KEY, base_url='https://api.deepseek.com')
        self.model = config.DEEPSEEK_MODEL
        self.max_tokens = int(config.DEEPSEEK_MAX_TOKENS)
        self.temperature = float(config.DEEPSEEK_TEMPERATURE)
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к Deepseek API и возвращает ответ."""
        try:
            logger.info(f'[{self.__class__.__name__}] Отправка запроса, модель: {self.model}')
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            content = response.choices[0].message.content.strip()
            logger.info(f'[{self.__class__.__name__}] Получен ответ, длина: {len(content)} символов')
            return content
        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] Ошибка при запросе: {e}')
            raise ValueError(f'Не удалось получить ответ от Deepseek API: {e}')


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
