"""add anchor and embed flag to note_links

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-10-13 10:40:00.000000

支持块级引用 `[[标题#锚点]]` 与嵌入引用 `![[标题]]`：
- `target_anchor`：`#` 后的小节名，为空表示引用整篇；
- `is_embed`：区分 `![[ ]]`（嵌入）与 `[[ ]]`（普通链接）。

唯一约束从 (source, title) 扩到 (source, title, anchor)：
同一篇笔记引用两个不同小节是两条合法引用，只按标题去重会丢掉后者。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('note_links', sa.Column('target_anchor', sa.String(length=512), nullable=True))
    op.add_column(
        'note_links',
        sa.Column('is_embed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )

    # 旧约束只按标题去重，会把「同篇不同小节」的引用误判为重复，需替换
    op.drop_constraint('uq_note_links_source_target', 'note_links', type_='unique')
    op.create_unique_constraint(
        'uq_note_links_source_target',
        'note_links',
        ['source_document_id', 'target_title', 'target_anchor'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_note_links_source_target', 'note_links', type_='unique')
    op.create_unique_constraint(
        'uq_note_links_source_target',
        'note_links',
        ['source_document_id', 'target_title'],
    )
    op.drop_column('note_links', 'is_embed')
    op.drop_column('note_links', 'target_anchor')
