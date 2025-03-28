from abc import ABC, abstractmethod
import logging
from typing import Dict, Any, Tuple
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

Logger()
logger = logging.getLogger('bot')


class UserStates(StatesGroup):
    ACCESS = State()
    CHOOSING_TOPIC = State()  # Выбор темы анализа
    CHOOSING_MODEL = State()  # Выбор модели
    ENTERING_PROMPT = State()  # Ввод запроса
    ASKING_CONTINUE = State()  # Спрашиваем, есть ли еще вопросы
    CONTINUE_DIALOG = State()  # Продолжение диалога с той же моделью и темой


class AdminStates(StatesGroup):
    """Состояния для административных функций."""

    CHOOSING_PROMPT = State()  # Выбор промпта для обновления
    UPLOADING_PROMPT = State()  # Загрузка файла с новым промптом
    NEW_PROMPT_NAME = State()  # Ввод технического имени нового топика
    NEW_PROMPT_DISPLAY = State()  # Ввод отображаемого имени нового топика
    NEW_PROMPT_UPLOAD = State()  # Загрузка файла с системным промптом


class TopicKeyboard(DynamicKeyboard):
    """Клавиатура для выбора темы."""

    @classmethod
    def get_buttons(cls) -> Tuple[Button, ...]:
        """Генерирует кнопки на основе доступных топиков."""
        buttons = []

        for topic_name, topic in Topics.__members__.items():
            buttons.append(Button(text=topic.value, callback=f'topic_{topic_name}'))

        return tuple(buttons)


class ModelKeyboard(DynamicKeyboard):
    """Клавиатура для выбора модели."""

    _buttons = (Button(model.name, f'model_{model.name}') for model in Models)


class ContinueKeyboard(Keyboard):
    """Клавиатура для продолжения диалога."""

    _buttons = ([Button('Да', 'continue_yes'), Button('Нет', 'continue_no')],)


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
        """Экранирует специальные символы Markdown."""
        try:
            chars = '_*[]()~`>#+-=|{}.!'
            for char in chars:
                text = text.replace(char, f'\\{char}')
            logger.debug(f'Успешно экранирован текст для Markdown, размер: {len(text)} символов')
            return text
        except Exception as e:
            logger.error(f'Ошибка при экранировании текста для Markdown: {e}')
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
            await message.answer('Добро пожаловать! Чем я могу вам помочь?', reply_markup=TopicKeyboard())
            await UserStates.CHOOSING_TOPIC.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['start'], state='*')


class ProcessingChooseTopicCallback(BaseScenario):
    """Обработка выбора темы."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        topic_callback = callback_query.data
        topic_name = topic_callback.replace('topic_', '')

        logger.info(f'Пользователь {user_id} выбрал тему: {topic_name}')

        system_prompts = SystemPrompts()
        system_prompt = system_prompts.get_prompt(SystemPrompt[topic_name.upper()])

        chat_context = ChatContextManager()
        chat_context.start_new_chat(user_id, topic_name, system_prompt)

        await state.update_data(chosen_topic=topic_name)
        await callback_query.message.delete()
        await callback_query.message.answer('Выберите ИИ-сервис для работы:', reply_markup=ModelKeyboard())
        await UserStates.CHOOSING_MODEL.set()
        await callback_query.answer()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('topic_'),
            state=UserStates.CHOOSING_TOPIC,
        )


class ProcessingChooseModelCallback(BaseScenario):
    """Обработка выбора модели."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        model_callback = callback_query.data
        model_name = model_callback.replace('model_', '')

        logger.info(f'Пользователь {user_id} выбрал модель: {model_name}')

        selected_model = Models[model_name]

        await state.update_data(chosen_model=selected_model.name, model_display=selected_model.value)
        await callback_query.message.delete()
        prompt_message = await callback_query.message.answer(
            'Какой Ваш запрос? Вы также можете прикрепить файл (PDF, Word, PPT).'
        )

        await state.update_data(prompt_message_id=prompt_message.message_id)
        await UserStates.ENTERING_PROMPT.set()
        await callback_query.answer()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('model_'),
            state=UserStates.CHOOSING_MODEL,
        )


class ProcessingEnterPromptHandler(BaseScenario):
    """Обработка ввода промпта и файлов пользователем."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_topic']
        model_name = user_data['chosen_model']

        logger.info(f'Запрос от {user_id}: модель={model_name}, тема={topic_name}, тип={message.content_type}')

        if 'prompt_message_id' in user_data:
            try:
                await self.bot.delete_message(chat_id=user_id, message_id=user_data['prompt_message_id'])
            except Exception as e:
                logger.error(f'Ошибка удаления сообщения {user_data["prompt_message_id"]}: {e}')

        file_content = ''
        if message.document:
            file_name = message.document.file_name
            file_size = message.document.file_size
            logger.info(f'Обработка файла: {file_name} ({file_size} байт)')
            try:
                file_content = await FileProcessor.extract_text_from_file(message.document, self.bot)
                logger.info(f'Извлечено {len(file_content)} символов из файла {file_name}')
            except ValueError as e:
                logger.error(f'Ошибка обработки файла {file_name}: {e}')
                await message.answer(f'Ошибка при обработке файла: {e}')
                return

        user_query = message.text
        full_query = f'{user_query}\n\nКонтекст из файла:\n{file_content}' if file_content else user_query

        chat_context = ChatContextManager()
        chat_context.add_message(user_id, topic_name, 'user', full_query)
        messages = chat_context.get_messages_for_api(user_id, topic_name)
        logger.info(f'Подготовлено {len(messages)} сообщений для API, размер запроса: {len(full_query)} символов')

        model = Models[model_name].value
        model_api = ModelAPI(model())

        try:
            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            logger.info(f'Отправка запроса к {model_name} для пользователя {user_id}')

            response = await model_api.get_response(messages)
            logger.info(f'Получен ответ от {model_name}, длина: {len(response)} символов')

            chat_context.add_message(user_id, topic_name, 'assistant', response)
            escaped_response = self._escape_markdown(response)

            await message.answer(escaped_response, parse_mode='MarkdownV2')
            await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
            await UserStates.ASKING_CONTINUE.set()
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
        dp.register_message_handler(
            self.process,
            content_types=['text', 'document'],
            state=UserStates.ENTERING_PROMPT,
        )


class ProcessingContinueCallback(BaseScenario):
    """Обработка ответа на вопрос о продолжении диалога."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_topic']
        continue_dialog = callback_query.data == 'continue_yes'

        logger.info(
            f'Пользователь {user_id} решил {"продолжить" if continue_dialog else "завершить"} диалог по теме {topic_name}',
        )

        chat_context = ChatContextManager()
        await callback_query.message.delete()

        if continue_dialog:
            prompt_message = await callback_query.message.answer(
                'Введите ваш следующий вопрос или загрузите новый документ (PDF, Word, PPT):',
            )
            await state.update_data(prompt_message_id=prompt_message.message_id)
            await UserStates.ENTERING_PROMPT.set()
        else:
            chat_context.end_chat(user_id, topic_name)
            chat_context.cleanup_user_context(user_id)
            logger.info(f'Очищен контекст чата для пользователя {user_id}')

            await state.finish()
            await callback_query.message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
            await UserStates.CHOOSING_TOPIC.set()

        await callback_query.answer()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('continue_'),
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

        file_content = ''
        if message.document:
            file_name = message.document.file_name
            file_size = message.document.file_size
            logger.info(f'Обработка файла: {file_name} ({file_size} байт)')
            try:
                file_content = await FileProcessor.extract_text_from_file(message.document, self.bot)
                logger.info(f'Извлечено {len(file_content)} символов из файла {file_name}')
            except ValueError as e:
                logger.error(f'Ошибка обработки файла {file_name}: {e}')
                await message.answer(f'Ошибка при обработке файла: {e}')
                return

        user_query = message.text
        full_query = f'{user_query}\n\nКонтекст из файла:\n{file_content}' if file_content else user_query

        chat_context = ChatContextManager()
        chat_context.add_message(user_id, topic_name, 'user', full_query)
        messages = chat_context.get_messages_for_api(user_id, topic_name)
        logger.info(f'Подготовлено {len(messages)} сообщений для API, размер запроса: {len(full_query)} символов')

        model = Models[model_name].value
        model_api = ModelAPI(model())

        try:
            await self.bot.send_chat_action(chat_id=user_id, action='typing')
            logger.info(f'Отправка запроса к {model_name} для пользователя {user_id}')

            response = await model_api.get_response(messages)
            logger.info(f'Получен ответ от {model_name}, длина: {len(response)} символов')

            chat_context.add_message(user_id, topic_name, 'assistant', response)
            escaped_response = self._escape_markdown(response)

            await message.answer(escaped_response, parse_mode='MarkdownV2')
            await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
            await UserStates.ASKING_CONTINUE.set()
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
        dp.register_message_handler(self.process, content_types=['text', 'document'], state=UserStates.CONTINUE_DIALOG)


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

        logger.info(f'Администратор {user_id} выбрал промпт {topic_name} для обновления')
        await state.update_data(chosen_prompt=topic_name)

        await callback_query.message.delete()
        await callback_query.message.answer('Загрузите TXT-файл с новым содержимым промпта:')
        await AdminStates.UPLOADING_PROMPT.set()
        logger.info(f'Пользователь {user_id} переведен в режим загрузки промпта')
        await callback_query.answer()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('prompt_'),
            state=AdminStates.CHOOSING_PROMPT,
        )


class AdminUploadPromptHandler(BaseScenario):
    """Обработка загрузки файла с новым промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']

        logger.info(f'Получен файл для обновления промпта {topic_name} от администратора {user_id}')

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
        logger.debug(f'Размер содержимого промпта: {len(file_content)} символов')

        try:
            system_prompts = SystemPrompts()
            system_prompts.set_prompt(SystemPrompt[topic_name.upper()], file_content)
            logger.info(f'Промпт {topic_name} успешно обновлен администратором {user_id}')

            TopicKeyboard.reset_instance()
            AdminPromptKeyboard.reset_instance()
            logger.debug('Клавиатуры сброшены')

            await message.answer(f"Промпт для темы '{Topics[topic_name].value}' успешно обновлен!")
        except KeyError:
            logger.error(f'Ошибка: тема {topic_name} не найдена')
            await message.answer(f"Ошибка: тема '{topic_name}' не найдена.")
        except Exception as e:
            logger.error(f'Ошибка при обновлении промпта: {e}', exc_info=True)
            await message.answer(f'Произошла ошибка при обновлении промпта: {e}')

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


class AdminUploadPromptTextHandler(BaseScenario):
    """Обработка ввода текста вместо загрузки файла."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_id = message.from_user.id
        logger.warning(f'Администратор {user_id} отправил текст вместо файла при обновлении промпта')
        await message.answer('Пожалуйста, загрузите TXT-файл с новым содержимым промпта.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.UPLOADING_PROMPT,
        )


class AdminNewPromptHandler(BaseScenario):
    """Обработка команды администратора для создания нового топика и промпта."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id
        logger.info(f'Запрос на создание нового промпта от пользователя {user_id}')

        if user_id not in config.ADMIN_USERS:
            logger.warning(f'Отказано в доступе пользователю {user_id} - не является администратором')
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer(
            'Вы начали процесс добавления нового топика и системного промпта.\n\n'
            'Шаг 1: Введите техническое имя нового топика (на английском, без пробелов):',
        )
        await AdminStates.NEW_PROMPT_NAME.set()
        logger.info(f'Администратор {user_id} начал процесс создания нового промпта')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['new_prompt'], state='*')


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

        logger.info(f'Получен файл для нового промпта {prompt_name} от администратора {user_id}')

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
        logger.debug(f'Размер содержимого нового промпта: {len(file_content)} символов')

        try:
            system_prompts = SystemPrompts()
            system_prompts.add_new_prompt(prompt_name, display_name, file_content)
            logger.info(f'Новый промпт {prompt_name} ({display_name}) успешно добавлен администратором {user_id}')

            TopicKeyboard.reset_instance()
            AdminPromptKeyboard.reset_instance()
            logger.debug('Клавиатуры сброшены')

            await message.answer(f"Системный промпт для топика '{display_name}' успешно добавлен!\n")
        except Exception as e:
            logger.error(f'Ошибка при добавлении системного промпта: {e}', exc_info=True)
            await message.answer(
                f'Произошла ошибка при добавлении системного промпта.\nСообщение об ошибке уже отправлено разработчику.',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_ID,
                text=f'Произошла ошибка при добавлении системного промпта:{str(e)}',
                parse_mode='MarkdownV2',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()
        logger.info(f'Администратор {user_id} вернулся в режим выбора темы')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.NEW_PROMPT_UPLOAD,
        )


class AdminNewPromptTextHandler(BaseScenario):
    """Обработка ввода текста вместо загрузки файла."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        await message.answer('Пожалуйста, загрузите TXT-файл с системным промптом.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.NEW_PROMPT_UPLOAD,
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
            '/update_prompts - Обновление существующего системного промпта. Позволяет выбрать тему и загрузить '
            'новый TXT-файл с содержимым промпта.\n\n'
            '/new_prompt - Создание нового топика и системного промпта. Проведет через процесс создания '
            'нового топика с указанием технического имени, отображаемого названия и загрузкой файла промпта.\n\n'
            '/load_prompts - Выгрузка всех системных промптов в виде TXT-файлов для просмотра или редактирования.\n\n'
            '/start - Перезапуск бота и возврат к выбору темы анализа.'
        )

        await message.answer(self._escape_markdown(help_text), parse_mode='MarkdownV2')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['help'], state='*')


class BotManager:
    scenarios: Dict[str, BaseScenario] = {}

    main_scenario = {
        'access': Access,
        'start': StartHandler,
        'choose_topic': ProcessingChooseTopicCallback,
        'choose_model': ProcessingChooseModelCallback,
        'enter_prompt': ProcessingEnterPromptHandler,
        'continue_dialog': ContinueDialogHandler,
        'continue_callback': ProcessingContinueCallback,
    }

    admins_update_system_prompts_scenario = {
        'update_prompts': AdminUpdatePromptsHandler,
        'choose_prompt': AdminChoosePromptCallback,
        'upload_prompt': AdminUploadPromptHandler,
        'upload_prompt_text': AdminUploadPromptTextHandler,
    }

    admin_new_system_prompts_scenario = {
        'new_prompt': AdminNewPromptHandler,
        'new_prompt_name': AdminNewPromptNameHandler,
        'new_prompt_display': AdminNewPromptDisplayHandler,
        'new_prompt_upload': AdminNewPromptUploadHandler,
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
