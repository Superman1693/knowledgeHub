"""add pinyin columns to chunks

Revision ID: d5e6f7a8b9c0
Revises: c1f2a3b4d5e6
Create Date: 2026-10-13 10:10:00.000000

给 chunks 增加 `pinyin` / `pinyin_initials` 两列并回填，
用于支持「只打得出来拼音」的检索（`xiangying` / `xjbsj`）。

回填放在迁移里而不是留给用户手动重建索引：否则升级后拼音检索
会静默失效（查得到 0 条但没有任何提示），用户只会以为功能坏了。
pypinyin 未安装时跳过回填，列保持 NULL，检索自动退回纯文本匹配。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c1f2a3b4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 加列（可空：老数据 / 无 pypinyin 时为 NULL，不影响检索主链路）
    op.add_column('chunks', sa.Column('pinyin', sa.Text(), nullable=True))
    op.add_column('chunks', sa.Column('pinyin_initials', sa.Text(), nullable=True))

    # 2) trgm 索引：拼音查询是 ILIKE '%...%'，没索引会全表扫描
    op.create_index(
        'ix_chunks_pinyin_trgm',
        'chunks',
        ['pinyin'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'pinyin': 'gin_trgm_ops'},
    )
    op.create_index(
        'ix_chunks_pinyin_initials_trgm',
        'chunks',
        ['pinyin_initials'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'pinyin_initials': 'gin_trgm_ops'},
    )

    # 3) 回填现有片段
    _backfill()


def downgrade() -> None:
    op.drop_index('ix_chunks_pinyin_initials_trgm', table_name='chunks')
    op.drop_index('ix_chunks_pinyin_trgm', table_name='chunks')
    op.drop_column('chunks', 'pinyin_initials')
    op.drop_column('chunks', 'pinyin')


def _backfill() -> None:
    """给现有片段补拼音。失败只告警，不让迁移失败（列可空，功能可降级）。"""
    try:
        from app.rag.pinyin import pinyin_available, pinyin_of
    except Exception as exc:  # noqa: BLE001
        print(f"[pinyin] 无法导入拼音模块，跳过回填：{exc}")
        return

    if not pinyin_available():
        print("[pinyin] pypinyin 未安装，跳过回填；重建索引时会自动补上")
        return

    conn = op.get_bind()
    # 只取还没有拼音的行，重复执行安全
    rows = conn.execute(
        sa.text(
            "SELECT id, heading, content FROM chunks "
            "WHERE pinyin IS NULL OR pinyin_initials IS NULL"
        )
    ).fetchall()
    if not rows:
        return

    updates = []
    for row in rows:
        # 标题也参与拼音：用户常按小节标题找内容
        source = f"{row.heading or ''}\n{row.content or ''}"
        full, initials = pinyin_of(source)
        updates.append(
            {"id": row.id, "pinyin": full or None, "pinyin_initials": initials or None}
        )

    conn.execute(
        sa.text(
            "UPDATE chunks SET pinyin = :pinyin, pinyin_initials = :pinyin_initials "
            "WHERE id = :id"
        ),
        updates,
    )
    print(f"[pinyin] 已回填 {len(updates)} 个片段")
