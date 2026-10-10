---
inclusion: always
---

# 结构引导：KnowledgeHub

> 本文件是 Kiro Steering 的 **structure.md**（结构引导），在每次交互中自动加载。
> 它定义项目"怎么组织"——目录、模块边界、命名约定与架构决策。生成的代码必须能自然融入本结构。

## 1. 顶层目录结构

```text
KnowledgeHub/
├── frontend/                     # 前端工程（Vue 3 + TS + Vite）
│   ├── src/
│   │   ├── api/                  # Axios 封装与接口定义
│   │   ├── assets/               # 静态资源
│   │   ├── components/           # 通用组件
│   │   ├── composables/          # 组合式函数
│   │   ├── layouts/              # 页面布局
│   │   ├── router/               # 路由定义
│   │   ├── stores/               # Pinia 状态
│   │   ├── views/                # 页面级组件
│   │   ├── utils/                # 工具函数
│   │   ├── App.vue
│   │   └── main.ts
│   ├── public/
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── backend/                      # 后端工程（FastAPI）
│   ├── app/
│   │   ├── api/                  # 路由层（按资源拆分子模块）
│   │   │   ├── documents.py
│   │   │   ├── categories.py
│   │   │   ├── tags.py
│   │   │   ├── search.py
│   │   │   ├── chat.py
│   │   │   ├── settings.py
│   │   │   └── backup.py
│   │   ├── core/                 # 配置、日志、数据库连接、异常
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── logging.py
│   │   │   └── exceptions.py
│   │   ├── models/               # SQLAlchemy 模型
│   │   ├── schemas/              # Pydantic 请求/响应模型
│   │   ├── services/             # 业务逻辑
│   │   ├── rag/                  # 分块、嵌入、检索
│   │   ├── ai/                   # 模型适配（本地 / 外部）
│   │   ├── storage/              # 文件读写与路径管理
│   │   └── main.py               # 应用入口
│   ├── tests/                    # 测试
│   ├── alembic/                  # 迁移脚本
│   │   └── versions/
│   ├── alembic.ini
│   └── requirements.txt
│
├── data/                         # 运行期数据（不进版本库）
│   ├── documents/                # 上传的原始文件
│   ├── attachments/              # 附件及相关文件
│   ├── exports/                  # 导出文件
│   ├── cache/                    # 可重建缓存
│   └── logs/                     # 运行日志
│
├── scripts/                      # 本地启动与维护脚本
│   ├── start.bat
│   ├── stop.bat
│   └── init_db.sql               # 建库 / 建号 / 建扩展 SQL
│
├── docs/
│   └── specs/                    # Kiro 规格文档（本目录）
│       ├── steering/
│       └── knowledgehub-core/
│
├── .env.example
├── .gitignore
└── README.md
```

> 说明：原提示词中的 `data/vector_store/`（ChromaDB 持久化目录）**已取消**——向量数据改存 PostgreSQL。仅当启用回退方案（SQLite + ChromaDB）时才重建该目录。

## 2. 后端模块职责与依赖方向

依赖方向必须单向：**api → services → (models / rag / ai / storage) → core**。禁止反向依赖。

| 模块 | 职责 | 允许依赖 |
|---|---|---|
| `api/` | 路由定义、参数校验、调用 service、组装响应 | services、schemas |
| `services/` | 业务编排（文档、分类、标签、检索、问答、备份） | models、rag、ai、storage、core |
| `rag/` | 文本分块、嵌入调用、pgvector/pg_trgm 检索、结果融合 | models、ai、core |
| `ai/` | 模型适配层（本地 Ollama / 外部 OpenAI 兼容），统一接口 | core |
| `storage/` | 本地文件读写、路径解析、数据目录管理 | core |
| `models/` | SQLAlchemy ORM 模型（表结构） | core |
| `schemas/` | Pydantic 模型（出入参） | — |
| `core/` | 配置、数据库会话、日志、异常基类 | — |

**规则：**
- 路由函数**不写业务逻辑**，只做参数校验与转发。
- 跨模块调用走 service，**禁止**路由直接操作 ORM 会话之外的数据库细节。
- `ai/` 与 `rag/` 不感知 HTTP，保持可单独测试。

## 3. 前端结构约定

- `views/` 一个文件对应一个页面；`components/` 放可复用 UI。
- 所有后端调用集中在 `api/`，页面不直接写 `axios`。
- 全局状态放 `stores/`（Pinia）；页面局部状态用 `ref`/`reactive`。
- 路由与菜单一一对应，页面需具备加载态、空态、错误态。

## 4. 命名约定

| 对象 | 约定 | 示例 |
|---|---|---|
| Python 文件/模块 | `snake_case` | `document_service.py` |
| Python 类 | `PascalCase` | `DocumentService` |
| Python 函数/变量 | `snake_case` | `parse_document` |
| 数据库表 | 复数 `snake_case` | `documents`、`document_tags` |
| 数据库列 | `snake_case` | `created_at`、`chunk_index` |
| REST 路径 | 复数、短横线 | `/api/documents`、`/api/app-settings` |
| Vue 组件文件 | `PascalCase.vue` | `DocumentList.vue` |
| TS 变量/函数 | `camelCase` | `fetchDocuments` |
| TS 类型/接口 | `PascalCase` | `DocumentMeta` |
| 环境变量 | `UPPER_SNAKE` | `DATABASE_URL`、`AI_API_KEY` |

## 5. 数据目录规范

- 所有业务数据集中在**一个**数据目录（默认 `data/`），可通过配置修改。
- 必须区分三类内容：**正式数据**（documents/attachments）、**导出产物**（exports）、**可重建缓存**（cache）。
- 清理缓存时**不得**误删原始文档、正式笔记等重要资料。
- 用户指定其他数据目录时，写入用户指定位置，**不得**擅自产生多份分散副本。

## 6. 架构决策记录（ADR 摘要）

| 编号 | 决策 | 理由 |
|---|---|---|
| ADR-001 | 用 PostgreSQL 18 + pgvector 替代 SQLite + ChromaDB | 本机已具备且运行中，一个库覆盖关系+向量+关键词，减少依赖 |
| ADR-002 | 中文关键词检索用 `pg_trgm` 而非 `tsvector` | 本机无中文分词器，trigram 子串/相似度匹配对中文有效 |
| ADR-003 | 原始文件不入库，仅存文件系统路径 | 避免大字段拖累数据库；便于用户直接查看原始文件 |
| ADR-004 | AI 访问抽象为统一适配层 | 本地模型与外部 API 可切换，界面需明示当前模式 |
| ADR-005 | 后台任务用本地线程/轻量队列 | 单用户本地场景，无需引入 Redis/Celery |
| ADR-006 | 提供回退路径但默认不启用 | 兼顾"优先用本机软件"与"换机可用"两种诉求 |

## 7. 禁止事项（结构层面）

- 禁止把业务逻辑写进路由函数或 Vue 页面组件。
- 禁止硬编码数据库连接、API 密钥、绝对路径。
- 禁止在源码仓库中提交 `data/`、备份文件、数据库文件、`.env`。
- 禁止绕过 service 层直接在 `api/` 中调用 `rag/`、`ai/` 的内部实现。
