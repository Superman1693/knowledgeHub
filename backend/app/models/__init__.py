"""模型包：统一导入，确保 Base.metadata 完整（供 Alembic 使用）。"""
from app.models.base import Base
from app.models.category import Category
from app.models.chunk import Chunk
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.glossary import GlossaryTerm
from app.models.setting import AppSetting
from app.models.tag import Tag, document_tags

__all__ = [
    "Base",
    "Category",
    "Chunk",
    "Conversation",
    "Message",
    "Document",
    "GlossaryTerm",
    "AppSetting",
    "Tag",
    "document_tags",
]
