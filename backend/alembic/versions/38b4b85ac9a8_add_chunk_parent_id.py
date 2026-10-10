"""add chunk parent_id

Revision ID: 38b4b85ac9a8
Revises: fa5b8cd29e87
Create Date: 2026-10-10 22:15:17.396491
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '38b4b85ac9a8'
down_revision: Union[str, None] = 'fa5b8cd29e87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 自引用外键必须显式命名：autogenerate 默认渲染成 None，
    # 会让 downgrade 的 drop_constraint(None) 直接报错（约束名不能为空）。
    op.add_column('chunks', sa.Column('parent_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_chunks_parent_id'), 'chunks', ['parent_id'], unique=False)
    op.create_foreign_key(
        'fk_chunks_parent_id', 'chunks', 'chunks', ['parent_id'], ['id'], ondelete='CASCADE'
    )


def downgrade() -> None:
    op.drop_constraint('fk_chunks_parent_id', 'chunks', type_='foreignkey')
    op.drop_index(op.f('ix_chunks_parent_id'), table_name='chunks')
    op.drop_column('chunks', 'parent_id')
