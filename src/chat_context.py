from typing import Dict, List, Literal, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

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
        logger.debug(f"Создана новая история чата по теме '{topic}'")

    def add_message(self, role: str, content: str) -> None:
        """Добавляет новое сообщение в историю."""
        message = ChatMessage(role=role, content=content)
        self.messages.append(message)
        logger.debug(f"Добавлено сообщение с ролью '{role}' в историю чата '{self.topic}', размер: {len(content)} символов")

    def get_messages_for_api(self) -> List[dict]:
        """Возвращает сообщения в формате для API."""
        messages = [msg.to_dict() for msg in self.messages]
        logger.debug(f"Получено {len(messages)} сообщений из истории чата '{self.topic}' для API")
        return messages

    def mark_as_inactive(self) -> None:
        """Помечает чат как неактивный."""
        self.is_active = False
        logger.debug(f"История чата '{self.topic}' помечена как неактивная")


class ChatContextManager:
    """Менеджер контекста чата (Singleton)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            logger.info("Создание экземпляра ChatContextManager (Singleton)")
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Инициализация менеджера."""
        self._contexts: Dict[int, Dict[str, ChatHistory]] = {}
        logger.info("Инициализирован менеджер контекста чата")

    def start_new_chat(self, user_id: int, topic: str, system_prompt: str) -> None:
        """Начинает новый чат для пользователя по заданной теме."""
        logger.info(f"Создание нового чата для пользователя {user_id} по теме '{topic}'")
        self.end_active_chats(user_id)

        if user_id not in self._contexts:
            self._contexts[user_id] = {}
            logger.debug(f"Создан новый контекст для пользователя {user_id}")

        chat_history = ChatHistory(topic)
        chat_history.add_message('system', system_prompt)
        self._contexts[user_id][topic] = chat_history
        logger.info(f"Чат для пользователя {user_id} по теме '{topic}' создан с системным промптом размером {len(system_prompt)} символов")

    def end_active_chats(self, user_id: int) -> None:
        """Завершает все активные чаты пользователя."""
        if user_id in self._contexts:
            active_chats = [topic for topic, history in self._contexts[user_id].items() if history.is_active]
            if active_chats:
                logger.info(f"Завершение активных чатов пользователя {user_id}: {', '.join(active_chats)}")
                for topic, history in self._contexts[user_id].items():
                    if history.is_active:
                        history.mark_as_inactive()
            else:
                logger.debug(f"У пользователя {user_id} нет активных чатов для завершения")
        else:
            logger.debug(f"Пользователь {user_id} не имеет контекстов чатов")

    def cleanup_user_context(self, user_id: int) -> None:
        """Очищает неактивные чаты конкретного пользователя."""
        if user_id in self._contexts:
            inactive_topics = [topic for topic, history in self._contexts[user_id].items() if not history.is_active]
            
            if inactive_topics:
                logger.info(f"Очистка неактивных чатов пользователя {user_id}: {', '.join(inactive_topics)}")
                for topic in inactive_topics:
                    del self._contexts[user_id][topic]
                    logger.debug(f"Удален чат '{topic}' для пользователя {user_id}")

                if not self._contexts[user_id]:
                    del self._contexts[user_id]
                    logger.debug(f"Удален пустой контекст пользователя {user_id}")
            else:
                logger.debug(f"У пользователя {user_id} нет неактивных чатов для очистки")
        else:
            logger.debug(f"Пользователь {user_id} не имеет контекстов для очистки")

    def add_message(self, user_id: int, topic: str, role: str, content: str) -> None:
        """Добавляет сообщение в историю чата."""
        if not self._check_chat_exists(user_id, topic):
            error_msg = f'Чат для пользователя {user_id} и темы {topic} не найден'
            logger.error(error_msg)
            raise ValueError(error_msg)

        chat_history = self._contexts[user_id][topic]
        if not chat_history.is_active:
            error_msg = f'Чат для пользователя {user_id} и темы {topic} не активен'
            logger.error(error_msg)
            raise ValueError(error_msg)

        chat_history.add_message(role, content)
        logger.info(f"Добавлено сообщение с ролью '{role}' для пользователя {user_id} по теме '{topic}', размер: {len(content)} символов")

    def get_chat_history(self, user_id: int, topic: str) -> Optional[ChatHistory]:
        """Возвращает историю чата пользователя по теме."""
        if not self._check_chat_exists(user_id, topic):
            logger.warning(f"Запрошена несуществующая история чата: пользователь {user_id}, тема '{topic}'")
            return None
        logger.debug(f"Получена история чата для пользователя {user_id} по теме '{topic}'")
        return self._contexts[user_id][topic]

    def get_messages_for_api(self, user_id: int, topic: str) -> List[dict]:
        """Возвращает сообщения в формате для API."""
        chat_history = self.get_chat_history(user_id, topic)
        if not chat_history:
            logger.warning(f"Нет сообщений для API: пользователь {user_id}, тема '{topic}'")
            return []
        
        messages = chat_history.get_messages_for_api()
        total_size = sum(len(msg['content']) for msg in messages)
        logger.info(f"Получено {len(messages)} сообщений для API: пользователь {user_id}, тема '{topic}', общий размер: {total_size} символов")
        return messages

    def end_chat(self, user_id: int, topic: str) -> None:
        """Завершает чат пользователя по теме."""
        if self._check_chat_exists(user_id, topic):
            logger.info(f"Завершение чата для пользователя {user_id} по теме '{topic}'")
            self._contexts[user_id][topic].mark_as_inactive()
        else:
            logger.warning(f"Попытка завершить несуществующий чат: пользователь {user_id}, тема '{topic}'")

    def _check_chat_exists(self, user_id: int, topic: str) -> bool:
        """Проверяет существование чата."""
        exists = user_id in self._contexts and topic in self._contexts[user_id]
        if not exists:
            logger.debug(f"Чат не существует: пользователь {user_id}, тема '{topic}'")
        return exists
