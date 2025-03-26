import os
import logging
from typing import BinaryIO, Dict, Type
from abc import ABC, abstractmethod
from aiogram import Bot
from aiogram.types import Document

logger = logging.getLogger(__name__)


class FileExtractor(ABC):
    """Абстрактный класс для извлечения текста из файлов различных форматов."""

    @abstractmethod
    async def extract_text(self, file: BinaryIO) -> str:
        """Извлекает текст из файла."""
        ...


class PDFExtractor(FileExtractor):
    """Извлечение текста из PDF файлов."""

    async def extract_text(self, file: BinaryIO) -> str:
        try:
            import PyPDF2

            reader = PyPDF2.PdfReader(file)
            text = ''

            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                text += page.extract_text() + '\n\n'

            return text.strip()
        except Exception as e:
            logger.error(f'Ошибка при извлечении текста из PDF: {e}')
            raise ValueError(f'Не удалось извлечь текст из PDF: {e}')


class DocxExtractor(FileExtractor):
    """Извлечение текста из DOCX файлов."""

    async def extract_text(self, file: BinaryIO) -> str:
        try:
            import docx

            doc = docx.Document(file)
            text = ''

            for paragraph in doc.paragraphs:
                text += paragraph.text + '\n'

            return text.strip()
        except Exception as e:
            logger.error(f'Ошибка при извлечении текста из DOCX: {e}')
            raise ValueError(f'Не удалось извлечь текст из DOCX: {e}')


class PPTXExtractor(FileExtractor):
    """Извлечение текста из PPTX файлов."""

    async def extract_text(self, file: BinaryIO) -> str:
        try:
            import pptx

            presentation = pptx.Presentation(file)
            text = ''

            for slide in presentation.slides:
                for shape in slide.shapes:
                    if hasattr(shape, 'text'):
                        text += shape.text + '\n'
                text += '\n'

            return text.strip()
        except Exception as e:
            logger.error(f'Ошибка при извлечении текста из PPTX: {e}')
            raise ValueError(f'Не удалось извлечь текст из PPTX: {e}')


class TXTExtractor(FileExtractor):
    """Извлечение текста из TXT файлов."""

    async def extract_text(self, file: BinaryIO) -> str:
        try:
            content = file.read().decode('utf-8')
            return content.strip()
        except UnicodeDecodeError:
            try:
                file.seek(0)
                content = file.read().decode('cp1251')
                return content.strip()
            except Exception as e:
                logger.error(f'Ошибка при извлечении текста из TXT: {e}')
                raise ValueError(f'Не удалось извлечь текст из TXT: {e}')


class FileProcessor:
    """Класс для обработки файлов различных форматов."""

    _extractors: Dict[str, Type[FileExtractor]] = {
        '.pdf': PDFExtractor,
        '.docx': DocxExtractor,
        '.doc': DocxExtractor,
        '.pptx': PPTXExtractor,
        '.ppt': PPTXExtractor,
        '.txt': TXTExtractor,
    }

    @classmethod
    async def extract_text_from_file(cls, document: Document, bot: Bot) -> str:
        """Извлекает текст из файла."""
        file_name = document.file_name.lower()
        file_ext = os.path.splitext(file_name)[1]

        if file_ext not in cls._extractors:
            supported_formats = ', '.join(cls._extractors.keys())
            raise ValueError(f'Формат файла {file_ext} не поддерживается. Поддерживаемые форматы: {supported_formats}')

        file_id = document.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        downloaded_file = await bot.download_file(file_path)

        extractor_class = cls._extractors[file_ext]
        extractor = extractor_class()

        try:
            text = await extractor.extract_text(downloaded_file)

            max_length = 4000
            if len(text) > max_length:
                text = text[:max_length] + '...\n[Текст был обрезан из-за большого размера]'

            return text
        except Exception as e:
            logger.error(f'Ошибка при обработке файла {file_name}: {e}')
            raise ValueError(f'Ошибка при обработке файла: {e}')

    @classmethod
    def register_extractor(cls, extension: str, extractor: Type[FileExtractor]) -> None:
        """Регистрирует новый экстрактор для указанного расширения файла."""
        cls._extractors[extension.lower()] = extractor

