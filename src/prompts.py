from enum import Enum
from pathlib import Path

from models_api import ChatGPTStrategy, DeepseekStrategy, GigaChatStrategy, PerplexityStrategy

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
        self._load_default_prompts()

    def _load_default_prompts(self) -> None:
        for prompt_type in SystemPrompt:
            filename = DEFAULT_PROMPTS_DIR / f'{prompt_type.value}.txt'
            if not filename.exists():
                raise ValueError(f'Файла для дефолтного системного промпта {filename} не существует.')
            self.prompts[prompt_type] = self.read_file(filename)

    def read_file(self, filename: Path) -> str:
        with open(str(filename), 'r', encoding='utf-8') as f:
            file_content = f.read()
        return file_content

    def update_or_create_file(self, content: str, filename: Path) -> None:
        filename.parent.mkdir(parents=True, exist_ok=True)

        with open(str(filename), 'w', encoding='utf-8') as f:
            f.write(content)

    def get_prompt(self, prompt_type: SystemPrompt) -> str:
        prompt = self.prompts.get(prompt_type)
        if not prompt:
            raise ValueError(f'Промпта для {prompt_type} не найдено.')
        return prompt

    def set_prompt(self, prompt_type: SystemPrompt, content: str) -> None:
        self.prompts[prompt_type] = content
        filename = DEFAULT_PROMPTS_DIR / f'{prompt_type.value}.txt'
        self.update_or_create_file(content, filename)

    def add_new_prompt(self, name: str, display_name: str, content: str) -> None:
        """Добавляет новый промпт."""
        if name in Topics.__members__:
            raise ValueError(f"Промпт с именем '{name}' уже существует.")

        Topics.add_member(name, display_name)
        SystemPrompt.add_member(name.upper(), name)

        filename = DEFAULT_PROMPTS_DIR / f'{name}.txt'
        self.update_or_create_file(content, filename)

        self.prompts[SystemPrompt[name.upper()]] = content
