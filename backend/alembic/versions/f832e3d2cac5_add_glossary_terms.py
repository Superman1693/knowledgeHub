"""add glossary terms

Revision ID: f832e3d2cac5
Revises: cdad83a6bdc2
Create Date: 2026-10-10 09:42:04.924585
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f832e3d2cac5'
down_revision: Union[str, None] = 'cdad83a6bdc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('glossary_terms',
    sa.Column('term', sa.String(length=255), nullable=False),
    sa.Column('definition', sa.Text(), nullable=False),
    sa.Column('aliases', sa.JSON(), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_glossary_terms_term'), 'glossary_terms', ['term'], unique=True)

    # 检索索引现已在上游模型的 __table_args__ 中声明；
    # 这里用 IF NOT EXISTS 兜底，防止因历史原因缺失（向量检索与关键词检索依赖它们）。
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_content_trgm "
        "ON chunks USING gin (content gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_title_trgm "
        "ON documents USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    # 仅回滚本迁移新增的对象；检索索引由上游迁移负责，不在此删除
    op.drop_index(op.f('ix_glossary_terms_term'), table_name='glossary_terms')
    op.drop_table('glossary_terms')
