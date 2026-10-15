"""add pdf_annotations

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-14 21:50:00.000000

PDF 批注（引文锚定的高亮与批注）。

锚点用「页号 + 引文 + 归一化矩形」三者组合：坐标只负责画在哪，
真正的身份是引文——PDF 被换成同内容的新版本后坐标整体失效时，
靠引文重新定位，用户的高亮不会丢。

`rects` 用 JSONB：它是一组只读的几何数据（跨行选择会产生多个矩形），
既不参与索引也不需要按元素查询，拆列或建子表都是过度设计。

⚠️ 本表必须同步登记进 `backup_service.DUMP_TABLES` 与 `CLEAR_ORDER`
（项目约定第 1 条，历史上漏过三次表）。已在同一次提交中完成。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pdf_annotations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=True),
        sa.Column("suffix", sa.Text(), nullable=True),
        sa.Column("rects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rotation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="yellow"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # 按文档取全部批注（打开 PDF 时的第一个动作）
    op.create_index("ix_pdf_annotations_document_id", "pdf_annotations", ["document_id"])
    # 渲染单页时取该页批注
    op.create_index(
        "ix_pdf_annotations_doc_page", "pdf_annotations", ["document_id", "page_no"]
    )


def downgrade() -> None:
    op.drop_index("ix_pdf_annotations_doc_page", table_name="pdf_annotations")
    op.drop_index("ix_pdf_annotations_document_id", table_name="pdf_annotations")
    op.drop_table("pdf_annotations")
