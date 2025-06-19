import html
import logging
import re
import traceback
import json
import os
import smtplib
from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple
from docx import Document
from docx.shared import Inches
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import aiogram.utils.exceptions
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

from access_middleware import AccessMiddleware
from chat_context import ChatContextManager
from config import Config
from file_processor import FileProcessor
from keyboards_builder import Button, DynamicKeyboard, Keyboard
from logger import Logger
from models_api import ExcelFileManager, ExcelSearchStrategy, ModelAPI
from prompts import DEFAULT_PROMPTS_DIR, Models, SystemPrompt, SystemPrompts, Topics

Logger()
logger = logging.getLogger('bot')
config = Config()

class EmailSender:
    """Класс для отправки email с отчетами."""
    
    def __init__(self):
        # Настройки email из config
        self.smtp_server = config.SMTP_SERVER
        self.smtp_port = config.SMTP_PORT  
        self.email_user = config.EMAIL_USER
        self.email_password = config.EMAIL_PASSWORD
        self.sender_name = config.SENDER_NAME
        
        if not self.email_user or not self.email_password:
            logger.warning("Email credentials not configured. Email sending will not work.")
    
    def _sanitize_filename(self, filename: str) -> str:
        """Очищает имя файла от недопустимых символов."""
        if not filename or not filename.strip():
            return 'unknown_company'
    
    # Убираем недопустимые символы для имени файла
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(filename))
    # Убираем пробелы в начале и конце
        sanitized = sanitized.strip()
    # Заменяем пробелы на подчеркивания
        sanitized = sanitized.replace(' ', '_')
    # Ограничиваем длину
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
    # Убираем точки в конце (проблемы в Windows)
        sanitized = sanitized.rstrip('.')
    
    # Проверяем, что результат не пустой
        if not sanitized:
            return 'unknown_company'
        
        return sanitized

    async def send_report(self, recipient_email: str, company_name: str, report_file_path: str, filename: str = None) -> bool:
        """Отправляет отчет на указанный email."""
        if not self.email_user or not self.email_password:
            logger.error("Email credentials not configured")
            return False
        
        try:
        # Создаем сообщение
            msg = MIMEMultipart()
            msg['From'] = f"{self.sender_name} <{self.email_user}>"
            msg['To'] = recipient_email
            msg['Subject'] = f"Инвестиционный анализ: {company_name}"
        
        # Текст письма
            body = f"""Здравствуйте!

Высылаем вам результаты инвестиционного анализа компании "{company_name}".

Отчет содержит:
- Анализ рынка и конкурентов
- Оценку инвестиционной привлекательности  
- Рекомендации по взаимодействию

С уважением,
Команда аналитиков"""
        
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Прикрепляем файл отчета
            if os.path.exists(report_file_path):
                with open(report_file_path, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
  
                encoders.encode_base64(part)
            
            # Формируем безопасное имя файла
                if filename:
                    safe_filename = self._sanitize_filename(filename)
                else:
                    safe_company_name = self._sanitize_filename(company_name)
                    safe_filename = f"investment_analysis_{safe_company_name}.docx"
            
            # Убеждаемся что имя файла не пустое
                if not safe_filename:
                    safe_filename = "investment_analysis_report.docx"
            
            # Используем правильный заголовок без лишних пробелов
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{safe_filename}"'
                )
                msg.attach(part)
            
                logger.info(f"Attached file with name: {safe_filename}")
            else:
                logger.error(f"Report file not found: {report_file_path}")
                return False
        
        # Отправляем email
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_user, self.email_password)
            text = msg.as_string()
            server.sendmail(self.email_user, recipient_email, text)
            server.quit()
        
            logger.info(f"Email successfully sent to {recipient_email}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to send email to {recipient_email}: {e}")
            return False

class UserStates(StatesGroup):
    ACCESS = State()
    CHOOSING_TOPIC = State()  # Выбор темы анализа
    CHOOSING_MODEL = State()  # Выбор модели
    ENTERING_PROMPT = State()  # Ввод запроса
    ATTACHING_FILE = State()  # Ожидание прикрепления файла
    UPLOADING_FILE = State()  # Загрузка файла
    ASKING_CONTINUE = State()  # Спрашиваем, есть ли еще вопросы
    CONTINUE_DIALOG = State()  # Продолжение диалога с той же моделью и темо
    ATTACHING_FILE_CONTINUE = State()  # Ожидание прикрепления файла при продолжении диалога
    UPLOADING_FILE_CONTINUE = State()  # Загрузка файла при продолжении диалога
    
    # Новые состояния для инвестиционного анализа
    INVESTMENT_ACTIONS = State()  # Выбор действия после executive summary
    INVESTMENT_QA = State()  # Режим вопросов-ответов по анализу
    INVESTMENT_REPORT_OPTIONS = State()  # Выбор способа получения отчета
    ENTERING_EMAIL = State()  # Ввод email для отправки отчета
    CHOOSING_FINAL_ACTION = State()  # НОВОЕ: Выбор после получения отчета



class AdminStates(StatesGroup):
    """Состояния для административных функций."""

    CHOOSING_PROMPT = State()  # Выбор промпта для обновления
    CHOOSING_PROMPT_TYPE = State()  # Выбор типа промпта для обновления (системный, детализированный или оба)
    UPLOADING_SYSTEM_PROMPT = State()  # Загрузка файла с новым системным промптом
    UPLOADING_DETAIL_PROMPT = State()  # Загрузка файла с новым детализированным промптом
    UPLOADING_PROMPT = State()  # Загрузка файла с новым промптом (для совместимости)
    NEW_PROMPT_NAME = State()  # Ввод технического имени нового топика
    NEW_PROMPT_DISPLAY = State()  # Ввод отображаемого имени нового топика
    NEW_PROMPT_UPLOAD = State()  # Загрузка файла с системным промптом
    NEW_PROMPT_UPLOAD_DETAIL = State()  # Загрузка файла с детализированным промптом
    UPLOADING_SCOUTING_FILE = State()  # Загрузка excel файла для скаутинга


class TopicKeyboard(DynamicKeyboard):
    """Клавиатура для выбора темы."""

    @classmethod
    def get_buttons(cls) -> Tuple[Button, ...]:
        """Генерирует кнопки на основе доступных топиков."""
        buttons = []

        for topic_name, topic in Topics.__members__.items():
            buttons.append(Button(text=topic.value, callback=f'topic_{topic_name}'))

        return tuple(buttons)


class FileAttachKeyboard(DynamicKeyboard):
    """Клавиатура для выбора прикрепления файла."""

    @classmethod
    def get_buttons(cls) -> Tuple[Button, ...]:
        """Возвращает кнопки для выбора прикрепления файла."""
        return (
            Button(text='Да, прикрепить файл', callback='attach_file'),
            Button(text='Нет, продолжить без файла', callback='no_file'),
        )


class ContinueKeyboard(Keyboard):
    """Клавиатура для продолжения диалога."""

    _buttons = (
        Button('Задать вопрос', 'continue_yes'),
        Button('Завершить чат', 'continue_no'),
    )


class AuthorizeKeyboard(Keyboard):
    """Клавиатура для авторизации."""

    _buttons = [Button('Авторизовать', 'authorize_yes'), Button('Отклонить', 'authorize_no')]


class AdminPromptKeyboard(DynamicKeyboard):
    """Клавиатура для выбора промпта администратором."""

    @classmethod
    def get_buttons(cls) -> Tuple[Button, ...]:
        """Генерирует кнопки на основе доступных системных промптов."""
        buttons = []

        for topic_name, topic in Topics.__members__.items():
            buttons.append(Button(text=topic.value, callback=f'prompt_{topic_name}'))

        return tuple(buttons)


class PromptTypeKeyboard(Keyboard):
    """Клавиатура для выбора типа промпта (системный, детализированный или оба)."""

    _buttons = (
        Button('Системный промпт', 'prompt_type_system'),
        Button('Детализированный промпт', 'prompt_type_detail'),
        Button('Оба промпта', 'prompt_type_both'),
    )


class InvestmentActionsKeyboard(Keyboard):
    """Клавиатура для действий после получения executive summary."""

    _buttons = (
        Button('Повторная генерация', 'investment_regenerate'),
        Button('Задать вопрос', 'investment_ask_question'),
        Button('Получить отчет', 'investment_get_report'),
    )


class InvestmentReportKeyboard(Keyboard):
    """Клавиатура для выбора способа получения отчета."""

    _buttons = (
        Button('Скачать отчет', 'investment_download'),
        Button('Выслать на почту', 'investment_email'),
        Button('← Назад', 'investment_back_to_actions'),
    )


class PromptTypeKeyboard(Keyboard):
    """Клавиатура для выбора типа промпта (системный, детализированный или оба)."""

    _buttons = (
        Button('Системный промпт', 'prompt_type_system'),
        Button('Детализированный промпт', 'prompt_type_detail'),
        Button('Оба промпта', 'prompt_type_both'),
    )


class InvestmentAnalysisProcessor:
    """Класс для обработки анализа инвестиционной привлекательности."""
    
    def __init__(self):
        self.analysis_prompt = """
Найди название компании в тексте и определи типы анализа.

ГЛАВНАЯ ЗАДАЧА: точно определить название компании.

Текст: "{user_text}"

Инструкции:
1. Найди название компании или бренда в тексте
2. Если названия нет, но есть описание ("фудтех стартап"), напиши "неизвестная_компания"
3. Определи нужные анализы:
   - market: 1 если нужен рыночный анализ (рынок, финансы, позиция)
   - rivals: 1 если нужен анализ конкурентов
   - synergy: 1 если нужен анализ синергии
   - Если тип анализа не указан, ставь все в 1

Ответ только JSON: {{"name": "название", "market": 1, "rivals": 1, "synergy": 1}}

Примеры:
"анализ Apple" → {{"name": "Apple", "market": 1, "rivals": 1, "synergy": 1}}
"Яндекс финансы" → {{"name": "Яндекс", "market": 1, "rivals": 1, "synergy": 1}}
"рынок Tesla" → {{"name": "Tesla", "market": 1, "rivals": 0, "synergy": 0}}
"""
        
        self.executive_summary_prompt = """
1. РОЛЬ

• Ты — инвестиционный профессионал с 50-летним опытом в корпоративном развитии и M&A, с глубоким опытом разработки экосистемных стратегий для Big Tech (Apple, Amazon, Yandex, Baidu, Tencent и пр.) и глубокими знаниями экономики на уровне нобелевских лауреатов по экономике.
• В твои обязанности входит поиск направлений развития экосистемы Сбера через M&A и стратегические партнерства. Ты по умолчанию можешь рассматривать конкурентов/ отдельные активы конкурентов как потенциальные цели для покупки, при этом партнерства с конкурентами не рассматриваются.
• Ты должен отвечать только на вопросы про развитие экосистемы Сбера. Если пользователь просить сделать допущение, проводи анализ с этим допущением.

2. КОНТЕКСТ

Сбер ищет направления для дальнейшего усиления и развития своей экосистемы для b2b и b2c клиентов, повышения липкости экосистемы для клиентов, масштабирования network эффекта.

Ключевые приоритеты стратегии Сбера:
• Развитие и коммерциализация искусственного интеллекта, антропоморфной робототехники, беспилотных технологий (наземные и воздушные беспилотники), микроэлектроники, квантовых вычислений и прочих наукоемких и высокотехнологичных направлений, в т.ч. встраивание данных технологий в традиционные модели бизнеса клиентов Сбера.
• Внедрение передовых ИИ-технологий и ИИ-агентов в клиентские пути и внутренние процессы банка и разработка ИИ-продуктов и ИИ-агентов для закрытия потребностей внешних b2b и b2c клиентов, решения их сложных повседневных задач.
• Развитие текущих и поиск новых частотных и гиперчастотных b2c сервисов (в т.ч. туризм) для экосистемы Сбера, поиск новых передовых бизнес-моделей.
• Развитие подписки СберПрайм: поиск новых частотных сервисов, развитие липкости и сетевого эффекта подписки, максимальная привязка клиентов к экосистеме Сбера.
• Дальнейшее развитие цифровых платежных решений и финансовых сервисов: SberPay, биометрия, Сбербанк Онлайн, обновление предложения для премиальных клиентов (СберБанк Первый, Private Banking), криптобиржи и DeFi при условии регулирования в РФ.
• Развитие b2b экосистемы Сбера через партнерства с лучшими рыночными провайдерами сервисов для бизнеса (Сбис, Контур и пр.).

Направления не интересные Сберу:
• Оффлайн-сервисы с традиционными бизнес-моделями (СТО, парикмахерские и пр.), традиционные индустрии (промышленность, добыча, энергетика, строительство и пр.).
• Высокорисковые бизнесы (беттинг, пиратство, офшоры, микрофинансовые организации и прочие компании с высоким санкционным или репутационным риском).

Текущий состав экосистемы Сбера:
• Подписка СберПрайм.
• Финансовые услуги: Сбер КИБ, ЮMoney, ЮKassa, Плати частями (BNPL-сервис), СберСтрахование, Эвотор.
• Электронная коммерция: Купер, МегаМаркет, Самокат, InSales.
• Медиа и развлечения: Okko, Звук, СоюзМультФильм, Рамблер.
• Образование: Алгоритмика, Фоксфорд, Нетология, Школа 21.
• Здравоохранение: СберЗдоровье.
• Мобильность: 2ГИС, СитиДрайв.
• Путешествия: Отелло
• Инфраструктурные объекты: Манжерок, Аэропорт Горно-Алтайск, Мрия, СберСити, сеть отделений Сбера.
• Маркетинг: SberAds, СберМаркетинг, Индекс 20.
• Классифайды: Работа.ру, СберАвто, ДомКлик.
• Телеком: СберМобайл.
• Технологии: Cloud, производитель дронов, Navio, Fusionbrain.ai, Kandinsky, GigaChat, SberDevices.

Подходы к корпоративному развитию:
• Конкуренты Сбера и их активы по умолчанию рассматриваются как доступные к покупке.
• Партнерство с основными конкурентами Сбера не рассматривается.
• Покупка/ партнерство с компаниями с малой рыночной долей не рассматривается.
• Основной фокус на покупку/ партнерство с лидерами рынка. Сбер готов монополизировать рынки.
• Антимонопольные риски, риски общественного резонанса и ESG-принципы не принимаются во внимание при анализе партнерства, не влияют на итоговую рекомендацию по формату партнерства.
• Если рынок зрелый и монополизирован (доля рынка компании-лидера превышает 60-70%), имеет смысл только покупка или партнерство с компанией-монополистом. Самостоятельный выход на рынок не рассматривается.
• В случае M&A приоритетной опцией является покупка 100% компании. Сбер старается избегать создания совместных предприятий. 
• Часто воспроизводство Сбером с нуля существующего бизнеса (greenfield) обходится дороже его покупки.
• У Сбера статус OFAC SDN (санкционные ограничения).

3. ПРИМЕР СТРУКТУРЫ РАССУЖДЕНИЙ

Этап 1. Рынок интересен Сберу, если он:
• Подходит под стратегию Сбера или создает новые точки роста для экосистемы
• Cоздаёт значимые синергии для экосистемы.
• Законен в РФ и не несет существенных репутационных рисков.

Этап 2. Компания-таргет интересна Сберу, если она:
• Входит в топ-3 лидеров рынка, имеет значимую долю рынка.
• Имеет уникальные технологии и экспертизу.
• Нет значимых рисков, связанных с интеграцией компании в экосистему Сбера.
В случае, если компания не интересна, необходимо рассмотреть других лидеров рынка.

Этап 3. Синергии являются значимыми, если:
• Объем синергий является значимым по сравнению со стоимостью M&A, партнерства или самостоятельной разработки.
• Понятна конкретная механика реализации синергий.
• Синергии оцениваются как на стороне экосистемы Сбера, так и на стороне компании-таргета.

Этап 4. Выбор формы сотрудничества.
• M&A если:
- Актив критичен для реализации стратегии Сбера.
- Нужен контроль над продуктом, в том числе для реализации синергий, глубокой интеграции в СБОЛ или другие сервисы экосистемы Сбера.
- Нужна передача критичных данных (в т.ч. персональных данных клиентов).
- Нужен быстрый выход на рынок.
- На рынке есть высокие барьеры входа, в т.ч. если рынок зрелый и монополизирован, более 60-70% рынка контролируется компанией-таргетом.
- Компания-таргет обладает уникальной экспертизой и технологиями.
• Greenfield если:
- Актив критичен для реализации стратегии Сбера.
- Нужен контроль над продуктом, в том числе для реализации синергий, глубокой интеграции в СБОЛ или другие сервисы экосистемы Сбера.
- Нужна передача критичных данных (в т.ч. персональных данных клиентов).
- Отсутствуют качественные компании-таргеты на рынке.
- Есть сильная экспертиза внутри Сбера.
• Партнерство если:
- Актив не подходит под ключевые направления развития стратегии Сбера.
- При этом есть значимые потенциальные синергии, которые можно реализовать в рамках коммерческого партнерства без контроля над продуктом.
- Есть санкционные риски в случае покупки компании с рынка.

4. ЗАДАЧА И ФОРМАТ ОТВЕТА

Проанализируй целесообразность партнерства Сбера с компанией [Название компании]. 

Ответ должен быть в формате executive summary для высшего руководства банка – простой текст объемом не более 250 слов с разбивкой на несколько абзацев. Ключевые выводы должны быть подтверждены числовыми данными, рыночной аналитикой, денежной оценкой. Необходимо приводить конкретные синергии с денежной оценкой и конкретные продуктовые интеграции. Обязательно давай ссылки на источники (с 2020 по 2025 г.).

Целевое содержание ответа: ключевой вывод о целесообразности сотрудничества и обоснование его формы (M&A, совместное предприятие, стратегическое партнерство, или уход в самостоятельную разработку), подтвержденный несколькими ключевыми тезисами, которые в том числе должны обязательно охватывать следующие вопросы: (1) перспективность рынка и трендов на нем, объем рынка, ключевые игроки (2) перспективность самой компании-таргета, наличие более перспективных таргетов (3) ключевые синергии между компанией и экосистемой Сбера, (4) возможные риски (рыночные, законодательные и прочие риски).

5. КРИТЕРИИ КАЧЕСТВА ОТВЕТА

Ответ будет признан качественным, если:
• Ответ соответствует задаче и формату ответа, учтены подходы к корпоративному развитию.
• Приведены ссылки на источники.
• Минимум воды в тексте, сухие короткие фразы.
• Прогнозы рынка приведены на горизонте после 2025 года и представлены в денежном выражении (млн руб.)
• Приведены объемы выручки (млн руб.) по ключевым рыночным игрокам.
• Приведена конкретная механика синергий и продуктовых интеграций, объем синергий оценен в млн руб.
• Синергии рассмотрены на стороне экосистемы Сбера и на стороне компании-таргета. Проверено наличие синергий между компанией-таргетом и всеми компаниями экосистемы Сбера.
• Антимонопольные риски, риски общественного резонанса и ESG-принципы не были приняты во внимание при выполнении задачи, не повлияли на итоговую рекомендацию по формату партнерства и не указаны в самом ответе.
• Приведены альтернативные таргеты, если изначальная компания-таргет не подходит Сберу.
Будь конкретным и структурированным в ответе.
"""

    async def parse_user_request(self, user_text: str) -> Dict[str, Any]:
        """Парсит запрос пользователя и определяет параметры анализа."""
        try:
            model_api = ModelAPI(Models.chatgpt.value())
            messages = [
                {"role": "system", "content": "Ты помощник для извлечения названий компаний из текста. Отвечай только валидным JSON без лишнего текста."},
                {"role": "user", "content": self.analysis_prompt.format(user_text=user_text)}
            ]
            
            response = await model_api.get_response(messages)
            logger.info(f"Raw response from GPT: '{response}'")
            
            # Очищаем ответ от лишних символов
            cleaned_response = response.strip()
            
            # Пытаемся найти JSON в ответе более надежным способом
            json_patterns = [
                r'\{[^{}]*"name"[^{}]*"[^"]*"[^{}]*\}',  # JSON с name в кавычках
                r'```json\s*(\{.*?\})\s*```',  # JSON в блоке кода
                r'```\s*(\{.*?\})\s*```',  # JSON в блоке без указания языка
                r'\{.*?"name".*?\}',  # JSON содержащий name
                r'\{.*\}',  # Любой JSON
            ]
            
            result = None
            for i, pattern in enumerate(json_patterns):
                matches = re.findall(pattern, cleaned_response, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    try:
                        json_text = match if isinstance(match, str) else match
                        # Дополнительная очистка
                        json_text = json_text.strip().replace('\n', ' ').replace('\r', '')
                        logger.info(f"Trying to parse pattern {i}: '{json_text}'")
                        result = json.loads(json_text)
                        logger.info(f"Successfully parsed JSON: {result}")
                        break
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON decode error for pattern {i}: {e}, text: '{json_text}'")
                        continue
                if result:
                    break
            
            if result and "name" in result:
                # Проверяем, что название компании не пустое
                if result["name"] and result["name"].strip() != "":
                    # Убеждаемся что все нужные поля присутствуют
                    final_result = {
                        "name": result.get("name", "неизвестная_компания"),
                        "market": result.get("market", 1),
                        "rivals": result.get("rivals", 1), 
                        "synergy": result.get("synergy", 1)
                    }
                    logger.info(f"Final parsed result: {final_result}")
                    return final_result
            
            # Если не удалось распарсить, логируем и используем fallback
            logger.warning(f"Could not parse JSON from response: '{response}'. Using manual extraction.")
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}, response was: '{response}'")
        except Exception as e:
            logger.error(f"Unexpected error parsing user request: {e}")
        
        # Fallback: простой результат без ручного извлечения
        fallback_result = {"name": "неизвестная_компания", "market": 1, "rivals": 1, "synergy": 1}
        logger.info(f"Using fallback result: {fallback_result}")
        return fallback_result
    

    async def run_analysis(self, analysis_params: Dict[str, Any], file_content: str = "") -> Dict[str, str]:
        results = {}
        system_prompts = SystemPrompts()
        model_api = ModelAPI(Models.chatgpt.value())
        
        company_name = analysis_params.get("name", "unknown_company")
        
        # Подготавливаем дополнительный контекст из файла
        additional_context = ""
        if file_content:
            additional_context = f"\n\nДополнительная информация из файла:\n{file_content}"
        
        # Запускаем анализы согласно параметрам
        if analysis_params.get("market", 0):
            try:
                # Получаем промпт как строку
                market_prompt_raw = system_prompts.get_prompt(SystemPrompt.INVESTMENT_MARKET)
                
                # Парсим классический промпт
                parsed_prompt = self._parse_classical_prompt(market_prompt_raw)
                
                # Подставляем название компании
                user_content = parsed_prompt["prompt"].replace("[название компании]", company_name)
                full_user_content = user_content + additional_context
                
                messages = [
                    {"role": "system", "content": parsed_prompt["role"]},
                    {"role": "user", "content": full_user_content}
                ]
                
                results["market"] = await model_api.get_response(messages)
                logger.info("Market analysis completed")
            except Exception as e:
                logger.error(f"Error in market analysis: {e}")
                results["market"] = f"Ошибка при анализе рынка: {str(e)}"
        
        if analysis_params.get("rivals", 0):
            try:
                # Получаем промпт как строку
                rivals_prompt_raw = system_prompts.get_prompt(SystemPrompt.INVESTMENT_RIVALS)
                
                # Парсим классический промпт
                parsed_prompt = self._parse_classical_prompt(rivals_prompt_raw)
                
                # Подставляем название компании
                user_content = parsed_prompt["prompt"].replace("[название компании]", company_name)
                full_user_content = user_content + additional_context
                
                messages = [
                    {"role": "system", "content": parsed_prompt["role"]},
                    {"role": "user", "content": full_user_content}
                ]
                
                results["rivals"] = await model_api.get_response(messages)
                logger.info("Rivals analysis completed")
            except Exception as e:
                logger.error(f"Error in rivals analysis: {e}")
                results["rivals"] = f"Ошибка при анализе конкурентов: {str(e)}"
        
        if analysis_params.get("synergy", 0):
            try:
                # Получаем промпт для анализа синергии
                synergy_prompt_raw = system_prompts.get_prompt(SystemPrompt.INVESTMENT_SYNERGY)
                
                # Проверяем формат промпта
                if isinstance(synergy_prompt_raw, dict):
                    system_content = synergy_prompt_raw.get("role", "")
                    user_content = synergy_prompt_raw.get("prompt", "")
                    user_content = user_content.replace("[название компании]", company_name)
                    full_user_content = user_content + additional_context
                    
                    messages = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": full_user_content}
                    ]
                elif isinstance(synergy_prompt_raw, str):
                    full_prompt = synergy_prompt_raw.replace("[название компании]", company_name)
                    full_prompt = full_prompt + additional_context
                    
                    messages = [
                        {"role": "user", "content": full_prompt}
                    ]
                else:
                    raise ValueError(f"Неподдерживаемый формат промпта: {type(synergy_prompt_raw)}")
                
                results["synergy"] = await model_api.get_response(messages)
                logger.info("Synergy analysis completed")
            except Exception as e:
                logger.error(f"Error in synergy analysis: {e}")
                results["synergy"] = f"Ошибка при анализе синергии: {str(e)}"
        
        return results
    
    def _parse_classical_prompt(self, prompt_text: str) -> Dict[str, str]:
        """
        Парсит классический промпт формата 'РОЛЬ. ... КОНТЕКСТ. ...' 
        и разделяет на роль и контекст.
        """
        try:
            # Ищем паттерны РОЛЬ и КОНТЕКСТ
            role_match = re.search(r'РОЛЬ\.\s*(.*?)(?=\n\s*КОНТЕКСТ\.|\n\s*[А-ЯЁ]+\.|\Z)', prompt_text, re.DOTALL | re.IGNORECASE)
            context_match = re.search(r'КОНТЕКСТ\.\s*(.*?)(?=\n\s*[А-ЯЁ]+\.|\Z)', prompt_text, re.DOTALL | re.IGNORECASE)
            
            role = role_match.group(1).strip() if role_match else ""
            context = context_match.group(1).strip() if context_match else ""
            
            # Если не нашли структурированные части, используем весь текст как контекст
            if not role and not context:
                context = prompt_text.strip()
                role = "Ты профессиональный аналитик."
            
            return {
                "role": role,
                "prompt": context
            }
        except Exception as e:
            logger.warning(f"Error parsing classical prompt: {e}")
            return {
                "role": "Ты профессиональный аналитик.",
                "prompt": prompt_text
            }

    def create_docx_report(self, company_name: str, analysis_results: Dict[str, str]) -> str:
        """Создает DOCX отчет с результатами анализа."""
        try:
            doc = Document()
            
            # Заголовок
            title = doc.add_heading(f'Анализ инвестиционной привлекательности: {company_name}', 0)
            
            # Добавляем результаты анализов
            if "market" in analysis_results:
                doc.add_heading('Рыночный анализ', level=1)
                doc.add_paragraph(analysis_results["market"])
                doc.add_page_break()
            
            if "rivals" in analysis_results:
                doc.add_heading('Анализ конкурентов', level=1)
                doc.add_paragraph(analysis_results["rivals"])
                doc.add_page_break()
            
            if "synergy" in analysis_results:
                doc.add_heading('Анализ синергии', level=1)
                doc.add_paragraph(analysis_results["synergy"])
            
            # Сохраняем во временный файл
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
            doc.save(temp_file.name)
            temp_file.close()
            
            logger.info(f"DOCX report created: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Error creating DOCX report: {e}")
            raise

    async def generate_executive_summary(self, docx_file_path: str) -> str:
        """Генерирует executive summary на основе DOCX файла."""
        try:
            # Читаем содержимое DOCX файла
            doc = Document(docx_file_path)
            doc_content = ""
            for paragraph in doc.paragraphs:
                doc_content += paragraph.text + "\n"
            
            model_api = ModelAPI(Models.chatgpt.value())
            messages = [
                {"role": "system", "content": self.executive_summary_prompt},
                {"role": "user", "content": f"Содержимое анализа:\n\n{doc_content}"}
            ]
            
            executive_summary = await model_api.get_response(messages)
            logger.info("Executive summary generated")
            return executive_summary
            
        except Exception as e:
            logger.error(f"Error generating executive summary: {e}")

    async def create_final_report_with_qa(self, company_name: str, analysis_results: Dict[str, str], qa_history: list) -> str:
        """Создает финальный отчет с интегрированными Q&A."""
        try:
        # Создаем новый документ
            doc = Document()
        
        # Заголовок
            title = doc.add_heading(f'Инвестиционный анализ: {company_name}', 0)
            title.alignment = 1  # Выравнивание по центру
        
        # Дата создания отчета
            from datetime import datetime
            date_paragraph = doc.add_paragraph(f'Дата создания отчета: {datetime.now().strftime("%d.%m.%Y")}')
            date_paragraph.alignment = 1  # Выравнивание по центру
        
            doc.add_page_break()
        
        # Добавляем результаты анализов с улучшенным форматированием
            if "market" in analysis_results:
                doc.add_heading('1. Рыночный анализ', level=1)
                self._add_formatted_content(doc, analysis_results["market"])
                doc.add_page_break()
        
            if "rivals" in analysis_results:
                doc.add_heading('2. Анализ конкурентов', level=1)
                self._add_formatted_content(doc, analysis_results["rivals"])
                doc.add_page_break()
        
            if "synergy" in analysis_results:
                doc.add_heading('3. Анализ синергии', level=1)
                self._add_formatted_content(doc, analysis_results["synergy"])
            
                if qa_history:  # Добавляем разрыв страницы только если есть Q&A
                    doc.add_page_break()
        
        # Добавляем Q&A секцию если есть вопросы
            if qa_history:
                doc.add_heading('4. Дополнительные вопросы и ответы', level=1)
            
                for i, qa in enumerate(qa_history, 1):
                # Добавляем вопрос
                    question_para = doc.add_paragraph()
                    question_run = question_para.add_run(f"Вопрос {i}: ")
                    question_run.bold = True
                    question_para.add_run(qa['question'])
                
                # Добавляем ответ
                    answer_para = doc.add_paragraph()
                    answer_run = answer_para.add_run("Ответ: ")
                    answer_run.bold = True
                
                # Добавляем сам текст ответа
                    self._add_formatted_content(doc, qa['answer'], is_sub_content=True)
                
                # Добавляем небольшой отступ между Q&A парами (если не последний)
                    if i < len(qa_history):
                        doc.add_paragraph()  # Один пустой параграф вместо нескольких
        
        # Сохраняем во временный файл
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='_final.docx')
            doc.save(temp_file.name)
            temp_file.close()
        
            logger.info(f"Final report with Q&A created: {temp_file.name}")
            return temp_file.name
        
        except Exception as e:
            logger.error(f"Error creating final report with Q&A: {e}")
        # В случае ошибки возвращаем базовый отчет
            return self.create_docx_report(company_name, analysis_results)


    def _add_formatted_content(self, doc, content: str, is_sub_content: bool = False):
        """Добавляет форматированный контент в документ."""
        if not content:
            return
    
    # Разбиваем контент на параграфы
        paragraphs = content.split('\n\n')
    
        for para_text in paragraphs:
            if not para_text.strip():
                continue
        
            lines = para_text.strip().split('\n')
        
            for line in lines:
                line = line.strip()
                if not line:
                    continue
            
            # Проверяем, является ли строка заголовком
                if line.startswith('##'):
                # Подзаголовок уровня 2
                    heading_text = line.replace('##', '').strip()
                    if heading_text:
                        doc.add_heading(heading_text, level=3)
                elif line.startswith('#'):
                # Подзаголовок уровня 1 
                    heading_text = line.replace('#', '').strip()
                    if heading_text:
                        doc.add_heading(heading_text, level=2 if is_sub_content else 2)
                elif line.startswith('**') and line.endswith('**'):
                # Жирный текст как отдельный параграф
                    para = doc.add_paragraph()
                    run = para.add_run(line.replace('**', ''))
                    run.bold = True
                elif line.startswith('- ') or line.startswith('* '):
                # Маркированный список
                    bullet_text = line[2:].strip()
                    if bullet_text:
                        para = doc.add_paragraph(bullet_text, style='List Bullet')
                elif line[0].isdigit() and '. ' in line:
                # Нумерованный список
                    numbered_text = line.split('. ', 1)[1] if '. ' in line else line
                    if numbered_text:
                        para = doc.add_paragraph(numbered_text, style='List Number')
                else:
                # Обычный параграф
                    para = doc.add_paragraph()
                
                # Обрабатываем жирный текст внутри параграфа
                    parts = line.split('**')
                    for i, part in enumerate(parts):
                        if part:
                            run = para.add_run(part)
                            if i % 2 == 1:  # Нечетные части - жирные
                                run.bold = True

    def _sanitize_filename(self, filename: str) -> str:
        """Очищает имя файла от недопустимых символов."""
        if not filename or not filename.strip():
            return 'unknown_company'
    
    # Убираем недопустимые символы для имени файла
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(filename))
    # Убираем пробелы в начале и конце
        sanitized = sanitized.strip()
    # Заменяем пробелы на подчеркивания
        sanitized = sanitized.replace(' ', '_')
    # Ограничиваем длину
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
    # Убираем точки в конце (проблемы в Windows)
        sanitized = sanitized.rstrip('.')
    
    # Проверяем, что результат не пустой
        if not sanitized:
            return 'unknown_company'
        
        return sanitized

class BaseScenario(ABC):
    """Базовый класс для сценариев с общей логикой работы с запросами, файлами и ошибками."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @abstractmethod
    async def process(self, *args, **kwargs) -> Any:  # Изменили сигнатуру на более гибкую
        pass

    @abstractmethod
    def register(self, dp: Dispatcher) -> None:
        pass

    async def process_investment_analysis(self, message, state, file_content=''):
        """Обработка запроса для анализа инвестиционной привлекательности."""
        user_id = message.chat.id
        user_data = await state.get_data()
        user_query = user_data.get('user_query', '')

        await self.delete_message_by_id(user_id, user_data.get('processing_msg_id'))

        if not user_query and not file_content:
            await message.answer(
                'Необходимо ввести запрос или прикрепить файл. Пожалуйста, начните заново с команды /start',
            )
            return

        try:
            # Показываем прогресс
            progress_msg = await message.answer('🔍 Анализирую запрос и определяю параметры анализа...')
            
            # Инициализируем процессор анализа
            processor = InvestmentAnalysisProcessor()
            
            # Парсим запрос пользователя
            analysis_params = await processor.parse_user_request(user_query)
            company_name = analysis_params.get("name", "unknown_company")
            
            await progress_msg.edit_text(f'📊 Запускаю анализ для компании: {company_name}...')
            
            # Запускаем анализ
            analysis_results = await processor.run_analysis(analysis_params, file_content)
            
            await progress_msg.edit_text('📄 Создаю отчет...')
            
            # Создаем DOCX отчет
            docx_file_path = processor.create_docx_report(company_name, analysis_results)
            
            await progress_msg.edit_text('📝 Генерирую executive summary...')
            
            # Генерируем executive summary
            executive_summary = await processor.generate_executive_summary(docx_file_path)
            
            # Сохраняем данные для дальнейшего использования
            await state.update_data(
                analysis_params=analysis_params,
                analysis_results=analysis_results,
                docx_file_path=docx_file_path,
                executive_summary=executive_summary,
                company_name=company_name,
                qa_history=[]  # Для хранения вопросов и ответов
            )
            
            # Отправляем executive summary
            await self.send_markdown_response(message, executive_summary)
            
            await progress_msg.delete()
            
            # Показываем кнопки действий
            keyboard = InvestmentActionsKeyboard()
            logger.info(f"Created keyboard: {keyboard}")
            actions_message = await message.answer(
                'Что бы вы хотели сделать дальше?', 
                reply_markup=keyboard
            )
            await UserStates.INVESTMENT_ACTIONS.set()
            logger.info(f"User {user_id} moved to INVESTMENT_ACTIONS state")
            logger.info(f"Actions message sent with ID: {actions_message.message_id}")
            
        except Exception as e:
            await self.handle_error(message, e, "investment_analysis")

    async def process_startups_scouting(self, message, state, file_content=''):
        """Обработка запроса для скаутинга стартапов (исправленная версия без file_search)."""
        user_id = message.chat.id
        user_data = await state.get_data()
        user_query = user_data.get('user_query', '')

        await self.delete_message_by_id(user_id, user_data.get('processing_msg_id'))

        if not user_query and not file_content:
            await message.answer('Необходимо ввести запрос или прикрепить файл. Пожалуйста, начните заново с команды /start',
            )
            return

        if file_content:
            summary = await self.summarize_file_content(file_content)
            if not summary:
                await message.answer('Произошла ошибка при суммаризации файла. Попробуйте еще раз или обратитесь к администратору.'
                )
                return
            file_context = f'\n\nКонтекст из файла (суммаризация):\n{summary}'
        else:
            file_context = ''

        chat_context = ChatContextManager()
        strategy = Models.chatgpt.value()
        model_api = ModelAPI(strategy)
    
        try:
        # Используем ExcelSearchStrategy но без file_search
            excel_search = ExcelSearchStrategy()
            excel_data = await excel_search.get_response([{'role': 'user', 'content': user_query}])
        
        # Если получили данные из Excel, добавляем к запросу
            if excel_data and "Ошибка" not in excel_data:
                full_query = f'{user_query}\n\nРелевантные данные из базы стартапов:\n{excel_data}{file_context}'
            else:
            # Если ошибка с Excel, работаем без данных
                full_query = f'{user_query}{file_context}'
                logger.warning(f"Excel search failed, continuing without data: {excel_data}")
        
            topic_name = user_data.get('chosen_topic')
            chat_context.add_message(user_id, topic_name, 'user', full_query)

            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            messages = chat_context.get_limited_messages_for_api(user_id, topic_name, limit=0)
            response = await model_api.get_response(messages)

            system_prompts = SystemPrompts()
            detail_prompt_type = f'{topic_name.upper()}_DETAIL'
            detail_prompt = system_prompts.get_prompt(SystemPrompt[detail_prompt_type])
            detail_messages = [
                {'role': 'system', 'content': detail_prompt},
                {'role': 'user', 'content': full_query},
            ]
            detail_response = await model_api.get_response(detail_messages)
            chat_context.add_message(user_id, topic_name, 'assistant', response)
        
            await self.send_markdown_response(message, response)
            await self.send_html_detail_response(message, detail_response)

            await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
            await UserStates.ASKING_CONTINUE.set()
        except Exception as e:
            await self.handle_error(message, e, "startups_scouting")
        
    async def process_query_with_file(self, message, state, file_content='', skip_system_prompt=False, max_history=0):
        """Универсальная обработка запроса пользователя с учетом выбранной темы."""
        user_data = await state.get_data()
        topic_name = user_data.get('chosen_topic')
        
        # Определяем тип обработки на основе темы
        if topic_name == Topics.investment.name:
            await self.process_investment_analysis(message, state, file_content)
        elif topic_name == Topics.startups.name:
            await self.process_startups_scouting(message, state, file_content)
        else:
            # Для других тем используем старую логику
            await self.process_legacy_query(message, state, file_content, skip_system_prompt, max_history)

    async def process_legacy_query(self, message, state, file_content='', skip_system_prompt=False, max_history=0):
        """Старая логика обработки запросов для совместимости."""
        user_id = message.chat.id
        user_data = await state.get_data()
        topic_name = user_data.get('chosen_topic')
        model_name = user_data.get('chosen_model', 'chatgpt')
        user_query = user_data.get('user_query', '')

        await self.delete_message_by_id(user_id, user_data.get('processing_msg_id'))

        if not user_query and not file_content:
            await message.answer(
                'Необходимо ввести запрос или прикрепить файл. Пожалуйста, начните заново с команды /start',
            )
            return

        if file_content:
            summary = await self.summarize_file_content(file_content)
            if not summary:
                await message.answer(
                    'Произошла ошибка при суммаризации файла. Попробуйте еще раз или обратитесь к администратору.'
                )
                return
            file_context = f'\n\nКонтекст из файла (суммаризация):\n{summary}'
        else:
            file_context = ''

        chat_context = ChatContextManager()
        strategy = Models[model_name].value()
        model_api = ModelAPI(strategy)
        
        try:
            full_query = f'{user_query}{file_context}'
            chat_context.add_message(user_id, topic_name, 'user', full_query)

            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            messages = chat_context.get_limited_messages_for_api(
                user_id,
                topic_name,
                limit=max_history,
                skip_system_prompt=skip_system_prompt,
            )
            response = await model_api.get_response(messages)

            system_prompts = SystemPrompts()
            detail_prompt_type = f'{topic_name.upper()}_DETAIL'
            detail_prompt = system_prompts.get_prompt(SystemPrompt[detail_prompt_type])
            
            if skip_system_prompt:
                user_assistant_history = [msg for msg in messages if msg['role'] != 'system'][-5:]
                detail_messages = [{'role': 'system', 'content': detail_prompt}] + user_assistant_history
            else:
                detail_messages = [
                    {'role': 'system', 'content': detail_prompt},
                    {'role': 'user', 'content': full_query},
                ]
            detail_response = await model_api.get_response(detail_messages)
            chat_context.add_message(user_id, topic_name, 'assistant', response)
            await self.send_markdown_response(message, response)
            await self.send_html_detail_response(message, detail_response)

            await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
            await UserStates.ASKING_CONTINUE.set()
        except Exception as e:
            await self.handle_error(message, e, model_name)

    async def send_markdown_response(self, message, response):
        escaped_response = self._escape_markdown(response)
        max_length = 4000
        for i in range(0, len(escaped_response), max_length):
            part = escaped_response[i : i + max_length]
            await message.answer(part, parse_mode='MarkdownV2')

    async def send_html_detail_response(self, message, detail_response):
        max_chunk_size = 3000
        detail_chunks = [
            detail_response[i : i + max_chunk_size] for i in range(0, len(detail_response), max_chunk_size)
        ]
        for i, chunk in enumerate(detail_chunks):
            chunk_without_links = self._remove_links(chunk)
            if i == 0:
                await message.answer(
                    f'<blockquote expandable>{html.escape(chunk_without_links)}</blockquote>',
                    parse_mode='HTML',
                )
            else:
                await message.answer(
                    f'<blockquote expandable>Продолжение детализированного ответа ({i + 1}/{len(detail_chunks)}):\n\n{html.escape(chunk_without_links)}</blockquote>',
                    parse_mode='HTML',
                )

    async def delete_message_by_id(self, user_id, message_id):
        if message_id:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=message_id)
            except Exception:
                pass

    async def handle_error(self, message, e, model_name):
        logger.error(f'Ошибка {model_name}: {e}', exc_info=True)

        token_limit = self._parse_token_limit_error(str(e))
        if token_limit:
            await message.answer(
                f'⚠️ Вы превысили лимит токенов для модели.\nМаксимум: {token_limit} токенов.\nПожалуйста, уменьшите запрос и попробуйте снова.'
            )
        else:
            await message.answer(
                'Извините, мой маленький компьютер перегружен. Поступает слишком много запросов. Пожалуйста, подождите несколько секунд или попробуйте ещё раз.\n'
                'Если проблема не исчезнет, обратитесь к администратору.'
            )

        await self.bot.send_message(
            chat_id=config.OWNER_ID,
            text=f'Ошибка при запросе к {model_name} от пользователя {message.chat.id}:\n{e}'
        )

    def _remove_links(self, text: str) -> str:
        try:
            return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        except Exception:
            return text

    def _escape_markdown(self, text: str) -> str:
        try:
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            result = ''
            i = 0
            while i < len(text):
                if i + 1 < len(text) and text[i : i + 2] == '**':
                    end_pos = text.find('**', i + 2)
                    if end_pos != -1:
                        bold_content = text[i + 2 : end_pos]
                        escaped_content = ''
                        for char in bold_content:
                            if char in '_[]()~`>#+-=|{}.!':
                                escaped_content += f'\\{char}'
                            elif char == '*':
                                escaped_content += '\\*'
                            else:
                                escaped_content += char
                        result += f'*{escaped_content}*'
                        i = end_pos + 2
                        continue
                if text[i] in '_*[]()~`>#+-=|{}.!':
                    result += f'\\{text[i]}'
                else:
                    result += text[i]
                i += 1
            return result
        except Exception:
            return text

    def _parse_token_limit_error(self, error_text: str) -> int:
        match = re.search(r'Limit (\d+), Requested (\d+)', error_text)
        if match:
            return int(match.group(1))
        return None

    async def summarize_file_content(self, file_content: str) -> str:
        summary_prompt = SystemPrompts().get_prompt(SystemPrompt.FILE_SUMMARY)
        messages = [{'role': 'system', 'content': summary_prompt}, {'role': 'user', 'content': file_content}]
        model_api = ModelAPI(Models.chatgpt_file.value())
        try:
            summary = await model_api.get_response(messages)
            logger.info(f'Суммаризация файла завершена, длина summary: {len(summary)} символов')
            return summary
        except Exception as e:
            logger.error(f'Ошибка при суммаризации файла: {e}', exc_info=True)
            return None


class InvestmentActionsHandler(BaseScenario):
    """Обработка действий после получения executive summary."""

    async def process(self, *args, **kwargs) -> None:  # Обновленная сигнатура
        # Извлекаем callback_query и state из args или kwargs
        if args:
            callback_query = args[0]
            state = args[1] if len(args) > 1 else kwargs.get('state')
        else:
            callback_query = kwargs.get('callback_query')
            state = kwargs.get('state')
            
        if not callback_query or not state:
            logger.error("InvestmentActionsHandler: missing callback_query or state parameter")
            return

        user_id = callback_query.from_user.id
        action = callback_query.data
        user_data = await state.get_data()
        
        logger.info(f"Investment actions handler: user {user_id}, action {action}")

        await callback_query.answer()

        if action == 'investment_regenerate':
            # Регенерация анализа
            await callback_query.message.delete()
            progress_msg = await callback_query.message.answer('🔄 Запускаю повторную генерацию анализа...')
            
            try:
                # Повторно запускаем анализ
                processor = InvestmentAnalysisProcessor()
                analysis_params = user_data.get('analysis_params')
                company_name = user_data.get('company_name')
                
                analysis_results = await processor.run_analysis(analysis_params)
                docx_file_path = processor.create_docx_report(company_name, analysis_results)
                executive_summary = await processor.generate_executive_summary(docx_file_path)
                
                # Обновляем данные
                await state.update_data(
                    analysis_results=analysis_results,
                    docx_file_path=docx_file_path,
                    executive_summary=executive_summary,
                    qa_history=[]  # Сбрасываем историю Q&A
                )
                
                await progress_msg.delete()
                await self.send_markdown_response(callback_query.message, executive_summary)
                await callback_query.message.answer(
                    'Что бы вы хотели сделать дальше?', 
                    reply_markup=InvestmentActionsKeyboard()
                )
                
            except Exception as e:
                await progress_msg.delete()
                await self.handle_error(callback_query.message, e, "regeneration")
            
        elif action == 'investment_ask_question':
            # Переход к режиму вопросов-ответов
            await callback_query.message.delete()
            await callback_query.message.answer(
                '❓ Задайте ваш вопрос по анализу компании. Все вопросы и ответы будут добавлены в итоговый отчет.'
            )
            await UserStates.INVESTMENT_QA.set()
            
        elif action == 'investment_get_report':
            # Выбор способа получения отчета
            await callback_query.message.edit_text(
                'Выберите способ получения отчета:',
                reply_markup=InvestmentReportKeyboard()
            )
            await UserStates.INVESTMENT_REPORT_OPTIONS.set()

    def register(self, dp: Dispatcher) -> None:
        logger.info("=== REGISTERING InvestmentActionsHandler ===")
        
        # Регистрируем обработчик для всех инвестиционных действий
        dp.register_callback_query_handler(
            lambda c, state: self.process(c, state),  # Оборачиваем в lambda
            lambda c: c.data in ['investment_regenerate', 'investment_ask_question', 'investment_get_report'],
            state=UserStates.INVESTMENT_ACTIONS,
        )
        
        logger.info("=== InvestmentActionsHandler REGISTERED SUCCESSFULLY ===")

class InvestmentQAHandler(BaseScenario):
    """Обработка вопросов-ответов в режиме инвестиционного анализа."""

    async def process(self, *args, **kwargs) -> None:  # Обновленная сигнатура
        # Извлекаем message и state из args или kwargs
        if args:
            message = args[0]
            state = args[1] if len(args) > 1 else kwargs.get('state')
        else:
            message = kwargs.get('message')
            state = kwargs.get('state')
            
        if not message or not state:
            logger.error("InvestmentQAHandler: missing message or state parameter")
            return

        user_id = message.from_user.id
        user_data = await state.get_data()
        user_question = message.text
        
        company_name = user_data.get('company_name', 'неизвестная_компания')
        qa_history = user_data.get('qa_history', [])

        try:
            # Простой промпт только с названием компании и текущим вопросом
            model_api = ModelAPI(Models.chatgpt.value())
            messages = [
                {"role": "system", "content": f"Ты эксперт по инвестиционному анализу. Ответь на вопрос по компании {company_name}. Будь конкретным и профессиональным."},
                {"role": "user", "content": user_question}
            ]
            
            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            response = await model_api.get_response(messages)
            
            # Сохраняем Q&A в историю для итогового отчета
            qa_history.append({
                "question": user_question,
                "answer": response
            })
            
            await state.update_data(qa_history=qa_history)
            
            await self.send_markdown_response(message, response)
            
            # Кнопка для возврата к действиям
            await message.answer(
                'Хотите задать еще вопрос или вернуться к выбору действий?',
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton('← Вернуться к действиям', callback_data='back_to_investment_actions')
                )
            )
            
        except Exception as e:
            await self.handle_error(message, e, "investment_qa")

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            lambda message, state: self.process(message, state),  # Оборачиваем в lambda
            content_types=['text'],
            state=UserStates.INVESTMENT_QA,
        )


class BackToInvestmentActionsHandler(BaseScenario):
    """Возврат к выбору действий инвестиционного анализа."""

    async def process(self, *args, **kwargs) -> None:  # Обновленная сигнатура
        # Извлекаем callback_query и state из args или kwargs
        if args:
            callback_query = args[0]
            state = args[1] if len(args) > 1 else kwargs.get('state')
        else:
            callback_query = kwargs.get('callback_query')
            state = kwargs.get('state')
            
        if not callback_query or not state:
            logger.error("BackToInvestmentActionsHandler: missing callback_query or state parameter")
            return

        logger.info(f"BackToInvestmentActionsHandler called by user {callback_query.from_user.id}")
        await callback_query.answer()
        await callback_query.message.edit_text(
            'Что бы вы хотели сделать дальше?',
            reply_markup=InvestmentActionsKeyboard()
        )
        await UserStates.INVESTMENT_ACTIONS.set()

    def register(self, dp: Dispatcher) -> None:
        logger.info("=== REGISTERING BackToInvestmentActionsHandler ===")
        dp.register_callback_query_handler(
            lambda c, state: self.process(c, state),  # Оборачиваем в lambda
            lambda c: c.data == 'back_to_investment_actions',
            state='*',  # Разрешаем из любого состояния
        )
        logger.info("=== BackToInvestmentActionsHandler REGISTERED ===")



class InvestmentReportHandler(BaseScenario):
    """Обработка получения отчета."""

    def __init__(self, bot):
        super().__init__(bot)
        self.email_sender = EmailSender()

    async def process(self, *args, **kwargs) -> None:
        if args:
            callback_query = args[0]
            state = args[1] if len(args) > 1 else kwargs.get('state')
        else:
            callback_query = kwargs.get('callback_query')
            state = kwargs.get('state')
            
        if not callback_query or not state:
            logger.error("InvestmentReportHandler: missing callback_query or state parameter")
            return

        user_id = callback_query.from_user.id
        action = callback_query.data
        user_data = await state.get_data()

        logger.info(f"InvestmentReportHandler: user {user_id}, action {action}")
        await callback_query.answer()

        if action == 'investment_download':
            await self._download_report(callback_query, state, user_data)
        elif action == 'investment_email':
            if not self.email_sender.email_user or not self.email_sender.email_password:
                await callback_query.message.edit_text(
                    '❌ Отправка на email временно недоступна. Воспользуйтесь скачиванием отчета.',
                    reply_markup=InvestmentReportKeyboard()
                )
                return
                
            await callback_query.message.edit_text('Введите ваш email для отправки отчета:')
            await UserStates.ENTERING_EMAIL.set()
        elif action == 'investment_back_to_actions':
            await callback_query.message.edit_text(
                'Что бы вы хотели сделать дальше?',
                reply_markup=InvestmentActionsKeyboard()
            )
            await UserStates.INVESTMENT_ACTIONS.set()

    async def _download_report(self, callback_query, state, user_data):
        """Генерирует и отправляет отчет для скачивания."""
        try:
            await callback_query.message.edit_text('Генерирую финальный отчет...')
            
            processor = InvestmentAnalysisProcessor()
            company_name = user_data.get('company_name', 'unknown_company')
            analysis_results = user_data.get('analysis_results')
            qa_history = user_data.get('qa_history', [])
            
            final_report_path = await processor.create_final_report_with_qa(
                company_name, analysis_results, qa_history
            )
            
            safe_company_name = processor._sanitize_filename(company_name)
            if not safe_company_name:
                safe_company_name = "unknown_company"
            report_filename = f'investment_analysis_{safe_company_name}_final.docx'
            
            with open(final_report_path, 'rb') as doc_file:
                await callback_query.message.answer_document(
                    document=types.InputFile(doc_file, filename=report_filename),
                    caption=f'Финальный отчет c инвестиционным анализом: {company_name}'
                )
            
            os.unlink(final_report_path)
            
            # ГЛАВНОЕ ИЗМЕНЕНИЕ: Показываем финальные кнопки вместо возврата к действиям
            await callback_query.message.answer(
                'Отчет готов! Что бы вы хотели сделать дальше?',
                reply_markup=FinalActionsKeyboard()
            )
            await UserStates.CHOOSING_FINAL_ACTION.set()
            
        except Exception as e:
            await self.handle_error(callback_query.message, e, "report_generation")

    def register(self, dp: Dispatcher) -> None:
        logger.info("=== REGISTERING InvestmentReportHandler ===")
        dp.register_callback_query_handler(
            lambda c, state: self.process(c, state),
            lambda c: c.data in ['investment_download', 'investment_email', 'investment_back_to_actions'],
            state=UserStates.INVESTMENT_REPORT_OPTIONS,
        )
        logger.info("=== InvestmentReportHandler REGISTERED ===")

class EmailInputHandler(BaseScenario):
    """Обработка ввода email для отправки отчета."""

    def __init__(self, bot):
        super().__init__(bot)
        self.email_sender = EmailSender()

    async def process(self, *args, **kwargs) -> None:
        if args:
            message = args[0]
            state = args[1] if len(args) > 1 else kwargs.get('state')
        else:
            message = kwargs.get('message')
            state = kwargs.get('state')
            
        if not message or not state:
            logger.error("EmailInputHandler: missing message or state parameter")
            return
            
        email = message.text.strip()
        user_data = await state.get_data()
        
        if '@' not in email or '.' not in email:
            await message.answer('❌ Некорректный email. Введите правильный email:')
            return
        
        try:
            await message.answer('Генерирую и отправляю отчет на почту...')
            
            processor = InvestmentAnalysisProcessor()
            company_name = user_data.get('company_name', 'unknown_company')
            analysis_results = user_data.get('analysis_results')
            qa_history = user_data.get('qa_history', [])
            
            final_report_path = await processor.create_final_report_with_qa(
                company_name, analysis_results, qa_history
            )
            
            safe_company_name = processor._sanitize_filename(company_name)
            if not safe_company_name:
                safe_company_name = "unknown_company"
            report_filename = f'investment_analysis_{safe_company_name}_final.docx'
            
            if not hasattr(self.email_sender, 'send_report'):
                logger.error("EmailSender doesn't have send_report method!")
                await message.answer('❌ Ошибка конфигурации email. Обратитесь к администратору.')
                return
            
            success = await self.email_sender.send_report(
                email, 
                company_name, 
                final_report_path,
                filename=report_filename
            )
            
            if os.path.exists(final_report_path):
                os.unlink(final_report_path)
            
            if success:
                await message.answer(f'✅ Отчет успешно отправлен на {email}')
            else:
                await message.answer(f'❌ Не удалось отправить отчет на {email}. Попробуйте скачать отчет.')
            
            # ИЗМЕНЕНИЕ: После email тоже показываем финальные кнопки
            await message.answer(
                'Что бы вы хотели сделать дальше?',
                reply_markup=FinalActionsKeyboard()
            )
            await UserStates.CHOOSING_FINAL_ACTION.set()
            
        except Exception as e:
            await self.handle_error(message, e, "email_sending")

    def register(self, dp: Dispatcher) -> None:
        logger.info("=== REGISTERING EmailInputHandler ===")
        dp.register_message_handler(
            lambda message, state: self.process(message, state),
            content_types=['text'],
            state=UserStates.ENTERING_EMAIL,
        )
        logger.info("=== EmailInputHandler REGISTERED ===")

class FinalActionsHandler(BaseScenario):
    """Обработка финальных действий после получения отчета."""

    async def process(self, *args, **kwargs) -> None:
        if args:
            callback_query = args[0]
            state = args[1] if len(args) > 1 else kwargs.get('state')
        else:
            callback_query = kwargs.get('callback_query')
            state = kwargs.get('state')
            
        if not callback_query or not state:
            logger.error("FinalActionsHandler: missing callback_query or state parameter")
            return

        user_id = callback_query.from_user.id
        action = callback_query.data

        logger.info(f"FinalActionsHandler: user {user_id}, action {action}")
        await callback_query.answer()

        if action == 'new_company_analysis':
            # Новый анализ - очищаем все и начинаем заново
            await callback_query.message.delete()
            await state.finish()
            
            chat_context = ChatContextManager()
            chat_context.end_active_chats(user_id)
            chat_context.cleanup_user_context(user_id)
            
            # Автоматически устанавливаем тему investment снова
            system_prompts = SystemPrompts()
            system_prompt = system_prompts.get_prompt(SystemPrompt.INVESTMENT)
            chat_context.start_new_chat(user_id, 'investment', system_prompt)
            
            await callback_query.message.answer(
                'Введите название новой компании или опишите ваш запрос для анализа инвестиционной привлекательности.'
            )
            await UserStates.ENTERING_PROMPT.set()
            
        elif action == 'return_to_main_bot':
            # Переход к основному боту через URL
            await callback_query.message.delete()
            await state.finish()
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    text="Перейти к основному боту",
                    url="https://t.me/sberallaibot"
                )
            )
            
            await callback_query.message.answer(
                'Спасибо за использование бота для анализа инвестиционной привлекательности!\n\n'
                'Нажмите кнопку ниже, чтобы перейти к основному боту Сбер CPNB:',
                reply_markup=keyboard
            )

    def register(self, dp: Dispatcher) -> None:
        logger.info("=== REGISTERING FinalActionsHandler ===")
        dp.register_callback_query_handler(
            lambda c, state: self.process(c, state),
            lambda c: c.data in ['new_company_analysis', 'return_to_main_bot'],
            state=UserStates.CHOOSING_FINAL_ACTION,
        )
        logger.info("=== FinalActionsHandler REGISTERED ===")

class Access(BaseScenario):
    """Обработка получения доступа к боту."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> NotImplemented:
        raise NotImplementedError()

    async def authorize_process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        admin_id = callback

class Access(BaseScenario):
    """Обработка получения доступа к боту."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> NotImplemented:
        raise NotImplementedError()

    async def authorize_process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        admin_id = callback

class Access(BaseScenario):
    """Обработка получения доступа к боту."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> NotImplemented:
        raise NotImplementedError()

    async def authorize_process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        admin_id = callback_query.from_user.id
        logger.info(f'Администратор {admin_id} авторизует пользователя')

        callback_message = callback_query.message.text
        try:
            authorized_user_id = int(callback_message.split('id: ')[1].split(')')[0])

            if config._users is None:
                _ = config.USERS

            config._users.append(authorized_user_id)

            msg = 'Доступ получен. Отправьте /start для начала работы с ботом.'
            await self.bot.send_message(chat_id=authorized_user_id, text=msg)

            admin_msg = f'Пользователь {authorized_user_id} успешно авторизован.'
            await callback_query.message.edit_text(admin_msg)

            logger.info(f'Авторизация пользователя {authorized_user_id} завершена успешно')
        except Exception as e:
            error_msg = f'Ошибка при авторизации пользователя: {str(e)}'
            logger.error(error_msg, exc_info=True)
            await callback_query.message.reply(error_msg)

    async def decline_process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        admin_id = callback_query.from_user.id
        logger.info(f'Администратор {admin_id} отклоняет авторизацию пользователя')

        callback_message = callback_query.message.text
        try:
            declined_user_id = int(callback_message.split('id: ')[1].split(')')[0])
            logger.info(f'Извлечен ID пользователя для отклонения: {declined_user_id}')

            config._blocked_users.add(declined_user_id)
            logger.info(f'Пользователь {declined_user_id} добавлен в список заблокированных')

            msg = 'Доступ запрещен администратором.'
            await self.bot.send_message(chat_id=declined_user_id, text=msg)

            admin_msg = f'Пользователь {declined_user_id} отклонен и заблокирован.'
            await callback_query.message.edit_text(admin_msg)

            logger.info(f'Отклонение пользователя {declined_user_id} завершено')
        except Exception as e:
            error_msg = f'Ошибка при отклонении пользователя: {str(e)}'
            logger.error(error_msg, exc_info=True)
            await callback_query.message.reply(error_msg)
            self.bot.send_message(chat_id=config.OWNER_ID, text=error_msg)

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.authorize_process,
            lambda c: c.data == 'authorize_yes',
            state='*',
        )
        dp.register_callback_query_handler(
            self.decline_process,
            lambda c: c.data == 'authorize_no',
            state='*',
        )


class StartHandler(BaseScenario):
    """Обработка /start команды."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id
        user_name = f'{message.from_user.first_name} {message.from_user.last_name}'
        logger.info(f'Команда /start от пользователя {user_id} ({user_name})')

        chat_context = ChatContextManager()
        logger.info(f'Завершаем все активные чаты пользователя {user_id} при /start')
        chat_context.end_active_chats(user_id)
        logger.info(f'Очищаем неактивные чаты пользователя {user_id} при /start')
        chat_context.cleanup_user_context(user_id)

        if user_id not in config.AUTHORIZED_USERS_IDS:
            logger.info(f'Запрос авторизации для {user_id} к администраторам {config.ADMIN_USERS}')
            await message.answer('Запрашиваю доступ у администратора.')
            user_first_name = message.from_user.first_name
            user_last_name = message.from_user.last_name
            msg = f'Пользователь {user_first_name} {user_last_name} (id: {user_id}) запрашивает доступ.'
            for admin_user in config.ADMIN_USERS:
                await self.bot.send_message(
                    chat_id=admin_user,
                    text=msg,
                    reply_markup=AuthorizeKeyboard(),
                )
            await UserStates.ACCESS.set()
        else:
            # ИЗМЕНЕНИЕ: Сразу переходим к инвестиционному анализу без выбора темы
            await message.answer('Здравствуйте! Добро пожаловать в бот для анализа инвестиционной привлекательности.\n\nВведите название компании или опишите ваш запрос для анализа.')
            
            # Автоматически устанавливаем тему как investment
            system_prompts = SystemPrompts()
            system_prompt = system_prompts.get_prompt(SystemPrompt.INVESTMENT)
            
            chat_context.start_new_chat(user_id, 'investment', system_prompt)
            
            # Устанавливаем состояние прямо в ввод промпта для инвестиционного анализа
            await UserStates.ENTERING_PROMPT.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['start'], state='*')


class ProcessingChooseTopicCallback(BaseScenario):
    """Обработка выбора темы."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        topic_callback = callback_query.data
        topic_name = topic_callback.replace('topic_', '')

        await callback_query.answer()

        logger.info(f'Пользователь {user_id} выбрал тему: {topic_name}')

        system_prompts = SystemPrompts()
        system_prompt = system_prompts.get_prompt(SystemPrompt[topic_name.upper()])

        chat_context = ChatContextManager()
        chat_context.start_new_chat(user_id, topic_name, system_prompt)

        await state.update_data(chosen_topic=topic_name)
        await state.update_data(chosen_model='chatgpt')

        await callback_query.message.delete()

        examples = {
            'investment': 'Покупка/Партнёрство с \*имя компании\*',
            'startups': 'Поиск стартапов в сфере \*название сферы\*',
        }
        example = examples[topic_name]
        prompt_example = f'Какой Ваш запрос?\n_Пример: {example}_'
        prompt_message = await callback_query.message.answer(prompt_example, parse_mode='MarkdownV2')

        await state.update_data(prompt_message_id=prompt_message.message_id)
        await UserStates.ENTERING_PROMPT.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('topic_'),
            state=UserStates.CHOOSING_TOPIC,
        )


class ProcessingEnterPromptHandler(BaseScenario):
    """Обработка ввода текстового промпта пользователем."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        
        # ИЗМЕНЕНИЕ: Автоматически устанавливаем investment тему
        topic_name = 'investment'
        model_name = 'chatgpt'
        
        # Обновляем состояние с установленными значениями
        await state.update_data(chosen_topic=topic_name, chosen_model=model_name)

        logger.info(f'Получен текстовый запрос от {user_id}: модель={model_name}, тема={topic_name}')

        await state.update_data(user_query=message.text)

        file_message = await message.answer(
            'Хотите ли вы прикрепить файл (PDF, Word, PPT) для анализа?',
            reply_markup=FileAttachKeyboard(),
        )

        await state.update_data(file_message_id=file_message.message_id)
        await UserStates.ATTACHING_FILE.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=UserStates.ENTERING_PROMPT,
        )

class FinalActionsKeyboard(Keyboard):
    """Клавиатура после получения отчета."""
    _buttons = (
        Button('🏢 Новая компания', 'new_company_analysis'),
        Button('← Вернуться к основному боту', 'return_to_main_bot'),
    )

class AttachFileHandler(BaseScenario):
    """Универсальный обработчик прикрепления файла (первый запрос и продолжение диалога)."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        user_data = await state.get_data()
        await callback_query.answer()
        await self.delete_message_by_id(user_id, user_data.get('file_message_id'))
        if callback_query.data == 'attach_file':
            file_prompt = await callback_query.message.answer('Пожалуйста, загрузите файл (PDF, Word, PPT):')
            await state.update_data(file_prompt_id=file_prompt.message_id)
            await UserStates.UPLOADING_FILE.set()
        else:
            # Без файла, универсальная обработка
            skip_system_prompt = user_data.get('skip_system_prompt', False)
            max_history = 10 if skip_system_prompt else 0
            await self.process_query_with_file(
                callback_query.message,
                state,
                file_content='',
                skip_system_prompt=skip_system_prompt,
                max_history=max_history,
            )

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data in ['attach_file', 'no_file'],
            state=[UserStates.ATTACHING_FILE, UserStates.ATTACHING_FILE_CONTINUE],
        )


class UploadFileHandler(BaseScenario):
    """Универсальный обработчик загрузки файла (первый запрос и продолжение диалога)."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        await self.delete_message_by_id(user_id, user_data.get('file_prompt_id'))
        if not message.document:
            await message.answer('Пожалуйста, загрузите файл в формате PDF, Word или PowerPoint.')
            return
        file_name = message.document.file_name
        file_size = message.document.file_size
        logger.info(f'Обработка файла: {file_name} ({file_size} байт)')
        try:
            processing_msg = await message.answer('Идет обработка файла...')
            file_content = await FileProcessor.extract_text_from_file(message.document, self.bot)
            logger.info(f'Извлечено {len(file_content)} символов из файла {file_name}')
            await state.update_data(processing_msg_id=processing_msg.message_id)
            skip_system_prompt = user_data.get('skip_system_prompt', False)
            max_history = 10 if skip_system_prompt else 0
            await self.process_query_with_file(
                message,
                state,
                file_content,
                skip_system_prompt=skip_system_prompt,
                max_history=max_history,
            )
        except ValueError as e:
            logger.error(f'Ошибка обработки файла {file_name}: {e}')
            await message.answer(
                'Произошла ошибка при обработке файла. Сообщение об ошибке уже отправлено разработчику. Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'{e}',
            )

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=[UserStates.UPLOADING_FILE, UserStates.UPLOADING_FILE_CONTINUE],
        )


class ProcessingContinueCallback(BaseScenario):
    """Обработка выбора продолжения диалога."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        continue_callback = callback_query.data
        user_data = await state.get_data()

        await callback_query.answer()

        if continue_callback == 'continue_yes':
            logger.info(f'Пользователь {user_id} решил продолжить диалог')
            await callback_query.message.delete()

            await state.update_data(skip_system_prompt=True)

            prompt_message = await self.bot.send_message(chat_id=user_id, text='Введите ваш следующий вопрос:')
            await state.update_data(prompt_message_id=prompt_message.message_id)
            await UserStates.CONTINUE_DIALOG.set()
        else:
            logger.info(f'Пользователь {user_id} решил начать новый диалог')
            await state.finish()
            await callback_query.message.delete()
            
            # ИЗМЕНЕНИЕ: Вместо выбора темы сразу переходим к новому анализу
            await self.bot.send_message(
                chat_id=user_id,
                text='Введите название компании или опишите ваш запрос для нового анализа инвестиционной привлекательности.'
            )
            await UserStates.ENTERING_PROMPT.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data in ['continue_yes', 'continue_no'],
            state=UserStates.ASKING_CONTINUE,
        )


class ContinueDialogHandler(BaseScenario):
    """Обработка продолжения диалога с той же моделью и темой."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_topic']
        model_name = user_data['chosen_model']

        logger.info(
            f'Продолжение диалога: {user_id}, модель={model_name}, тема={topic_name}, тип={message.content_type}',
        )

        if 'prompt_message_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['prompt_message_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["prompt_message_id"]}: {e}')

        await state.update_data(user_query=message.text)

        file_message = await message.answer(
            'Хотите ли вы прикрепить файл (PDF, Word, PPT) для анализа?',
            reply_markup=FileAttachKeyboard(),
        )

        await state.update_data(file_message_id=file_message.message_id)
        await UserStates.ATTACHING_FILE_CONTINUE.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, content_types=['text'], state=UserStates.CONTINUE_DIALOG)


class ResetStateHandler(BaseScenario):
    """Обработка команды /reset для сброса состояния пользователя."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        logger.info(f'Пользователь {user_id} запросил сброс состояния')

        await state.finish()

        # ИЗМЕНЕНИЕ: После reset тоже сразу идем к инвестиционному анализу
        await message.answer('Состояние сброшено. Введите название компании или опишите ваш запрос для анализа инвестиционной привлекательности.')
        await UserStates.ENTERING_PROMPT.set()

        logger.info(f'Состояние пользователя {user_id} успешно сброшено')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['reset'], state='*')


class AdminUpdatePromptsHandler(BaseScenario):
    """Обработка команды администратора для обновления системных промптов."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id
        logger.info(f'Запрос на обновление промптов от пользователя {user_id}')

        if user_id not in config.ADMIN_USERS:
            logger.warning(f'Отказано в доступе пользователю {user_id} - не является администратором')
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer('Выберите тему промпта для обновления:', reply_markup=AdminPromptKeyboard())
        await AdminStates.CHOOSING_PROMPT.set()
        logger.info(f'Пользователь {user_id} переведен в режим выбора промпта для обновления')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            commands=['update_prompts'],
            state='*',
        )


class AdminChoosePromptCallback(BaseScenario):
    """Обработка выбора промпта для обновления."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        prompt_callback = callback_query.data
        topic_name = prompt_callback.replace('prompt_', '')

        await callback_query.answer()

        logger.info(f'Администратор {user_id} выбрал промпт {topic_name} для обновления')
        await state.update_data(chosen_prompt=topic_name)

        await callback_query.message.delete()
        prompt_type_message = await callback_query.message.answer(
            'Выберите, какие промпты вы хотите обновить:',
            reply_markup=PromptTypeKeyboard(),
        )
        await state.update_data(prompt_type_message_id=prompt_type_message.message_id)
        await AdminStates.CHOOSING_PROMPT_TYPE.set()
        logger.info(f'Пользователь {user_id} переведен в режим выбора типа промпта')

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('prompt_'),
            state=AdminStates.CHOOSING_PROMPT,
        )


class AdminChoosePromptTypeCallback(BaseScenario):
    """Обработка выбора типа промпта для обновления (системный, детализированный или оба)."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        prompt_type = callback_query.data
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']

        await callback_query.answer()

        logger.info(f'Администратор {user_id} выбрал тип промпта {prompt_type} для топика {topic_name}')
        await state.update_data(chosen_prompt_type=prompt_type)

        if 'prompt_type_message_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['prompt_type_message_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["prompt_type_message_id"]}: {e}')

        if prompt_type == 'prompt_type_system':
            await callback_query.message.answer('Загрузите TXT-файл с новым содержимым системного промпта:')
            await AdminStates.UPLOADING_SYSTEM_PROMPT.set()
            logger.info(f'Пользователь {user_id} переведен в режим загрузки системного промпта')
        elif prompt_type == 'prompt_type_detail':
            await callback_query.message.answer('Загрузите TXT-файл с новым содержимым детализированного промпта:')
            await AdminStates.UPLOADING_DETAIL_PROMPT.set()
            logger.info(f'Пользователь {user_id} переведен в режим загрузки детализированного промпта')
        elif prompt_type == 'prompt_type_both':
            await callback_query.message.answer('Сначала загрузите TXT-файл с новым содержимым системного промпта:')
            await AdminStates.UPLOADING_SYSTEM_PROMPT.set()
            await state.update_data(upload_both_prompts=True)
            logger.info(f'Пользователь {user_id} переведен в режим загрузки обоих промптов, начиная с системного')

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('prompt_type_'),
            state=AdminStates.CHOOSING_PROMPT_TYPE,
        )


class AdminUploadSystemPromptHandler(BaseScenario):
    """Обработка загрузки файла с новым системным промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']
        upload_both = user_data.get('upload_both_prompts', False)

        logger.info(f'Получен файл для обновления системного промпта {topic_name} от администратора {user_id}')

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}',
            )
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        try:
            file_id = message.document.file_id
            file = await self.bot.get_file(file_id)
            file_path = file.file_path
            downloaded_file = await self.bot.download_file(file_path)
            logger.debug(f'Файл {message.document.file_name} успешно загружен')

            file_content = downloaded_file.read().decode('utf-8')
            logger.debug(f'Размер содержимого системного промпта: {len(file_content)} символов')

            system_prompts = SystemPrompts()
            system_prompts.set_prompt(SystemPrompt[topic_name.upper()], file_content)
            logger.info(f'Системный промпт {topic_name} успешно обновлен администратором {user_id}')

            if upload_both:
                await message.answer('Теперь загрузите TXT-файл с новым содержимым детализированного промпта:')
                await AdminStates.UPLOADING_DETAIL_PROMPT.set()
                logger.info(f'Пользователь {user_id} переведен в режим загрузки детализированного промпта')
                return

            await message.answer(f"Системный промпт для темы '{Topics[topic_name].value}' успешно обновлен!")
        except KeyError:
            logger.error(f'Ошибка: тема {topic_name} не найдена')
            await message.answer(f"Ошибка: тема '{topic_name}' не найдена.")
        except Exception as e:
            logger.error(f'Ошибка при обновлении системного промпта: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при обновлении системного промпта.\nСообщение об ошибке уже отправлено разработчику.\n'
                'Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при обновлении системного промпта: {e}',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()
        logger.info(f'Администратор {user_id} вернулся в режим выбора темы')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.UPLOADING_SYSTEM_PROMPT,
        )


class AdminUploadDetailPromptHandler(BaseScenario):
    """Обработка загрузки файла с новым детализированным промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']
        detail_topic_name = f'{topic_name.upper()}_DETAIL'

        logger.info(f'Получен файл для обновления детализированного промпта {topic_name} от администратора {user_id}')

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}',
            )
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        try:
            file_id = message.document.file_id
            file = await self.bot.get_file(file_id)
            file_path = file.file_path
            downloaded_file = await self.bot.download_file(file_path)
            logger.debug(f'Файл {message.document.file_name} успешно загружен')

            file_content = downloaded_file.read().decode('utf-8')
            logger.debug(f'Размер содержимого детализированного промпта: {len(file_content)} символов')

            if not hasattr(SystemPrompt, detail_topic_name):
                logger.warning(f'Детализированный промпт {detail_topic_name} не найден, возможно это ошибка')
                await message.answer(
                    'Предупреждение: детализированный промпт для этой темы не найден в системе. '
                    'Возможно, для данной темы его не существует.',
                )
            else:
                system_prompts = SystemPrompts()
                system_prompts.set_prompt(SystemPrompt[detail_topic_name], file_content)
                logger.info(f'Детализированный промпт {detail_topic_name} успешно обновлен администратором {user_id}')
                await message.answer(
                    f"Детализированный промпт для темы '{Topics[topic_name].value}' успешно обновлен!",
                )

        except KeyError:
            logger.error(f'Ошибка: тема {topic_name} или детализированный промпт {detail_topic_name} не найден')
            await message.answer(f'Ошибка: тема или детализированный промпт не найден.')
        except Exception as e:
            logger.error(f'Ошибка при обновлении детализированного промпта: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при обновлении промпта.\nСообщение об ошибке уже отправлено разработчику.\n'
                'Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при обновлении детализированного промпта: {e}',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()
        logger.info(f'Администратор {user_id} вернулся в режим выбора темы')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.UPLOADING_DETAIL_PROMPT,
        )


class AdminUploadPromptHandler(BaseScenario):
    """Обработка загрузки файла с новым промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']

        logger.info(
            f'Получен файл для обновления промпта {topic_name} от администратора {user_id} (обратная совместимость)',
        )

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}',
            )
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        try:
            file_id = message.document.file_id
            file = await self.bot.get_file(file_id)
            file_path = file.file_path
            downloaded_file = await self.bot.download_file(file_path)
            logger.debug(f'Файл {message.document.file_name} успешно загружен')

            file_content = downloaded_file.read().decode('utf-8')
            logger.debug(f'Размер содержимого промпта: {len(file_content)} символов')

            system_prompts = SystemPrompts()
            system_prompts.set_prompt(SystemPrompt[topic_name.upper()], file_content)
            logger.info(f'Промпт {topic_name} успешно обновлен администратором {user_id}')

            await message.answer(f"Промпт для темы '{Topics[topic_name].value}' успешно обновлен!")

        except KeyError:
            logger.error(f'Ошибка: тема {topic_name} не найдена')
            await message.answer(f"Ошибка: тема '{topic_name}' не найдена.")
        except Exception as e:
            logger.error(f'Ошибка при обновлении промпта: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при обновлении промпта.\nСообщение об ошибке уже отправлено разработчику.\n'
                'Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при обновлении промпта: {e}',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()
        logger.info(f'Администратор {user_id} вернулся в режим выбора темы')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.UPLOADING_PROMPT,
        )


class AdminNewPromptHandler(BaseScenario):
    """Обработка команды администратора для создания нового топика и промпта."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id

        if user_id not in config.ADMIN_USERS:
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer('Шаг 1: Введите техническое имя топика (только латинские буквы и цифры):')
        await AdminStates.NEW_PROMPT_NAME.set()
        logger.info(f'Администратор {user_id} начал процесс создания нового топика')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            commands=['new_prompt'],
            state='*',
        )


class AdminNewPromptNameHandler(BaseScenario):
    """Обработка ввода технического имени нового топика."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        prompt_name = message.text.strip().lower()
        logger.info(f'Получено техническое имя нового промпта от администратора {user_id}: {prompt_name}')

        if not prompt_name.isalnum() or not prompt_name.isascii():
            logger.warning(f'Некорректное имя промпта: {prompt_name}')
            await message.answer('Имя должно содержать только латинские буквы и цифры. Попробуйте еще раз:')
            return

        if prompt_name in Topics.__members__:
            logger.warning(f'Промпт с именем {prompt_name} уже существует')
            await message.answer(f"Топик с именем '{prompt_name}' уже существует. Введите другое имя:")
            return

        await state.update_data(new_prompt_name=prompt_name)
        await message.answer('Шаг 2: Введите отображаемое название топика (на русском):')
        await AdminStates.NEW_PROMPT_DISPLAY.set()
        logger.info(f'Администратор {user_id} перешел к вводу отображаемого имени для промпта {prompt_name}')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.NEW_PROMPT_NAME,
        )


class AdminNewPromptDisplayHandler(BaseScenario):
    """Обработка ввода отображаемого имени нового топика."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        display_name = message.text.strip()
        user_data = await state.get_data()
        prompt_name = user_data['new_prompt_name']

        logger.info(f'Получено отображаемое имя для промпта {prompt_name} от администратора {user_id}: {display_name}')

        if not display_name:
            logger.warning(f'Пустое отображаемое имя для промпта {prompt_name}')
            await message.answer('Отображаемое имя не может быть пустым. Введите отображаемое имя:')
            return

        await state.update_data(new_prompt_display=display_name)

        await message.answer(
            f"Шаг 3: Загрузите TXT-файл с системным промптом для топика '{display_name}':",
        )
        await AdminStates.NEW_PROMPT_UPLOAD.set()
        logger.info(f'Администратор {user_id} перешел к загрузке файла для нового промпта {prompt_name}')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.NEW_PROMPT_DISPLAY,
        )


class AdminNewPromptUploadHandler(BaseScenario):
    """Обработка загрузки файла с системным промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        prompt_name = user_data['new_prompt_name']
        display_name = user_data['new_prompt_display']

        logger.info(f'Получен файл для нового системного промпта {prompt_name} от администратора {user_id}')

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}',
            )
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        file_id = message.document.file_id
        file = await self.bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await self.bot.download_file(file_path)
        logger.debug(f'Файл {message.document.file_name} успешно загружен')

        file_content = downloaded_file.read().decode('utf-8')
        logger.debug(f'Размер содержимого системного промпта: {len(file_content)} символов')

        try:
            await state.update_data(system_prompt_content=file_content)
            await message.answer(f"Шаг 4: Загрузите TXT-файл с детализированным промптом для топика '{display_name}':")
            await AdminStates.NEW_PROMPT_UPLOAD_DETAIL.set()
            logger.info(f'Администратор {user_id} перешел к загрузке детализированного промпта для {prompt_name}')
        except Exception as e:
            logger.error(f'Ошибка при обработке системного промпта: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при обработке системного промпта.\nСообщение об ошибке уже отправлено разработчику.\n'
                'Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при обработке системного промпта: {e}\n\n{traceback.format_exc()}',
            )
            await state.finish()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.NEW_PROMPT_UPLOAD,
        )


class AdminNewPromptUploadDetailHandler(BaseScenario):
    """Обработка загрузки файла с детализированным промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        prompt_name = user_data['new_prompt_name']
        display_name = user_data['new_prompt_display']
        system_prompt_content = user_data['system_prompt_content']

        logger.info(f'Получен файл для нового детализированного промпта {prompt_name} от администратора {user_id}')

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}',
            )
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        file_id = message.document.file_id
        file = await self.bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await self.bot.download_file(file_path)
        logger.debug(f'Файл {message.document.file_name} успешно загружен')

        detail_prompt_content = downloaded_file.read().decode('utf-8')
        logger.debug(f'Размер содержимого детализированного промпта: {len(detail_prompt_content)} символов')

        try:
            system_prompts = SystemPrompts()
            system_prompts.add_new_prompt(prompt_name, display_name, system_prompt_content, detail_prompt_content)
            logger.info(f'Новый топик {prompt_name} ({display_name}) успешно добавлен администратором {user_id}')

            await message.answer(f"Топик '{display_name}' успешно создан с системным и детализированным промптами!")

            await self.bot.send_message(
                chat_id=user_id,
                text=f"Топик '{display_name}' успешно создан!\n\n"
                f'Системный промпт: {len(system_prompt_content)} символов\n'
                f'Детализированный промпт: {len(detail_prompt_content)} символов',
            )
        except Exception as e:
            logger.error(f'Ошибка при создании нового топика: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при создании топика.\nСообщение об ошибке уже отправлено разработчику.\n'
                'Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при создании топика: {e}\n\n{traceback.format_exc()}',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()
        logger.info(f'Администратор {user_id} вернулся в режим выбора темы')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.NEW_PROMPT_UPLOAD_DETAIL,
        )


class AdminNewPromptTextHandler(BaseScenario):
    """Обработка ввода текста вместо загрузки файла при создании нового промпта."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        await message.answer('Пожалуйста, загрузите TXT-файл с системным промптом.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.NEW_PROMPT_UPLOAD,
        )


class AdminUploadPromptTextHandler(BaseScenario):
    """Обработка ввода текста вместо загрузки файла при обновлении промпта."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        current_state = await state.get_state()
        logger.warning(
            f'Администратор {user_id} отправил текст вместо файла при обновлении промпта (состояние: {current_state})',
        )

        if current_state == 'AdminStates:UPLOADING_SYSTEM_PROMPT':
            await message.answer('Пожалуйста, загрузите TXT-файл с новым содержимым системного промпта.')
        elif current_state == 'AdminStates:UPLOADING_DETAIL_PROMPT':
            await message.answer('Пожалуйста, загрузите TXT-файл с новым содержимым детализированного промпта.')
        else:
            await message.answer('Пожалуйста, загрузите TXT-файл с новым содержимым промпта.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.UPLOADING_PROMPT,
        )
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.UPLOADING_SYSTEM_PROMPT,
        )
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.UPLOADING_DETAIL_PROMPT,
        )


class AdminLoadPromptsHandler(BaseScenario):
    """Обработка команды администратора для выгрузки всех системных промптов."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id

        if user_id not in config.ADMIN_USERS:
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer('Начинаю выгрузку всех системных промптов...')

        for prompt_file in DEFAULT_PROMPTS_DIR.glob('*.txt'):
            try:
                with open(prompt_file, 'rb') as f:
                    await message.answer_document(document=types.InputFile(f, filename=prompt_file.name))
            except Exception as e:
                logger.error(f'Ошибка при выгрузке промпта {prompt_file.name}: {e}')
                await message.answer(f'Ошибка при выгрузке промпта {prompt_file.name}')
                await self.bot.send_message(
                    chat_id=config.OWNER_ID,
                    text=f'Ошибка при выгрузке промпта {prompt_file.name}.\n{e}',
                )

        await message.answer('Выгрузка системных промптов завершена.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['load_prompts'], state='*')


class AdminUpdateScoutingExcelHandler(BaseScenario):
    """Обработка команды администратора для обновления excel файла скаутинга стартапов."""

    async def process(self, message: types.Message, **kwargs) -> Any:
        user_id = message.from_user.id
        if user_id not in config.ADMIN_USERS:
            logger.warning(f'Отказано в доступе пользователю {user_id} - не является администратором')
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer('Отправьте Excel(.xlsx) файл для обновления.')
        await AdminStates.UPLOADING_SCOUTING_FILE.set()
        logger.info(f'Пользователь {user_id} переведен в режим обновления файла скаутинга.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            commands=['update_scouting_prompts'],
            state='*',
        )


class AdminUploadScoutingExcelFileHandler(BaseScenario):
    """Обработка загрузки файла с новым excel файлом для скаутинга."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> Any:
        user_id = message.from_user.id

        logger.info(f'Получен файл для обновления excel файла для скаутинга от администратора {user_id}')

        if not message.document or not message.document.file_name.endswith('.xlsx'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}'
            )
            await message.answer('Пожалуйста, загрузите файл в формате XLSX.')
            return

        try:
            file_id = message.document.file_id
            file = await self.bot.get_file(file_id)
            file_path = file.file_path
            downloaded_file = await self.bot.download_file(file_path)
            logger.debug(f'Файл {message.document.file_name} успешно загружен')

            file_content = downloaded_file.read()
            logger.debug(f'Размер содержимого excel файла: {len(file_content)} символов')

            await self.bot.send_chat_action(chat_id=user_id, action='upload_document')

            file_manager = ExcelFileManager()
            await file_manager.update_excel_file(file_content)
            logger.info(f'Excel файл успешно обновлен администратором {user_id}')

            await file_manager.delete_file()
            await file_manager.upload_file()

            await message.answer('Файл обновляется на серверах OpenAI, пожалуйста ожидайте')
            is_file_updated = await file_manager.check_status_file()
            if not is_file_updated:
                await message.answer('Не удалось обновить файл. Сообщение об ошибке отправлено разработчику.')

            logger.info('Excel файл успешно обновлен в OpenAI')
            await message.answer('Excel файл успешно обновлен и готов к использованию.')

        except Exception as e:
            logger.error(f'Ошибка при обновлении excel файла для скаутинга: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при обновлении excel файла для скаутинга.\nСообщение об ошибке уже отправлено разработчику.\n'
                'Продолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при обновлении excel файла для скаутинга: {e}',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()
        logger.info(f'Администратор {user_id} вернулся в режим выбора темы')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.UPLOADING_SCOUTING_FILE,
        )


class AdminHelpHandler(BaseScenario):
    """Обработка команды /help для администратора."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id

        if user_id not in config.ADMIN_USERS:
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        help_text = (
            '🔑 Административные команды:\n\n'
            '/update_prompts - Обновление существующего системного промпта. Позволяет выбрать тему, '
            'тип промпта (системный, детализированный или оба) и загрузить '
            'TXT-файл(ы) с новым содержимым.\n\n'
            '/new_prompt - Создание нового топика и системного промпта. Проведет через процесс создания '
            'нового топика с указанием технического имени, отображаемого названия и загрузкой файла промпта.\n\n'
            '/load_prompts - Выгрузка всех системных промптов в виде TXT-файлов для просмотра или редактирования.\n\n'
            '/update_scouting_prompts - Обновление excel файла для темы "Скаутинг стартапов"\n\n'
            '/list_auth_users - Получить список id авторизованных пользователей.\n\n'
            '/start - Перезапуск бота и возврат к выбору темы анализа.'
        )

        await message.answer(help_text)

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['help'], state='*')


class AdminListAuthUsersHandler(BaseScenario):
    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id

        if user_id not in config.ADMIN_USERS:
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        auth_user_list = ', '.join([str(i) for i in config.AUTHORIZED_USERS_IDS])
        await message.answer(auth_user_list)

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['list_auth_users'], state='*')


class BotManager:
    scenarios: Dict[str, BaseScenario] = {}

    main_scenario = {
        'access': Access,
        'start': StartHandler,
        # УБИРАЕМ: 'choose_topic': ProcessingChooseTopicCallback,
        'enter_prompt': ProcessingEnterPromptHandler,
        'attach_file': AttachFileHandler,
        'upload_file': UploadFileHandler,
        'continue_dialog': ContinueDialogHandler,
        'continue_callback': ProcessingContinueCallback,
        'reset_state': ResetStateHandler,
    }

    admins_update_system_prompts_scenario = {
        'update_prompts': AdminUpdatePromptsHandler,
        'choose_prompt': AdminChoosePromptCallback,
        'choose_prompt_type': AdminChoosePromptTypeCallback,
        'upload_system_prompt': AdminUploadSystemPromptHandler,
        'upload_detail_prompt': AdminUploadDetailPromptHandler,
        'upload_prompt': AdminUploadPromptHandler,
        'upload_prompt_text': AdminUploadPromptTextHandler,
    }

    admin_new_system_prompts_scenario = {
        'new_prompt': AdminNewPromptHandler,
        'new_prompt_name': AdminNewPromptNameHandler,
        'new_prompt_display': AdminNewPromptDisplayHandler,
        'new_prompt_upload': AdminNewPromptUploadHandler,
        'new_prompt_upload_detail': AdminNewPromptUploadDetailHandler,
        'new_prompt_text': AdminNewPromptTextHandler,
        'load_prompts': AdminLoadPromptsHandler,
    }

    admin_update_scouting_excel = {
        'update_scouting_excel': AdminUpdateScoutingExcelHandler,
        'upload_scouting_excel': AdminUploadScoutingExcelFileHandler,
    }

    admin_common_scenario = {
        'help': AdminHelpHandler,
        'auth_users_list': AdminListAuthUsersHandler,
    }

    def __init__(self, bot: Bot, dp: Dispatcher) -> None:
        self.bot = bot
        self.dp = dp

        # ВАЖНО: Создаем investment_analysis_scenario ПЕРЕД регистрацией
        self.investment_analysis_scenario = { 
            'investment_actions': InvestmentActionsHandler,    
            'investment_qa': InvestmentQAHandler, 
            'back_to_investment_actions': BackToInvestmentActionsHandler, 
            'investment_report': InvestmentReportHandler, 
            'email_input': EmailInputHandler,
            'final_actions': FinalActionsHandler,  # ДОБАВЛЯЕМ
        } 
        logger.info(f"Investment analysis scenario created: {list(self.investment_analysis_scenario.keys())}") 

        self._setup_middlewares()

        # Регистрируем все сценарии в правильном порядке
        all_scenarios = [
            ('main', self.main_scenario),
            ('investment', self.investment_analysis_scenario),  # ПЕРЕМЕЩЕНО ВВЕРХ
            ('admin_update', self.admins_update_system_prompts_scenario),
            ('admin_new', self.admin_new_system_prompts_scenario),
            ('admin_scouting', self.admin_update_scouting_excel),
            ('admin_common', self.admin_common_scenario),
        ]

        # Создаем и регистрируем все сценарии
        for scenario_group, scenarios in all_scenarios:
            for scenario_name, scenario_class in scenarios.items():
                full_name = f'{scenario_group}_{scenario_name}'
                logger.info(f'Registering scenario: {full_name}')
                scenario_instance = scenario_class(bot)
                self._register_scenario(full_name, scenario_instance)

        # ВАЖНО: Вызываем register() для ВСЕХ сценариев после их создания
        logger.info("Starting registration of all handlers...")
        for scenario_name, scenario in self.scenarios.items():
            logger.info(f'Calling register() for scenario: {scenario_name}')
            try:
                scenario.register(dp)
                logger.info(f'Successfully registered: {scenario_name}')
            except Exception as e:
                logger.error(f'Failed to register {scenario_name}: {e}')

        logger.info(f"Total scenarios registered: {len(self.scenarios)}")

    def _register_scenario(self, name: str, scenario: BaseScenario) -> None:
        self.scenarios[name] = scenario
        logger.info(f'Scenario {name} added to scenarios dict')

    def _setup_middlewares(self) -> None:
        self.dp.middleware.setup(AccessMiddleware())


if __name__ == '__main__':
    config = Config()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(bot, storage=MemoryStorage())

    BotManager(bot, dp)

    executor.start_polling(dp, skip_updates=True)



