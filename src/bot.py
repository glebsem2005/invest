from abc import ABC, abstractmethod
import logging
from typing import Dict, Any
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from access_middleware import AccessMiddleware
from keyboards_builder import Button, Keyboard
from logger import Logger
from config import Config
from models_api import ModelAPI
from prompts import DEFAULT_PROMPTS_DIR, Models, SystemPrompt, Topics, SystemPrompts

Logger()
logger = logging.getLogger('bot')


class UserStates(StatesGroup):
    # START = State()  # Начальное состояние
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


class TopicKeyboard(Keyboard):
    """Клавиатура для выбора темы."""

    @property
    def _buttons(self):
        # Динамически получаем все доступные топики
        return (Button(topic.value, f'topic_{topic.name}') for topic in Topics)


class ModelKeyboard(Keyboard):
    """Клавиатура для выбора модели."""

    _buttons = (Button(model.name, f'model_{model.name}') for model in Models)


class ContinueKeyboard(Keyboard):
    """Клавиатура для продолжения диалога."""

    _buttons = ([Button('Да', 'continue_yes'), Button('Нет', 'continue_no')],)


class AuthorizeKeyboard(Keyboard):
    """Клавиатура для авторизации."""

    _buttons = [Button('Авторизовать', 'authorize_yes'), Button('Отклонить', 'authorize_no')]


class AdminPromptKeyboard(Keyboard):
    """Клавиатура для выбора промпта для обновления."""

    @property
    def _buttons(self):
        # Динамически получаем все доступные топики
        return (Button(topic.value, f'prompt_{topic.name}') for topic in Topics)


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


class Access(BaseScenario):
    """Обработка получения доступа к боту."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> NotImplemented:
        raise NotImplementedError()

    async def authorize_process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        msg = 'Доступ получен.'
        await bot.send_message(chat_id=user_id, text=msg)
        admin_msg = f'Пользователь {user_id} успешно авторизован.'
        await callback_query.message.reply(admin_msg)

    async def decline_process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        user_id = callback_query.from_user.id
        msg = 'Доступ запрещен.'
        await bot.send_message(chat_id=user_id, text=msg)
        admin_msg = f'Пользователь {user_id} отклонен.'
        await callback_query.message.reply(admin_msg)

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.authorize_process,
            lambda c: c.data == 'authorize_yes',
            state=UserStates.ACCESS,
        )
        dp.register_callback_query_handler(
            self.decline_process,
            lambda c: c.data == 'authorize_no',
            state=UserStates.ACCESS,
        )


class StartHandler(BaseScenario):
    """Обработка /start команды."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id
        if user_id not in config.AUTHORIZED_USERS_IDS:
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
        topic_callback = callback_query.data
        topic_name = topic_callback.replace('topic_', '')

        selected_topic = next(filter(lambda topic: topic.name == topic_name, Topics), None)

        await state.update_data(chosen_topic=selected_topic.name, topic_value=selected_topic.value)
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
        model_callback = callback_query.data
        model_name = model_callback.replace('model_', '')

        selected_model = Models[model_name]

        await state.update_data(chosen_model=selected_model.name, model_display=selected_model.value)
        await callback_query.message.answer('Какой Ваш запрос? Вы также можете прикрепить файл (PDF, Word, PPT).')
        await UserStates.ENTERING_PROMPT.set()
        await callback_query.answer()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data.startswith('model_'),
            state=UserStates.CHOOSING_MODEL,
        )


class ProcessingEnterPromptHandler(BaseScenario):
    """Обработка ввода запроса и файлов."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_data = await state.get_data()
        model_class = Models[user_data['chosen_model']].value
        topic = Topics[user_data['chosen_topic']]

        system_prompts = SystemPrompts()
        system_prompt = system_prompts.get_prompt(SystemPrompt[topic.name])

        file_content = ''
        if message.document:
            file_content = await self.process_file(message.document)

        full_prompt = f'{system_prompt}\n\nКонтекст из файла:\n{file_content}\n\nЗапрос пользователя:\n{message.text}'

        model_api = ModelAPI(model_class())
        response = await model_api.send_message(full_prompt)

        await message.answer(response)
        await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
        await UserStates.ASKING_CONTINUE.set()

    async def process_file(self, document: types.Document) -> str:  # FIXME
        file = await document.download()
        return 'Текст из файла'

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text', 'document'],
            state=UserStates.ENTERING_PROMPT,
        )


class ProcessingContinueCallback(BaseScenario):
    """Обработка ответа на вопрос о продолжении диалога."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        if callback_query.data == 'continue_yes':
            await callback_query.message.answer('Задайте ваш следующий вопрос:')
            await UserStates.CONTINUE_DIALOG.set()
        else:
            await callback_query.message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
            await UserStates.CHOOSING_TOPIC.set()

        await callback_query.answer()

    def register(self, dp: Dispatcher) -> None:
        dp.register_callback_query_handler(
            self.process,
            lambda c: c.data in ['continue_yes', 'continue_no'],
            state=UserStates.ASKING_CONTINUE,
        )


class ContinueDialogHandler(BaseScenario):
    """Обработка продолжения диалога с той же моделью и темой."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_data = await state.get_data()
        model_class = Models[user_data['chosen_model']].value
        topic = Topics[user_data['chosen_topic']]

        system_prompts = SystemPrompts()
        system_prompt = system_prompts.get_prompt(SystemPrompt[topic.name])

        await message.answer('Обрабатываю ваш запрос...')

        file_content = ''
        if message.document:
            file_content = await FileProcessor.extract_text_from_file(message.document, self.bot)

        full_prompt = f'{system_prompt}\n\nКонтекст из файла:\n{file_content}\n\nЗапрос пользователя:\n{message.text}'

        model_api = ModelAPI(model_class())
        response = await model_api.send_message(full_prompt)

        await message.answer(response)
        await message.answer('Остались ли у Вас вопросы?', reply_markup=ContinueKeyboard())
        await UserStates.ASKING_CONTINUE.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, content_types=['text', 'document'], state=UserStates.CONTINUE_DIALOG)


class AdminUpdatePromptsHandler(BaseScenario):
    """Обработка команды администратора для обновления системных промптов."""

    async def process(self, message: types.Message, **kwargs) -> None:
        user_id = message.from_user.id

        if user_id not in config.ADMIN_USERS:
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer('Выберите тему промпта для обновления:', reply_markup=AdminPromptKeyboard())
        await AdminStates.CHOOSING_PROMPT.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            commands=['update_prompts'],
            state='*',
        )


class AdminChoosePromptCallback(BaseScenario):
    """Обработка выбора промпта для обновления."""

    async def process(self, callback_query: types.CallbackQuery, state: FSMContext, **kwargs) -> None:
        prompt_callback = callback_query.data
        topic_name = prompt_callback.replace('prompt_', '')

        system_prompts = SystemPrompts()
        current_prompt = system_prompts.get_prompt(SystemPrompt[topic_name])

        await state.update_data(chosen_prompt=topic_name)

        await callback_query.message.answer('Загрузите TXT-файл с новым содержимым промпта:')

        await AdminStates.UPLOADING_PROMPT.set()
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
        user_data = await state.get_data()
        topic_name = user_data['chosen_prompt']

        if not message.document or not message.document.file_name.endswith('.txt'):
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        file_id = message.document.file_id
        file = await self.bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await self.bot.download_file(file_path)

        file_content = downloaded_file.read().decode('utf-8')

        system_prompts = SystemPrompts()
        system_prompts.set_prompt(SystemPrompt[topic_name], file_content)

        await message.answer(f"Промпт для темы '{Topics[topic_name].value}' успешно обновлен!")

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['document'],
            state=AdminStates.UPLOADING_PROMPT,
        )


class AdminUploadPromptTextHandler(BaseScenario):
    """Обработка ввода текста вместо загрузки файла."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
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

        if user_id not in config.ADMIN_USERS:
            await message.answer('У вас нет прав для выполнения этой команды.')
            return

        await message.answer(
            'Вы начали процесс добавления нового топика и системного промпта.\n\n'
            'Шаг 1: Введите техническое имя нового топика (на английском, без пробелов):',
        )
        await AdminStates.NEW_PROMPT_NAME.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['new_prompt'], state='*')


class AdminNewPromptNameHandler(BaseScenario):
    """Обработка ввода технического имени нового топика."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        prompt_name = message.text.strip().lower()

        if not prompt_name.isalnum() or not prompt_name.isascii():
            await message.answer('Имя должно содержать только латинские буквы и цифры. Попробуйте еще раз:')
            return

        if prompt_name in Topics.__members__:
            await message.answer(f"Топик с именем '{prompt_name}' уже существует. Введите другое имя:")
            return

        await state.update_data(new_prompt_name=prompt_name)
        await message.answer('Шаг 2: Введите отображаемое название топика (на русском):')
        await AdminStates.NEW_PROMPT_DISPLAY.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.NEW_PROMPT_NAME,
        )


class AdminNewPromptDisplayHandler(BaseScenario):
    """Обработка ввода отображаемого имени нового топика."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        display_name = message.text.strip()

        if not display_name:
            await message.answer('Отображаемое имя не может быть пустым. Введите отображаемое имя:')
            return

        user_data = await state.get_data()
        prompt_name = user_data['new_prompt_name']

        await state.update_data(new_prompt_display=display_name)

        try:
            Topics.add_member(prompt_name, display_name)
            SystemPrompt.add_member(prompt_name.upper(), prompt_name)

            await message.answer(
                f"Топик '{display_name}' успешно создан!\n\n"
                f'Шаг 3: Загрузите TXT-файл с системным промптом для этого топика:'
            )
            await AdminStates.NEW_PROMPT_UPLOAD.set()
        except Exception as e:
            logger.error(f'Ошибка при создании нового топика: {e}')
            await message.answer(
                'Произошла ошибка при создании нового топика.\nСообщение об ошибке уже отправлено разработчику.',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_USER,
                text=f'Произошла ошибка при создании нового топика:{str(e)}',
                parse_mode='MarkdownV2',
            )
            await state.finish()
            await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
            await UserStates.CHOOSING_TOPIC.set()

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(
            self.process,
            content_types=['text'],
            state=AdminStates.NEW_PROMPT_DISPLAY,
        )


class AdminNewPromptUploadHandler(BaseScenario):
    """Обработка загрузки файла с системным промптом."""

    async def process(self, message: types.Message, state: FSMContext, **kwargs) -> None:
        user_data = await state.get_data()
        prompt_name = user_data['new_prompt_name']
        display_name = user_data['new_prompt_display']

        if not message.document or not message.document.file_name.endswith('.txt'):
            await message.answer('Пожалуйста, загрузите файл в формате TXT.')
            return

        file_id = message.document.file_id
        file = await self.bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await self.bot.download_file(file_path)

        file_content = downloaded_file.read().decode('utf-8')

        try:
            system_prompts = SystemPrompts()

            filename = DEFAULT_PROMPTS_DIR / f'{prompt_name}.txt'
            system_prompts.update_or_create_file(file_content, filename)

            system_prompts.prompts[SystemPrompt[prompt_name.upper()]] = file_content

            await message.answer(f"Системный промпт для топика '{display_name}' успешно добавлен!\n")
        except Exception as e:
            logger.error(f'Ошибка при добавлении системного промпта: {e}')
            await message.answer(
                f'Произошла ошибка при добавлении системного промпта.\nСообщение об ошибке уже отправлено разработчику.',
            )
            await self.bot.send_message(
                chat_id=config.OWNER_USER,
                text=f'Произошла ошибка при добавлении системного промпта:{str(e)}',
                parse_mode='MarkdownV2',
            )

        await state.finish()
        await message.answer('Чем я могу вам помочь?', reply_markup=TopicKeyboard())
        await UserStates.CHOOSING_TOPIC.set()

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
                    chat_id=config.OWNER_USER,
                    text=f'Ошибка при выгрузке промпта {prompt_file.name}.\n{e}',
                )

        await message.answer('Выгрузка системных промптов завершена.')

    def register(self, dp: Dispatcher) -> None:
        dp.register_message_handler(self.process, commands=['load_prompts'], state='*')


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

    # Инициализация менеджера сценариев
    BotManager(bot, dp)

    # Запуск бота
    executor.start_polling(dp, skip_updates=True)
