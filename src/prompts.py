from enum import Enum
from pathlib import Path
import logging

from models_api import ChatGPTStrategy, DeepseekStrategy, GigaChatStrategy, PerplexityStrategy

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.absolute()
DEFAULT_PROMPTS_DIR = BASE_DIR / 'default_prompts'


class DynamicEnum(Enum):
    @classmethod
    def add_member(cls, name: str, value: str):
        """Динамически добавляет новый элемент в Enum."""
        cls._value2member_map_[value] = cls._member_map_[name] = member = object.__new__(cls)
        member._name_ = name
        member._value_ = value
        return member


class Topics(DynamicEnum):
    investment = 'Анализ инвестиционной возможности'
    competitors = 'Анализ стратегии конкурентов'
    market = 'Анализ рынка и трендов'


class Models(Enum):
    chatgpt = ChatGPTStrategy
    perplexity = PerplexityStrategy
    deepseek = DeepseekStrategy
    gigachat = GigaChatStrategy


class SystemPrompt(DynamicEnum):
    INVESTMENT = 'investment'
    COMPETITORS = 'competitors'
    MARKET = 'market'


class SystemPrompts:
    """Класс для работы с системными промптами. Получение, обновление промптов."""

    def __init__(self) -> None:
        self.prompts = {}
        logger.info(f'Инициализация SystemPrompts, директория промптов: {DEFAULT_PROMPTS_DIR}')
        self._load_default_prompts()

    def _load_default_prompts(self) -> None:
        logger.info(f'Загрузка дефолтных промптов из {DEFAULT_PROMPTS_DIR}')
        for prompt_type in SystemPrompt:
            filename = DEFAULT_PROMPTS_DIR / f'{prompt_type.value}.txt'
            logger.debug(f'Загрузка промпта {prompt_type.name} из файла {filename}')
            if not filename.exists():
                logger.error(f'Файл промпта не найден: {filename}')
                raise ValueError(f'Файла для дефолтного системного промпта {filename} не существует.')
            self.prompts[prompt_type] = self.read_file(filename)
            logger.debug(f'Загружен промпт {prompt_type.name}, размер: {len(self.prompts[prompt_type])} символов')
        logger.info(f'Загружено {len(self.prompts)} промптов')

    def read_file(self, filename: Path) -> str:
        logger.debug(f'Чтение файла: {filename}')
        try:
            with open(str(filename), 'r', encoding='utf-8') as f:
                file_content = f.read()
            logger.debug(f'Успешно прочитан файл {filename}, размер: {len(file_content)} символов')
            return file_content
        except Exception as e:
            logger.error(f'Ошибка при чтении файла {filename}: {e}', exc_info=True)
            raise ValueError(f'Не удалось прочитать файл {filename}: {e}')

    def update_or_create_file(self, content: str, filename: Path) -> None:
        logger.debug(f'Обновление/создание файла: {filename}, размер контента: {len(content)} символов')
        try:
            filename.parent.mkdir(parents=True, exist_ok=True)
            with open(str(filename), 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f'Успешно записан файл: {filename}')
        except Exception as e:
            logger.error(f'Ошибка при записи в файл {filename}: {e}', exc_info=True)
            raise ValueError(f'Не удалось записать в файл {filename}: {e}')

    def get_prompt(self, prompt_type: SystemPrompt) -> str:
        logger.debug(f'Запрос промпта: {prompt_type.name}')
        prompt = self.prompts.get(prompt_type)
        if not prompt:
            filename = DEFAULT_PROMPTS_DIR / f'{prompt_type.value}.txt'
            logger.debug(f'Промпт не найден в словаре, проверяем файл: {filename}')
            if filename.exists():
                prompt = self.read_file(filename)
                self.prompts[prompt_type] = prompt
                logger.debug(f'Загружен промпт из файла: {prompt_type.name}')
            else:
                logger.error(f'Промпт не найден: {prompt_type.name}')
                raise ValueError(f'Промпта для {prompt_type} не найдено.')
        return prompt

    def update_prompt(self, prompt_type: SystemPrompt, content: str) -> None:
        """Обновляет существующий промпт."""
        logger.info(f'Обновление промпта: {prompt_type.name}, размер: {len(content)} символов')
        self.prompts[prompt_type] = content
        filename = DEFAULT_PROMPTS_DIR / f'{prompt_type.value}.txt'
        self.update_or_create_file(content, filename)
        logger.info(f'Промпт {prompt_type.name} успешно обновлен')

    def add_new_prompt(self, name: str, display_name: str, content: str) -> None:
        """Добавляет новый промпт."""
        logger.info(f"Добавление нового промпта: {name} ('{display_name}'), размер: {len(content)} символов")
        if name in Topics.__members__:
            logger.error(f"Промпт с именем '{name}' уже существует")
            raise ValueError(f"Промпт с именем '{name}' уже существует.")

        try:
            Topics.add_member(name, display_name)
            SystemPrompt.add_member(name.upper(), name)
            logger.debug(f'Добавлены элементы в Topics и SystemPrompt: {name}')

            filename = DEFAULT_PROMPTS_DIR / f'{name}.txt'
            self.update_or_create_file(content, filename)

            self.prompts[SystemPrompt[name.upper()]] = content
            logger.info(f"Новый промпт '{name}' успешно добавлен")
        except Exception as e:
            logger.error(f"Ошибка при добавлении промпта '{name}': {e}", exc_info=True)
            raise ValueError(f"Не удалось добавить промпт '{name}': {e}")

    def set_prompt(self, prompt_type: SystemPrompt, content: str) -> None:
        """Устанавливает содержимое промпта."""
        logger.debug(f'Установка содержимого промпта {prompt_type.name}')
        self.update_prompt(prompt_type, content)
