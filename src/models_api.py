import logging
from abc import ABC, abstractmethod
from typing import Dict, List

import aiolimiter

from openai import AsyncOpenAI

from config import Config
from excel_file_manager import ExcelFileManager

logger = logging.getLogger('bot')
config = Config()


class ModelStrategy(ABC):
    """Абстрактный класс для стратегий взаимодействия с моделями."""

    @abstractmethod
    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Получает ответ от модели на основе списка сообщений."""
        ...


class ChatGPTStrategy(ModelStrategy):
    """Стратегия для взаимодействия с ChatGPT через OpenAI API с лимитом запросов."""

    _limiter = AsyncLimiter(max_rate=3, time_period=1.0)  # ⬅️ лимит: 3 запроса в секунду (настраивается)

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.OPENAI_MODEL
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

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
        """Отправляет запрос к ChatGPT с ограничением по частоте запросов и повторными попытками."""
        logger.info(f'[{self.__class__.__name__}] Отправка запроса, модель: {self.model}')
        logger.debug(f'[{self.__class__.__name__}] {self._format_messages_for_log(messages)}')

        for attempt in range(3):  # ⬅️ максимум 3 попытки при ошибке 429
            try:
                async with self._limiter:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        web_search_options={},  # поддерживается только gpt-4o
                    )

                content = response.choices[0].message.content.strip()
                token_usage = getattr(response.usage, 'completion_tokens', 'неизвестно')
                logger.info(
                    f'[{self.__class__.__name__}] Получен ответ, длина: {len(content)} символов, использовано токенов: {token_usage}'
                )
                return content

            except Exception as e:
                if '429' in str(e):
                    wait = 2 ** attempt
                    logger.warning(f'[{self.__class__.__name__}] Превышен лимит запросов, повтор через {wait}с...')
                    await asyncio.sleep(wait)
                else:
                    logger.error(f'[{self.__class__.__name__}] Ошибка при запросе: {e}')
                    raise ValueError(f'Не удалось получить ответ от ChatGPT: {e}')

        raise RuntimeError("Слишком много попыток из-за превышения лимита")


class ChatGPTFileStrategy(ModelStrategy):
    """Стратегия для взаимодействия с ChatGPT через OpenAI API для обработки файлов."""

    def __init__(self) -> None:
        """Инициализирует клиент OpenAI с API-ключом из конфигурации."""
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.OPENAI_FILE_MODEL
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Отправляет запрос к ChatGPT и возвращает ответ."""
        try:
            logger.info(
                f'[{self.__class__.__name__}] Отправка запроса к файловой модели: {self.model}',
            )
            logger.debug(f'[{self.__class__.__name__}] Сообщения: {messages}')

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )

            content = response.choices[0].message.content.strip()
            token_usage = response.usage.completion_tokens if hasattr(response, 'usage') else 'неизвестно'
            logger.info(
                f'[{self.__class__.__name__}] Получен ответ от файловой модели, длина: {len(content)} символов, использовано токенов: {token_usage}',
            )
            return content
        except Exception as e:
            logger.error(f'[{self.__class__.__name__}] Ошибка при запросе к файловой модели: {e}')
            raise ValueError(f'Не удалось получить ответ от ChatGPT (файловая модель): {e}')


class ExcelSearchStrategy(ModelStrategy):
    """Стратегия для поиска в Excel файле с использованием OpenAI Vector Store."""

    def __init__(self) -> None:
        """Инициализирует клиент OpenAI с API-ключом из конфигурации."""
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.OPENAI_FILE_MODEL
        self._file_manager = ExcelFileManager()
        logger.info(f'Инициализирована стратегия {self.__class__.__name__} с моделью {self.model}')

    async def get_response(self, messages: List[Dict[str, str]]) -> str:
        """Находит наиболее релевантную информацию для запроса пользователя."""
        try:
            search_prompt = (
                'Найди в загруженном Excel файле подходящую информацию для запроса пользователя.\n'
                f"Запрос пользователя: {messages[-1]['content']}\n"
                'ОБЯЗАТЕЛЬНО верни заголовок таблицы и МИНИМУМ ТРИ строки, которые потенциально подходят под запрос пользователя!\n'
                '!Строк должно быть по количеству НЕ МЕНЕЕ, чем попросил пользователь (можешь возвращать побольше)! Если пользователь не указал количество, то возвращай НЕ МЕНЕЕ 3 СТРОК!!!\n'
                '!Релевантными строками считаются те, которые удовлетворяют хотя бы одному критерию в запросе пользователя!\n'
                'Не добавляй никаких пояснений или дополнительного текста!\n'
                'Пример формата ответа (здесь одна строка после заголовка таблицы, но ты возвращай больше!):\n'
                'Полное юридическое название Вашей|Наименование организации|Создание|Последнее изменение|ИНН|Год регистрации|Сайт|Страна юрисдикции|Краткое описание проекта|Бизнес-модели|Страна Где базируется проект|Город Где базируется проект|Индустрии|Технологии|Стадия продукта|Видео о продукте|Проблема, которую решает проект|Целевая аудитория|Рынки, на которых Вы работаете|Продажи|Оборот в год Оборот в год (в USD)|Прямые конкуренты|Преимущества перед конкурентами|Количество сотрудников|Укажите, какие ключевые должности|Если вы В2В-, В2G-, B2B2C-, В2О- стартап: у|С кем был успешный кейс? Описание и|Заинтересованы ли вы в пилотирова|Предлагаемый кейс|Есть ли у Вас опыт взаимодействия|Объем ранее привлеченных инвестиц|Какую потребность Экосистемы Сбер|Подавались ранее в sber500?|Выручка за последний месяц|Выручка за последние 3 месяца|Количество активных или платящих|заменяет ли ваш продукт какие-либо аналогичные сервисы или компании|названия заменяемых сервисов/компаний|как именно вы заменяете перечисленные сервисы/компании|преимущества перед перечисленными сервисами/компаниями\n'
                'ООО "ВАРТЕХ"|МБонус|2021-05-05 18:10:11|2022-07-29 13:39:21|7801690817|2020|https://vartech24.ru|Россия|МБонус - это первый в России сервис управления сдельной оплатой труда и сквозной мотивации продавцов, консультантов и партнеров, с мгновенным доступом к заработанным деньгам.||Россия|Санкт-Петербург|[FinTech, Retail, HR-Tech]|[Mobile, Payments and Transactions, SaaS, Computer Vision]|[MVP, первые продажи]||1. Автоматизация постановки задач, учета выполнения и взаиморасчетов с исполнителями. 2. Мгновенные выплаты физ лицам, самозанятым и ИП. 3. Увеличение продаж товаров/услуг/выполнения KPI. 4. Низкая лояльность персонала к работодателю. 5. Высокие финансовые издержки при работе с исполнителями.|1. Сервисы такси, доставки 3. Курьерские службы 4. Call-центры 5. Аптечные сети 6. Розничые магазины и производители: электроники, бытовых товаров, товаров для ремонта, парфюмерии и косметики, авто-товаров, БАД и лекарств, алкоголя, зоотоваров.|[Россия]|[Есть продажи в РФ]|44 780|Прямых конкурентов нет.|Возможность полностью автоматизировать сдельную оплату труда, запуск промо-акций мгновенно, рямая коммуникация с продавцами, озможность мгновенно выплачивать бонусы на любую карту или телефон, не нужны предоплаченные карты или промокоды, собственное фондирование для срочный выплат.|4|(ГЕНЕРАЛЬНЫЙ ДИРЕКТОР,Опыт предпринимательской деятельности более 10 лет. Собственные проекты в рознице и бьюти.);(Коммерческий директор,Опыт работы в крупных международных фарм компаниях 9 лет, опыт предпринимательской деятельности более 5 лет. Собственный проект аптечного партнерства.);(Менеджер по работе с клиентами,В продажа более 10 лет.);(ИТ-директор,Опыт в ИТ более 10 лет. Собственная ИТ компания.)|True||True|Автоматизация взаиморасчетов с исполнителями (самозанятые, ИП, сотрудники в найме) на основании выполненных задач, результатов. Возможность выплат вознаграждения/оклада по требованию исполнителя в любое время.||0|||||||||'
            )

            response = await self.client.responses.create(
                model=self.model,
                input=search_prompt,
                tools=[{
                    'type': 'file_search',
                    'vector_store_ids': [self._file_manager._vector_store_id],
                }],
                include=['file_search_call.results'],
            )

            content = response.output[1].content[0].text.strip()
            logger.info(f'Получен ответ, длина: {len(content)} символов, текст: `{content}`')
            return content

        except Exception as e:
            logger.error(f'Ошибка при поиске в excel file: {e}')
            raise ValueError(f'Не удалось найти релевантную информацию: {e}')


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
