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
    _buttons: Tuple[Union[Button, List[Button]], ...]

    def __new__(cls) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        for btn in cls._buttons:
            if isinstance(btn, list):
                builder.add_row_buttons(btn)
            else:
                builder.add_button(btn)
        return builder.keyboard
