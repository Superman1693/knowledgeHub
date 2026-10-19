"""pytest 公共配置 + **测试环境隔离**。

## 为什么必须隔离（本文件存在的首要理由）

此前 `tests/` **直连真实 PostgreSQL 与真实 `data/` 目录**，靠「用例自建自清」维持干净。
两个后果，都在实际使用中发生了：

1. **跑测试等于拿真实知识库做实验**。某个用例清理失败（比如断言先失败、`finally` 只清了一半），
   库里就会留下半截数据；文件删除还可能被系统拦截（>50 个/次），残留只能手工清。
2. **孤儿文件会静默降低覆盖率**。`data/documents` 里一有残留，那些「要求目录干净」的用例
   就**自动 skip**——不是通过了，是没跑。PDF 批注用例加入后，一轮跑完留下 126 个文件。

## 怎么隔离

| 维度 | 做法 | 为什么这么做 |
|---|---|---|
| 数据库 | 独立 schema `kh_test` | 应用账号**没有 CREATEDB 权限**，建不了独立库；schema 级隔离同样干净，且**不需要改任何应用代码** |
| 生效方式 | 给引擎挂 `connect` 监听执行 `SET search_path` | 显式且确定。⚠️ 试过两条隐式路子都不可靠：连接串的 `?options=` 会被 configparser 当成插值语法（alembic 直接报错）；`PGOPTIONS` 环境变量在应用引擎上生效、在 alembic 的引擎上却没生效，排查成本很高 |
| 文件 | `DATA_DIR` 指向临时目录，整轮结束后删除 | 残留随目录一起消失，不再需要手工清理 |
| 表结构 | 每次会话用 **alembic 重建**，而不是 `create_all` | `create_all` 只建模型里声明的对象，会漏掉「只存在于迁移里」的索引/约束，测试就测不到真实结构 |

## 一个约束

`app.core.config.settings` 是**模块级单例**，`app.core.database` 在 import 时用它建引擎。
`DATA_DIR` / `rerank_enabled` 必须在 import 之前改好——本文件在模块顶部就做。

真正的生效校验放在会话夹具里**用一条真实连接**检查 `current_schema()`——
字符串层面的「看起来设对了」不算数。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# 保证能 import app 包
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 测试专用 schema 名。可用环境变量覆盖，便于并行跑多套测试。
TEST_SCHEMA = os.environ.get("KH_TEST_SCHEMA", "kh_test")

# ---------------------------------------------------------------- 1) 先改配置
# 放在 import app.* 之前：settings 是单例，一旦建好就定死了
from app.core.config import settings  # noqa: E402

_TMP_DATA = Path(tempfile.mkdtemp(prefix="kh-test-data-"))
settings.data_dir = str(_TMP_DATA)
# 测试不该意外消耗额度或访问外网：重排序默认关闭这件事本来就在配置里，
# 这里显式写一遍，防止有人把 .env 打开后测试行为跟着漂移
settings.rerank_enabled = False

from sqlalchemy import event  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402

assert os.path.normcase(str(settings.data_path)) == os.path.normcase(str(_TMP_DATA)), (
    "测试数据目录未生效，测试会污染真实 data/"
)


@event.listens_for(engine, "connect")
def _set_test_search_path(dbapi_connection, _record) -> None:  # noqa: ANN001
    """每个新连接都把默认 schema 指到测试 schema。

    用事件监听而不是连接串参数：连接串里的 `%3D` 会被 configparser 当插值语法，
    而 `PGOPTIONS` 环境变量在本机出现过「应用引擎生效、alembic 引擎不生效」的
    不一致行为。这里直接对每条连接执行 SQL，行为一目了然。
    """
    with dbapi_connection.cursor() as cur:
        cur.execute(f'SET search_path TO "{TEST_SCHEMA}", public')


# ---------------------------------------------------------------- 2) 会话级重建
@pytest.fixture(scope="session", autouse=True)
def isolated_environment():
    """重建测试 schema → 跑迁移 → 建数据目录；结束后删临时目录。

    会话开始就把 schema 删掉重建，而不是「有就复用」：
    上一轮中途失败留下的半截表结构会让本轮表现怪异，而且极难排查。
    重建成本只有几百毫秒。
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    # 管理连接：建/删 schema 需要 autocommit
    admin = create_engine(settings.resolved_database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
            conn.execute(text(f'CREATE SCHEMA "{TEST_SCHEMA}"'))
    finally:
        admin.dispose()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    # 显式给绝对路径：alembic.ini 里写的是相对路径，依赖当前工作目录
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # 注入一条连接：它的 search_path 已由上面的 connect 监听设成测试 schema，
    # 否则 alembic 会连到 public，看到真实库的 alembic_version 后直接「无事可做」
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        # 版本表必须落在测试 schema：不指定的话 alembic 会顺着 search_path
        # 命中 public 里**真实库**的 alembic_version，误判成「已到 head」而一条迁移都不跑
        cfg.attributes["version_table_schema"] = TEST_SCHEMA
        command.upgrade(cfg, "head")

    # 用**真实连接**校验隔离是否生效——字符串层面设对了不代表连上就对了
    with engine.connect() as conn:
        current_schema = conn.execute(text("SELECT current_schema()")).scalar()
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
                )
            )
        }
    assert current_schema == TEST_SCHEMA, (
        f"测试库未生效：连接默认 schema 是 {current_schema!r}，应为 {TEST_SCHEMA!r}。"
        "请确认 PGOPTIONS 在 import app.core.database 之前设置。"
    )
    assert "documents" in tables, f"迁移未在测试 schema 里建表：{sorted(tables)[:8]}"

    settings.ensure_dirs()

    yield

    # 清理顺序有讲究：
    # 1) 先释放连接池；
    # 2) 再关日志句柄 —— setup_logging 会把 FileHandler 挂在 logs/ 下，
    #    而 Windows 上「仍被打开的文件」删不掉，不关就会残留整个临时目录
    #    （曾残留 7 个，靠 ignore_errors 静默掩盖了）；
    # 3) 最后删目录。
    engine.dispose()
    logging.shutdown()
    shutil.rmtree(_TMP_DATA, ignore_errors=True)


# ---------------------------------------------------------------- 3) 固定夹具内容
# 一小组固定文档。此前若干用例依赖**用户真实知识库里的 vue.md / Docker.md**
# （例如「拼错 vuee 还能搜到 vue」），隔离后必须自己造。
#
# 内容刻意满足两个条件：
#   1. 标题含 `vue` / `Docker`，让「拼错容错」有可召回的目标；
#   2. 正文足够长，切成 ≥3 个片段，让「精确命中充足时不启用模糊」有依据。
SEED_DOCS: dict[str, str] = {
    "vue.md": """# Vue 3 响应式原理

Vue 3 使用 Proxy 替代 Vue 2 的 Object.defineProperty，这是响应式实现的关键变化。
Proxy 能拦截对象上的读取、赋值、删除与 `in` 判断，而 defineProperty 只能拦截已有的属性读写。

## 依赖收集

Vue 的响应式系统在读取时通过 track 收集依赖：当前正在执行的副作用函数会被记录到
该属性对应的依赖集合里。这个副作用函数通常是组件的渲染函数或 computed 的求值函数。

## 触发更新

当数据被修改时，Vue 通过 trigger 取出该属性收集到的全部副作用，逐个重新执行。
为避免同一次更新里重复执行，Vue 会把副作用放进队列并在微任务里批量刷新。

## 为什么 Proxy 更彻底

Vue 2 的 defineProperty 方案有三个固有缺陷：无法监听新增属性、无法监听数组索引与长度、
需要递归遍历整个对象来初始化。Proxy 方案天然解决前两个，第三个通过惰性代理缓解——
只有真正访问到嵌套对象时才创建它的代理。
""",
    "Docker.md": """# Docker 常用命令

Docker 把应用与依赖打包成镜像，运行时以容器隔离。日常最常用的是下面几条命令。

## 镜像

`docker build -t app:latest .` 用当前目录的 Dockerfile 构建镜像。
`docker images` 列出本地镜像，`docker rmi <id>` 删除不要的镜像。

## 容器

`docker run -d -p 8000:8000 app:latest` 后台启动并把容器端口映射到宿主机。
`docker ps` 看运行中的容器，`docker logs -f <id>` 跟踪日志，
`docker exec -it <id> bash` 进入容器排查问题。

## 编排

单机多容器用 docker compose：`docker compose up -d` 启动，
`docker compose down` 停止并清理网络。数据持久化用 volume 挂载，
不要把数据库文件放在容器可写层里。
""",
}


@pytest.fixture
def seeded_library() -> None:
    """确保测试库里有一小组固定内容（幂等）。

    做成幂等而不是「会话开始建一次」：备份/恢复那条用例会先清空全库再恢复，
    若夹具只建一次，后面依赖内容的用例就会突然找不到数据。
    """
    from sqlalchemy import select

    from app.models import Document
    from app.services import document_service

    db = SessionLocal()
    try:
        titles = {t for (t,) in db.execute(select(Document.title)).all()}
        for title, body in SEED_DOCS.items():
            if title in titles:
                continue
            asyncio.run(
                document_service.create_note(db, title=title, content_text=body)
            )
    finally:
        db.close()


# ---------------------------------------------------------------- 4) 嵌入服务探测
@pytest.fixture(scope="session")
def embedding_available() -> bool:
    """探测一次嵌入服务是否可用（会话级，避免每个用例都打一次 API）。

    本机的嵌入服务走外部免费额度，配额耗尽时返回 403。此时凡是
    「语义检索 / 重建索引」类用例都会按设计降级（关键词检索仍可用），
    并非代码缺陷——应该跳过或断言降级行为，而不是报红。
    """
    from app.rag import indexer

    # 只调外部 API，不碰数据库，因此在任何 schema 下都能探测
    try:
        vec = asyncio.run(indexer.embed_query("连接性探测"))
    except Exception:  # noqa: BLE001
        return False
    return bool(vec)


@pytest.fixture
def requires_embedding(embedding_available: bool) -> None:
    """在依赖嵌入服务的用例上声明：不可用时跳过并说明原因。"""
    if not embedding_available:
        pytest.skip("嵌入服务当前不可用（配额耗尽或网络故障），语义检索类用例跳过")
