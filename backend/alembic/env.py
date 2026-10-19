"""Alembic 环境配置。"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 alembic 能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (导入以填充 metadata)

config = context.config
config.set_main_option("sqlalchemy.url", settings.resolved_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.resolved_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 支持外部注入连接：测试要在独立 schema 里建表（见 tests/conftest.py），
    # 靠注入已设好 `search_path` 的连接，比在连接串里塞 options 可靠得多
    # （连接串里的 `%3D` 会被 configparser 当成插值语法而报错）。
    # 不注入时行为与之前完全一致。
    injected = config.attributes.get("connection")
    if injected is not None:
        context.configure(
            connection=injected,
            target_metadata=target_metadata,
            compare_type=True,
            # 必须显式指定版本表所在 schema。`alembic_version` 是**不带 schema**
            # 查的，而注入连接的 search_path 通常是 `测试schema,public`：
            # 测试 schema 里还没有这张表时，PG 会退到 public 命中**真实库**的
            # alembic_version，于是 alembic 认定「已到 head」、一条迁移都不跑。
            version_table_schema=config.attributes.get("version_table_schema"),
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
