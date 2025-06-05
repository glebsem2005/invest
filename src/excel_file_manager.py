import asyncio
import logging
import time
from pathlib import Path

from openai import AsyncOpenAI

from config import Config
from file_processor import ExcelExtractor

logger = logging.getLogger('bot')
config = Config()

BASE_DIR = Path(__file__).parent.absolute()
STATIC_FILES_DIR = BASE_DIR / 'static_files'
SCOUTING_EXCEL_PATH = STATIC_FILES_DIR / 'scouting_data.xlsx'
SCOUTING_TXT_PATH = STATIC_FILES_DIR / 'scouting_data.txt'


class ExcelFileManager:
    """Синглтон для управления Excel файлом и его vector store."""

    _instance = None
    _file_id = None
    _vector_store_id = config.VECTOR_STORE_ID or None

    def __new__(cls):
        if cls._instance is None:
            logger.info('Создание экземпляра ExcelFileManager (Singleton)')
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            self._initialized = True

    async def _create_vector_store(self) -> None:
        """Создает vector store при инициализации класса."""
        try:
            if self._vector_store_id:
                logger.info(f'Vector store уже существует с ID: {self._vector_store_id}')
                return

            vector_store = await self.client.vector_stores.create(name='Excel Data Store')
            self._vector_store_id = vector_store.id
            logger.info(f'Создан vector store с ID: {self._vector_store_id}')
        except Exception as e:
            logger.error(f'Ошибка при создании vector store: {e}')
            raise ValueError(f'Не удалось создать vector store: {e}')

    @property
    def file_id(self) -> str:
        """Возвращает текущий vector store id."""
        return self._vector_store_id

    async def upload_file(self) -> None:
        """Загружает файл в OpenAI и добавляет его в существующий vector store."""
        try:
            if not self._vector_store_id:
                await self._create_vector_store()

            if not SCOUTING_TXT_PATH.exists():
                logger.error('TXT файл не найден. Сначала обновите Excel файл.')
                raise ValueError('TXT файл не найден. Сначала обновите Excel файл.')

            existing_files = await self.client.vector_stores.files.list(vector_store_id=self._vector_store_id)
            logger.debug(f'Найдено файлов в векторном хранилище: {existing_files}')
            
            if existing_files.data:
                self._file_id = existing_files.data[0].id
                logger.info(f'Найден существующий файл в vector store с ID: {self._file_id}')
                await self.delete_file()
                return

            with open(SCOUTING_TXT_PATH, 'rb') as f:
                file_response = await self.client.files.create(
                    file=f,
                    purpose='assistants',
                )
                self._file_id = file_response.id
                logger.info(f'TXT файл загружен в OpenAI, file_id: {self._file_id}')

            await self.client.vector_stores.files.create(
                vector_store_id=self._vector_store_id,
                file_id=self._file_id,
            )
            logger.info(f'Файл {self._file_id} добавлен в vector store {self._vector_store_id}')

        except Exception as e:
            logger.error(f'Ошибка при загрузке файла в OpenAI: {e}')
            raise ValueError(f'Не удалось загрузить файл в OpenAI: {e}')

    async def check_status_file(self) -> bool:
        """Проверяет статус файла в vector store каждые 5 секунд до готовности."""

        MAX_WAIT_TIME = 60 * 5
        start_time = time.time()
        
        while True:
            try:
                if time.time() - start_time > MAX_WAIT_TIME:
                    logger.error('Превышено максимальное время ожидания обработки файла (5 минут)')
                    return False
                
                result = await self.client.vector_stores.files.list(vector_store_id=self._vector_store_id)
                
                if not result.data:
                    logger.warning('Файл не найден в vector store')
                    return False
                
                file_status = result.data[0].status
                logger.debug(f'Статус файла: {file_status}')
                
                if file_status == 'completed':
                    logger.info('Файл успешно обработан и готов к использованию')
                    return True
                elif file_status == 'failed':
                    logger.error('Обработка файла завершилась с ошибкой')
                    return False
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f'Ошибка при проверке статуса файла: {e}')
                return False

    async def delete_file(self) -> None:
        """Удаляет файл из vector store."""
        if self._file_id:
            try:
                await self.client.vector_stores.files.delete(
                    vector_store_id=self._vector_store_id,
                    file_id=self._file_id,
                )
                self._file_id = None
                logger.info('Файл удален из OpenAI и vector store')
            except Exception as e:
                logger.error(f'Ошибка при удалении файла из OpenAI: {e}', exc_info=True)

    async def cleanup(self) -> None:
        """Полная очистка ресурсов, включая vector store."""
        await self.delete_file()
        if self._vector_store_id:
            try:
                await self.client.beta.vector_stores.delete(vector_store_id=self._vector_store_id)
                self._vector_store_id = None
                logger.info('Vector store удален из OpenAI')
            except Exception as e:
                logger.error(f'Ошибка при удалении vector store из OpenAI: {e}')

    async def update_excel_file(self, content: bytes) -> None:
        """Обновляет содержимое excel файла для скаутинга и создает TXT версию."""
        try:
            with open(SCOUTING_EXCEL_PATH, 'wb') as f:
                f.write(content)
            logger.info(f'Excel файл скаутинга: {SCOUTING_EXCEL_PATH} успешно обновлен.')

            txt_content = await ExcelExtractor.extract_text_from_path(str(SCOUTING_EXCEL_PATH))
            with open(SCOUTING_TXT_PATH, 'w', encoding='utf-8') as f:
                f.write(txt_content)
            logger.info(f'TXT файл скаутинга: {SCOUTING_TXT_PATH} успешно обновлен.')
        except Exception as e:
            logger.error(f'Ошибка при обновлении файлов: {e}')
            raise ValueError(f'Не удалось обновить файлы: {e}')
