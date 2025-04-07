from collections import namedtuple
from typing import List, Tuple, Union, Dict, Type

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

Button = namedtuple('Button', ['text', 'callback'])


class InlineKeyboardBuilder:
    def __init__(self) -> None:
        self.keyboard = InlineKeyboardMarkup()

    def add_button(self, button: Button) -> None:
        btn = InlineKeyboardButton(button.text, callback_data=button.callback)
        self.keyboard.row(btn)

    def add_row_buttons(self, buttons: List[Button]) -> None:
        btns = [InlineKeyboardButton(btn.text, callback_data=btn.callback) for btn in buttons]
        self.keyboard.row(*btns)


class Keyboard:
    """Базовый класс для создания клавиатур."""

    _buttons: Tuple[Union[Button, List[Button]], ...] = ()

    @classmethod
    def get_buttons(cls) -> Tuple[Union[Button, List[Button]], ...]:
        """Возвращает кнопки для клавиатуры."""
        return cls._buttons

    @classmethod
    def _build_keyboard(cls, buttons) -> InlineKeyboardMarkup:
        """Строит клавиатуру на основе кнопок."""
        builder = InlineKeyboardBuilder()
        for btn in buttons:
            if isinstance(btn, list):
                builder.add_row_buttons(btn)
            else:
                builder.add_button(btn)
        return builder.keyboard

    def __new__(cls) -> InlineKeyboardMarkup:
        buttons = cls.get_buttons()
        return cls._build_keyboard(buttons)


class DynamicKeyboard(Keyboard):
    """Базовый класс для клавиатур с динамическими кнопками."""

    _instance = None
    _registry: Dict[str, Type['DynamicKeyboard']] = {}

    def __init_subclass__(cls, **kwargs):
        """Регистрация подклассов DynamicKeyboard в реестре."""
        super().__init_subclass__(**kwargs)
        DynamicKeyboard._registry[cls.__name__] = cls

    @classmethod
    def get_buttons(cls) -> Tuple[Button, ...]:
        """Переопределяется в дочерних классах для генерации динамических кнопок."""
        return cls._buttons

    @classmethod
    def reset_instance(cls):
        """Сбрасывает кэшированный экземпляр клавиатуры."""
        cls._instance = None

    @classmethod
    def reset_all_keyboards(cls):
        """Сбрасывает кэш всех динамических клавиатур."""
        for keyboard_cls in cls._registry.values():
            keyboard_cls.reset_instance()

    def __new__(cls) -> InlineKeyboardMarkup:
        if cls._instance is None:
            buttons = cls.get_buttons()
            cls._instance = cls._build_keyboard(buttons)
        return cls._instance
