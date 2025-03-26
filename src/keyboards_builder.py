from collections import namedtuple
from typing import List, Tuple, Union

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

    def __new__(cls) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()

        buttons = cls.get_buttons()

        for btn in buttons:
            if isinstance(btn, list):
                builder.add_row_buttons(btn)
            else:
                builder.add_button(btn)
        return builder.keyboard


class DynamicKeyboard(Keyboard):
    """Базовый класс для клавиатур с динамическими кнопками."""

    _instance = None

    @classmethod
    def get_buttons(cls) -> Tuple[Union[Button, List[Button]], ...]:
        """Переопределяется в дочерних классах для генерации динамических кнопок."""
        return cls._buttons

    @classmethod
    def reset_instance(cls):
        """Сбрасывает кэшированный экземпляр клавиатуры."""
        cls._instance = None

    def __new__(cls) -> InlineKeyboardMarkup:
        cls._instance = None

        builder = InlineKeyboardBuilder()

        buttons = cls.get_buttons()

        for btn in buttons:
            if isinstance(btn, list):
                builder.add_row_buttons(btn)
            else:
                builder.add_button(btn)

        cls._instance = builder.keyboard
        return cls._instance
