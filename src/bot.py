from abc import ABC, abstractmethod
import logging
from typing import Dict, Any, Tuple
import re
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from access_middleware import AccessMiddleware
from keyboards_builder import Button, Keyboard, DynamicKeyboard
from logger import Logger
from config import Config
from models_api import ModelAPI
from prompts import DEFAULT_PROMPTS_DIR, Models, SystemPrompt, Topics, SystemPrompts
from chat_context import ChatContextManager
from file_processor import FileProcessor
import aiogram.utils.exceptions
import traceback

Logger()
logger = logging.getLogger('bot')


class UserStates(StatesGroup):
    ACCESS = State()
    CHOOSING_TOPIC = State()  # Выбор темы анализа
    CHOOSING_MODEL = State()  # Выбор модели
    ENTERING_PROMPT = State()  # Ввод запроса
    ATTACHING_FILE = State()  # Ожидание прикрепления файла
    UPLOADING_FILE = State()  # Загрузка файла
    ASKING_CONTINUE = State()  # Спрашиваем, есть ли еще вопросы
    CONTINUE_DIALOG = State()  # Продолжение диалога с той же моделью и темой
    ATTACHING_FILE_CONTINUE = State()  # Ожидание прикрепления файла при продолжении диалога
    UPLOADING_FILE_CONTINUE = State()  # Загрузка файла при продолжении диалога


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


class BaseScenario(ABC):
    """Базовый класс для сценариев."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    @abstractmethod
    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> Any:
        pass

    @abstractmethod
    def register(self, dp: Dispatcher) -> None:
        pass

    def _escape_markdown(self, text: str) -> str:
        """Экранирует потенциально опасные символы Markdown для безопасной отправки."""
        try:
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            
            chars = '_*[]()~`>#+-=|{}.!'
            
            for char in chars:
                text = text.replace(char, f'\\{char}')
            
            logger.debug(f'Успешно экранирован текст для Markdown, размер: {len(text)} символов')
            return text
        except Exception as e:
            logger.error(f'Ошибка при экранировании текста для Markdown: {e}', exc_info=True)
            return text


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
            await message.answer('Здравствуйте! Чем я могу вам помочь?', reply_markup=TopicKeyboard())
            await UserStates.CHOOSING_TOPIC.set()

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
        prompt_message = await callback_query.message.answer('Какой Ваш запрос?')
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
        user_data = await state.get_data()
        topic_name = user_data['chosen_topic']
        model_name = user_data['chosen_model']

        logger.info(f'Получен текстовый запрос от {user_id}: модель={model_name}, тема={topic_name}')

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
        await UserStates.ATTACHING_FILE.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=UserStates.ENTERING_PROMPT,
        )


class AttachFileCallback(BaseScenario):
    """Обработка выбора прикрепления файла."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        user_data = await state.get_data()

        await callback_query.answer()

        if 'file_message_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['file_message_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["file_message_id"]}: {e}')

        if callback_query.data == 'attach_file':
            logger.info(f'Пользователь {user_id} решил прикрепить файл')
            file_prompt = await callback_query.message.answer('Пожалуйста, загрузите файл (PDF, Word, PPT):')
            await state.update_data(file_prompt_id=file_prompt.message_id)
            await UserStates.UPLOADING_FILE.set()
        else:
            logger.info(f'Пользователь {user_id} решил продолжить без файла')
            await self.process_query_with_file(callback_query.message, state, file_content='')

    async def process_query_with_file(self, message, state, file_content=''):
        """Обрабатывает запрос с файлом или без него."""
        user_id = message.chat.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_topic']
        model_name = user_data['chosen_model']
        user_query = user_data.get('user_query', '')

        was_file_model = user_data.get('was_file_model', False)
        skip_system_prompt = user_data.get('skip_system_prompt', False)

        if 'processing_msg_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['processing_msg_id'])
                logger.debug(f'Удалено сообщение об обработке файла {user_data["processing_msg_id"]}')
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения об обработке файла {user_data["processing_msg_id"]}: {e}')

        if not user_query and not file_content:
            await message.answer(
                'Необходимо ввести запрос или прикрепить файл. Пожалуйста, начните заново с команды /start',
            )
            return

        full_query = f'{user_query}\n\nКонтекст из файла:\n{file_content}' if file_content else user_query

        chat_context = ChatContextManager()
        chat_context.add_message(user_id, topic_name, 'user', full_query)

        if model_name == 'chatgpt' and (not file_content or was_file_model):
            messages = chat_context.get_limited_messages_for_api(user_id, topic_name, skip_system_prompt=skip_system_prompt)
            logger.info(
                f'Подготовлено {len(messages)} ограниченных сообщений для API, чтобы избежать превышения лимита токенов'
            )
        else:
            messages = chat_context.get_messages_for_api(user_id, topic_name)
            logger.info(f'Подготовлено {len(messages)} сообщений для API, размер запроса: {len(full_query)} символов')

        if skip_system_prompt and model_name != 'chatgpt':
            messages = [msg for msg in messages if msg['role'] != 'system']
            logger.info(f'Системный промпт пропущен, отправляется {len(messages)} сообщений')

        if file_content and model_name == 'chatgpt':
            logger.info(f'Обнаружен файл, переключение на модель chatgpt_file вместо {model_name}')
            model_name = 'chatgpt_file'
            await state.update_data(was_file_model=True)

        strategy = Models[model_name].value()
        model_api = ModelAPI(strategy)

        try:
            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            logger.info(f'Отправка запроса к {model_name} для пользователя {user_id}')

            response = await model_api.get_response(messages)
            logger.info(f'Получен ответ от {model_name}, длина: {len(response)} символов')

            chat_context.add_message(user_id, topic_name, 'assistant', response)

            system_prompts = SystemPrompts()
            detail_prompt_type = f"{topic_name.upper()}_DETAIL"
            if hasattr(SystemPrompt, detail_prompt_type):
                detail_prompt = system_prompts.get_prompt(SystemPrompt[detail_prompt_type])
                
                detail_messages = [
                    {'role': 'system', 'content': detail_prompt},
                    {'role': 'user', 'content': full_query}
                ]

                detail_response = await model_api.get_response(detail_messages)
                logger.info(f'Получен детализированный ответ, длина: {len(detail_response)} символов')

                escaped_response = self._escape_markdown(response)
                escaped_detail = self._escape_markdown(detail_response)
                
                formatted_detail = escaped_detail.replace('\n', '\n>>')
                formatted_response = f"{escaped_response}\n\n>>{formatted_detail}"
            else:
                escaped_response = self._escape_markdown(response)
                formatted_response = escaped_response

            max_length = 4000
            for i in range(0, len(formatted_response), max_length):
                part = formatted_response[i : i + max_length]
                await message.answer(part, parse_mode='MarkdownV2')

            await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
            await UserStates.ASKING_CONTINUE.set()
        except aiogram.utils.exceptions.InvalidQueryID:
            logger.warning(f'Устаревший callback_query для пользователя {user_id}')
        except Exception as e:
            logger.error(f'Ошибка API {model_name}: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при получении ответа. Попробуйте еще раз или выберите другую модель введя команду `/start`.',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Ошибка при отправке запроса в {model_name}.\n{e}',
            )

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data in ['attach_file', 'no_file'],
            state=UserStates.ATTACHING_FILE,
        )


class UploadFileHandler(BaseScenario):
    """Обработка загрузки файла."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()

        if 'file_prompt_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['file_prompt_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["file_prompt_id"]}: {e}')

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

            attach_file_handler = AttachFileCallback(self.bot)
            await attach_file_handler.process_query_with_file(message, state, file_content)

        except ValueError as e:
            logger.error(f'Ошибка обработки файла {file_name}: {e}')
            await message.answer(
                f'Произошла ошибка при обработке файла.\nСообщение об ошибке уже отправлено разработчику.\nПродолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'{e}',
            )

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=UserStates.UPLOADING_FILE,
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
        elif continue_callback == 'request_details':
            logger.info(f'Пользователь {user_id} запросил детальную информацию')
            await callback_query.message.delete()

            topic_name = user_data.get('chosen_topic')
            model_name = user_data.get('chosen_model')

            if topic_name in ['startups', 'investment']:
                system_prompts = SystemPrompts()
                if topic_name == 'startups':
                    system_prompt = system_prompts.get_prompt(SystemPrompt.STARTUPS_DETAIL)
                elif topic_name == 'investment':
                    system_prompt = system_prompts.get_prompt(SystemPrompt.INVESTMENT_DETAIL)

                chat_context = ChatContextManager()

                messages = chat_context.get_messages_for_api(user_id, topic_name)

                if model_name == 'chatgpt':
                    logger.info(f'Запрос деталей, переключение на модель chatgpt_file вместо {model_name}')
                    model_name = 'chatgpt_file'
                    await state.update_data(was_file_model=True)

                strategy = Models[model_name].value()
                model_api = ModelAPI(strategy)

                await self.bot.send_chat_action(chat_id=user_id, action='typing')
                logger.info(f'Отправка запроса на детальный анализ к {model_name} для пользователя {user_id}')

                new_messages = [{'role': 'system', 'content': system_prompt}]
                user_messages = [msg for msg in messages if msg['role'] == 'user']
                if user_messages:
                    new_messages.append(user_messages[-1])

                logger.info(f'Запрос деталей с минимальным контекстом: {len(new_messages)} сообщений')

                response = await model_api.get_response(new_messages)
                logger.info(f'Получен детальный ответ от {model_name}, длина: {len(response)} символов')

                chat_context.add_message(user_id, topic_name, 'assistant', response)
                escaped_response = self._escape_markdown(response)

                max_length = 4000
                for i in range(0, len(escaped_response), max_length):
                    part = escaped_response[i : i + max_length]
                    await self.bot.send_message(chat_id=user_id, text=part, parse_mode='MarkdownV2')

                await self.bot.send_message(
                    chat_id=user_id, text='Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard()
                )
                await UserStates.ASKING_CONTINUE.set()
            else:
                await self.bot.send_message(
                    chat_id=user_id,
                    text='Детальный анализ не поддерживается для этого типа запроса.',
                    reply_markup=ContinueKeyboard(),
                )
                await UserStates.ASKING_CONTINUE.set()
        else:
            logger.info(f'Пользователь {user_id} решил начать новый диалог')
            await callback_query.message.delete()
            await self.bot.send_message(
                chat_id=user_id, text='Выберите тему для анализа:', reply_markup=TopicKeyboard()
            )
            await UserStates.CHOOSING_TOPIC.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data in ['continue_yes', 'continue_no', 'request_details'],
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
            f'Продолжение диалога: {user_id}, модель={model_name}, тема={topic_name}, тип={message.content_type}'
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


class AttachFileContinueCallback(BaseScenario):
    """Обработка выбора прикрепления файла при продолжении диалога."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        user_data = await state.get_data()

        await callback_query.answer()

        if 'file_message_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['file_message_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["file_message_id"]}: {e}')

        if callback_query.data == 'attach_file':
            logger.info(f'Пользователь {user_id} решил прикрепить файл при продолжении диалога')
            file_prompt = await callback_query.message.answer('Пожалуйста, загрузите файл (PDF, Word, PPT):')
            await state.update_data(file_prompt_id=file_prompt.message_id)
            await UserStates.UPLOADING_FILE_CONTINUE.set()
        else:
            logger.info(f'Пользователь {user_id} решил продолжить без файла')
            await self.process_query_with_file(callback_query.message, state, file_content='')

    async def process_query_with_file(self, message, state, file_content=''):
        """Обрабатывает запрос с файлом или без него."""
        user_id = message.chat.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_topic']
        model_name = user_data['chosen_model']
        user_query = user_data.get('user_query', '')

        was_file_model = user_data.get('was_file_model', False)
        skip_system_prompt = user_data.get('skip_system_prompt', False)

        if 'processing_msg_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['processing_msg_id'])
                logger.debug(f'Удалено сообщение об обработке файла {user_data["processing_msg_id"]}')
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения об обработке файла {user_data["processing_msg_id"]}: {e}')

        if not user_query and not file_content:
            await message.answer(
                'Необходимо ввести запрос или прикрепить файл. Пожалуйста, начните заново с команды /start'
            )
            return

        full_query = f'{user_query}\n\nКонтекст из файла:\n{file_content}' if file_content else user_query

        chat_context = ChatContextManager()
        chat_context.add_message(user_id, topic_name, 'user', full_query)

        if model_name == 'chatgpt' and (not file_content or was_file_model):
            messages = chat_context.get_limited_messages_for_api(user_id, topic_name, skip_system_prompt=skip_system_prompt)
            logger.info(
                f'Подготовлено {len(messages)} ограниченных сообщений для API, чтобы избежать превышения лимита токенов'
            )
        else:
            messages = chat_context.get_messages_for_api(user_id, topic_name)
            logger.info(f'Подготовлено {len(messages)} сообщений для API, размер запроса: {len(full_query)} символов')

        if skip_system_prompt and model_name != 'chatgpt':
            messages = [msg for msg in messages if msg['role'] != 'system']
            logger.info(f'Системный промпт пропущен, отправляется {len(messages)} сообщений')

        if file_content and model_name == 'chatgpt':
            logger.info(f'Обнаружен файл, переключение на модель chatgpt_file вместо {model_name}')
            model_name = 'chatgpt_file'
            await state.update_data(was_file_model=True)

        strategy = Models[model_name].value()
        model_api = ModelAPI(strategy)

        try:
            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            logger.info(f'Отправка запроса к {model_name} для пользователя {user_id}')

            response = await model_api.get_response(messages)
            logger.info(f'Получен ответ от {model_name}, длина: {len(response)} символов')

            chat_context.add_message(user_id, topic_name, 'assistant', response)

            system_prompts = SystemPrompts()
            detail_prompt_type = f"{topic_name.upper()}_DETAIL"
            if hasattr(SystemPrompt, detail_prompt_type):
                detail_prompt = system_prompts.get_prompt(SystemPrompt[detail_prompt_type])
                
                detail_messages = [
                    {'role': 'system', 'content': detail_prompt},
                    {'role': 'user', 'content': full_query}
                ]

                detail_response = await model_api.get_response(detail_messages)
                logger.info(f'Получен детализированный ответ, длина: {len(detail_response)} символов')

                escaped_response = self._escape_markdown(response)
                escaped_detail = self._escape_markdown(detail_response)
                
                formatted_detail = escaped_detail.replace('\n', '\n>>')
                formatted_response = f"{escaped_response}\n\n>>{formatted_detail}"
            else:
                escaped_response = self._escape_markdown(response)
                formatted_response = escaped_response

            max_length = 4000
            for i in range(0, len(formatted_response), max_length):
                part = formatted_response[i : i + max_length]
                await message.answer(part, parse_mode='MarkdownV2')

            await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
            await UserStates.ASKING_CONTINUE.set()
        except aiogram.utils.exceptions.InvalidQueryID:
            logger.warning(f'Устаревший callback_query для пользователя {user_id}')
        except Exception as e:
            logger.error(f'Ошибка API {model_name}: {e}', exc_info=True)
            await message.answer(
                'Произошла ошибка при получении ответа. Попробуйте еще раз или выберите другую модель введя команду `/start`.',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Ошибка при отправке запроса в {model_name}.\n{e}',
            )

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data in ['attach_file', 'no_file'],
            state=UserStates.ATTACHING_FILE_CONTINUE,
        )


class UploadFileContinueHandler(BaseScenario):
    """Обработка загрузки файла при продолжении диалога."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()

        if 'file_prompt_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['file_prompt_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["file_prompt_id"]}: {e}')

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

            attach_file_handler = AttachFileContinueCallback(self.bot)
            await attach_file_handler.process_query_with_file(message, state, file_content)

        except ValueError as e:
            logger.error(f'Ошибка обработки файла {file_name}: {e}')
            await message.answer(
                f'Произошла ошибка при обработке файла.\nСообщение об ошибке уже отправлено разработчику.\nПродолжите использование нажав команду /start',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Ошибка при обработке файла: {e}',
            )

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=UserStates.UPLOADING_FILE_CONTINUE,
        )


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
            reply_markup=PromptTypeKeyboard()
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
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}'
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
        detail_topic_name = f"{topic_name.upper()}_DETAIL"

        logger.info(f'Получен файл для обновления детализированного промпта {topic_name} от администратора {user_id}')

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}'
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
                    'Возможно, для данной темы его не существует.'
                )
            else:
                system_prompts = SystemPrompts()
                system_prompts.set_prompt(SystemPrompt[detail_topic_name], file_content)
                logger.info(f'Детализированный промпт {detail_topic_name} успешно обновлен администратором {user_id}')
                await message.answer(f"Детализированный промпт для темы '{Topics[topic_name].value}' успешно обновлен!")
                
        except KeyError:
            logger.error(f'Ошибка: тема {topic_name} или детализированный промпт {detail_topic_name} не найден')
            await message.answer(f"Ошибка: тема или детализированный промпт не найден.")
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
    """Обработка загрузки файла с новым промптом (для обратной совместимости)."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']

        logger.info(f'Получен файл для обновления промпта {topic_name} от администратора {user_id} (обратная совместимость)')

        if not message.document or not message.document.file_name.endswith('.txt'):
            logger.warning(
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}'
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
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}'
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
                f'Неверный формат файла от пользователя {user_id}: {message.document.file_name if message.document else "нет файла"}'
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
                     f"Системный промпт: {len(system_prompt_content)} символов\n"
                     f"Детализированный промпт: {len(detail_prompt_content)} символов"
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
        logger.warning(f'Администратор {user_id} отправил текст вместо файла при обновлении промпта (состояние: {current_state})')
        
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
            '/start - Перезапуск бота и возврат к выбору темы анализа.'
        )

        await message.answer(help_text)

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['help'], state='*')


class ResetStateHandler(BaseScenario):
    """Обработка команды /reset для сброса состояния пользователя."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        logger.info(f'Пользователь {user_id} запросил сброс состояния')

        await state.finish()

        await message.answer('Состояние сброшено. Выберите тему для анализа:', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()

        logger.info(f'Состояние пользователя {user_id} успешно сброшено')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['reset'], state='*')


class BotManager:
    scenarios: Dict[str, BaseScenario] = {}

    main_scenario = {
        'access': Access,
        'start': StartHandler,
        'choose_topic': ProcessingChooseTopicCallback,
        'enter_prompt': ProcessingEnterPromptHandler,
        'attach_file': AttachFileCallback,
        'upload_file': UploadFileHandler,
        'continue_dialog': ContinueDialogHandler,
        'continue_callback': ProcessingContinueCallback,
        'attach_file_continue': AttachFileContinueCallback,
        'upload_file_continue': UploadFileContinueHandler,
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

    admin_common_scenario = {
        'help': AdminHelpHandler,
    }

    def __init__(self, bot: Bot, dp: Dispatcher) -> None:
        self.bot = bot
        self.dp = dp

        self._setup_middlewares()

        for scenario_name, scenario in self.main_scenario.items():
            logger.info(f'Add for registering handler: {scenario_name}')
            self._register_scenario(scenario_name, scenario(bot))

        for scenario_name, scenario in self.admins_update_system_prompts_scenario.items():
            logger.info(f'Add for registering admin update handler: {scenario_name}')
            self._register_scenario(f'admin_update_{scenario_name}', scenario(bot))

        for scenario_name, scenario in self.admin_new_system_prompts_scenario.items():
            logger.info(f'Add for registering admin new handler: {scenario_name}')
            self._register_scenario(f'admin_new_{scenario_name}', scenario(bot))

        for scenario_name, scenario in self.admin_common_scenario.items():
            logger.info(f'Add for registering admin common handler: {scenario_name}')
            self._register_scenario(f'admin_common_{scenario_name}', scenario(bot))

        for scenario in self.scenarios.values():
            scenario.register(dp)

    def _register_scenario(self, name: str, scenario: BaseScenario) -> None:
        self.scenarios[name] = scenario

    def _setup_middlewares(self) -> None:
        self.dp.middleware.setup(AccessMiddleware())


if __name__ == '__main__':
    config = Config()
    bot = Bot(token=config.TOKEN)
    dp = Dispatcher(bot, storage=MemoryStorage())

    BotManager(bot, dp)

    executor.start_polling(dp, skip_updates=True)
