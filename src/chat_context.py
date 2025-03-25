from typing import Dict, List, Literal, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChatMessage:
    """Класс для хранения сообщения в чате."""

    role: Literal['system', 'user', 'assistant']
    content: str
    timestamp: datetime = datetime.now()

    def to_dict(self) -> dict:
        """Преобразует сообщение в словарь для API."""
        return {'role': self.role, 'content': self.content}


class ChatHistory:
    """Класс для хранения истории чата (Memento)."""

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.messages: List[ChatMessage] = []
        self.is_active = True

    def add_message(self, role: str, content: str) -> None:
        """Добавляет новое сообщение в историю."""
        message = ChatMessage(role=role, content=content)
        self.messages.append(message)

    def get_messages_for_api(self) -> List[dict]:
        """Возвращает сообщения в формате для API."""
        return [msg.to_dict() for msg in self.messages]

    def mark_as_inactive(self) -> None:
        """Помечает чат как неактивный."""
        self.is_active = False


class ChatContextManager:
    """Менеджер контекста чата (Singleton)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Инициализация менеджера."""
        self._contexts: Dict[int, Dict[str, ChatHistory]] = {}

    def start_new_chat(self, user_id: int, topic: str, system_prompt: str) -> None:
        """Начинает новый чат для пользователя по заданной теме."""
        if user_id not in self._contexts:
            self._contexts[user_id] = {}

        chat_history = ChatHistory(topic)

        chat_history.add_message('system', system_prompt)

        self._contexts[user_id][topic] = chat_history

    def add_message(self, user_id: int, topic: str, role: str, content: str) -> None:
        """Добавляет сообщение в историю чата."""
        if not self._check_chat_exists(user_id, topic):
            raise ValueError(f'Chat for user {user_id} and topic {topic} not found')

        chat_history = self._contexts[user_id][topic]
        if not chat_history.is_active:
            raise ValueError(f'Chat for user {user_id} and topic {topic} is not active')

        chat_history.add_message(role, content)

    def get_chat_history(self, user_id: int, topic: str) -> Optional[ChatHistory]:
        """Возвращает историю чата пользователя по теме."""
        if not self._check_chat_exists(user_id, topic):
            return None
        return self._contexts[user_id][topic]

    def get_messages_for_api(self, user_id: int, topic: str) -> List[dict]:
        """Возвращает сообщения в формате для API."""
        chat_history = self.get_chat_history(user_id, topic)
        if not chat_history:
            return []
        return chat_history.get_messages_for_api()

    def end_chat(self, user_id: int, topic: str) -> None:
        """Завершает чат пользователя по теме."""
        if self._check_chat_exists(user_id, topic):
            self._contexts[user_id][topic].mark_as_inactive()

    def _check_chat_exists(self, user_id: int, topic: str) -> bool:
        """Проверяет существование чата."""
        return user_id in self._contexts and topic in self._contexts[user_id]

    def cleanup_inactive_chats(self) -> None:
        """Очищает неактивные чаты для экономии памяти."""
        for user_id in list(self._contexts.keys()):
            for topic in list(self._contexts[user_id].keys()):
                if not self._contexts[user_id][topic].is_active:
                    del self._contexts[user_id][topic]
            if not self._contexts[user_id]:
                del self._contexts[user_id]
