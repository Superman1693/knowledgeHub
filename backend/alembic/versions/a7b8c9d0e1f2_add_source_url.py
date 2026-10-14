"""add source_url for web clippings

Revision ID: a7b8c9d0e1f2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-14 19:30:00.000000

网页剪藏（URL 导入）需要记录原始地址：
- 溯源：剪藏来的内容必须能回到出处，否则知识库里的内容失去可信度；
- 去重：同一网址重复剪藏时可提示，而不是默默堆一份副本。

可空列，对既有数据无影响（老文档都不是剪藏来的）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_url", sa.Text(), nullable=True))
    # 按 URL 查重是剪藏的高频动作（每次导入都要查一次），加索引
    op.create_index("ix_documents_source_url", "documents", ["source_url"])


def downgrade() -> None:
    op.drop_index("ix_documents_source_url", table_name="documents")
    op.drop_column("documents", "source_url")
