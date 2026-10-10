# KnowledgeHub 核心闭环 —— 技术设计（design.md）

> 本文档描述**如何实现** `requirements.md` 中定义的需求。
> 阅读顺序建议：先看第 2 节架构总览，再看第 5–7 节数据模型与接口，最后看第 8 节关键流程时序图。

---

## 1. 概述与设计目标

| 目标 | 说明 |
|---|---|
| 本地可运行 | 全部服务运行在本机，不依赖云 |
| 复用现有环境 | 存储复用本机已安装的 PostgreSQL 18 + pgvector |
| 模块清晰 | 前后端分层，后端按功能划分模块，单一职责 |
| 可测试 | 业务逻辑与 HTTP、数据库可分离测试 |
| 可扩展 | 新增文件格式、模型、检索策略时无需改动核心流程 |
| 可回退 | 本机无合适存储时可切换到 SQLite + ChromaDB |

---

## 2. 总体架构

### 2.1 分层视图

```mermaid
flowchart TB
    subgraph Client["浏览器（本机）"]
        UI["Vue 3 SPA<br/>页面 / 组件 / Pinia"]
    end

    subgraph Server["FastAPI 后端（127.0.0.1）"]
        API["API 层<br/>路由 / 参数校验"]
        SVC["Service 层<br/>业务编排"]
        RAG["RAG 模块<br/>分块 / 检索 / 融合"]
        AI["AI 适配层<br/>本地模型 / 外部 API"]
        STO["Storage 模块<br/>文件读写 / 路径管理"]
    end

    subgraph Data["数据层（本机）"]
        PG[("PostgreSQL 18<br/>+ pgvector + pg_trgm")]
        FS[("本地文件系统<br/>data/documents, attachments")]
    end

    subgraph Ext["外部（可选）"]
        LM["本地模型服务<br/>Ollama"]
        RM["外部模型 API<br/>OpenAI 兼容"]
    end

    UI -->|REST / SSE| API
    API --> SVC
    SVC --> RAG
    SVC --> AI
    SVC --> STO
    RAG --> PG
    SVC --> PG
    STO --> FS
    AI --> LM
    AI --> RM
```

### 2.2 组件职责

| 组件 | 职责 |
|---|---|
| 前端 SPA | 页面渲染、交互、调用 REST、SSE 接收流式回答 |
| API 层 | 路由、入参校验、鉴权（本项目无）、响应组装 |
| Service 层 | 文档/分类/标签/检索/问答/备份的业务编排 |
| RAG 模块 | 文本分块、嵌入调用、pgvector 语义检索、pg_trgm 关键词检索、结果融合 |
| AI 适配层 | 统一模型接口，屏蔽本地/外部差异 |
| Storage 模块 | 原始文件落盘、路径解析、数据目录管理 |
| PostgreSQL | 关系数据 + 向量 + 关键词索引 |
| 本地文件系统 | 原始文件、附件、导出、缓存、日志 |

---

## 3. 技术选型理由

| 选型 | 理由 |
|---|---|
| PostgreSQL 18 | 本机已安装且运行中；关系 + 向量 + 关键词一库搞定 |
| pgvector 0.8.2 | 本机已安装；支持 `vector` 类型与 HNSW 索引，满足语义检索 |
| pg_trgm | 本机已安装；在无中文分词器情况下实现中文子串/相似度匹配 |
| SQLAlchemy 2.x + Alembic | 成熟的 ORM 与迁移方案，便于结构演进 |
| FastAPI | 类型友好、自动文档、原生支持异步与 SSE |
| Vue 3 + Element Plus | 组件生态成熟，适合信息密集型后台界面 |
| 本地线程/轻量队列 | 单用户本地场景，无需引入 Redis/Celery |

---

## 4. 目录结构与模块划分

见 Steering 的 `structure.md`。核心约定复述：

- 后端依赖方向单向：`api → services → (models / rag / ai / storage) → core`
- 前端所有请求集中在 `frontend/src/api/`
- 运行期数据集中在 `data/`，通过配置可改

---

## 5. 数据模型（PostgreSQL）

### 5.1 表清单

| 表名 | 用途 | 所属需求 |
|---|---|---|
| `documents` | 文档元数据 | 5、6、7 |
| `chunks` | 知识片段 + 向量 | 10 |
| `categories` | 知识分类 | 8 |
| `tags` | 标签 | 9 |
| `document_tags` | 文档-标签关联 | 9 |
| `glossary_terms` | 专属术语词典 | 17 |
| `conversations` | 会话 | 16 |
| `messages` | 会话消息 + 引用 | 12、13、16 |
| `app_settings` | 用户可调配置 | 18 |

> **索引声明约定（重要）**：`chunks.embedding` 的 HNSW 索引、`chunks.content` 与
> `documents.title` 的 pg_trgm GIN 索引，**必须同时写进模型的 `__table_args__`**。
> 否则 Alembic autogenerate 会把它们视为"数据库中多余的索引"而在新迁移里删除，
> 导致向量检索与关键词检索静默失效。

> 扩展模块（面试、错题）的表在各自后续 spec 中定义，此处不建。

### 5.2 `documents`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `uuid` PK | 主键 |
| `title` | `varchar(512)` | 文档标题 |
| `original_filename` | `varchar(512)` | 原始文件名 |
| `file_path` | `text` | 本地相对路径（相对数据目录） |
| `file_type` | `varchar(32)` | 扩展名/类型 |
| `file_size` | `bigint` | 字节数 |
| `category_id` | `uuid` FK → categories.id | 可为空 |
| `content_text` | `text` | 解析后的全文（用于预览与再分块） |
| `status` | `varchar(16)` | `pending`/`processing`/`indexed`/`failed` |
| `error_message` | `text` | 失败原因 |
| `chunk_count` | `integer` | 片段数 |
| `created_at` | `timestamptz` | 创建时间 |
| `updated_at` | `timestamptz` | 更新时间 |

索引：`status`、`category_id`、`updated_at`；标题与正文关键词用 `pg_trgm` GIN。

### 5.3 `chunks`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `uuid` PK | 主键 |
| `document_id` | `uuid` FK → documents.id (ON DELETE CASCADE) | 所属文档 |
| `chunk_index` | `integer` | 片段序号 |
| `heading` | `varchar(512)` | 章节标题（可空） |
| `content` | `text` | 片段正文 |
| `page_no` | `integer` | 页码（可空，未知则 NULL） |
| `token_count` | `integer` | 估算 token 数 |
| `embedding` | `vector(dim)` | 嵌入向量（dim 由嵌入模型决定） |
| `created_at` / `updated_at` | `timestamptz` | 时间戳 |

索引：
- HNSW：`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`
- 关键词：`CREATE INDEX ... USING gin (content gin_trgm_ops)`
- 外键：`document_id`

### 5.4 `categories` / `tags` / `document_tags`

- `categories`：`id`、`name`（唯一）、`description`、`created_at`、`updated_at`
- `tags`：`id`、`name`（唯一）、`created_at`
- `document_tags`：`document_id` + `tag_id` 复合主键，双向外键级联

### 5.5 `conversations` / `messages`

`conversations`：`id`、`title`、`mode`（`detail`/`brief`/`example`）、`created_at`、`updated_at`

`messages`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `uuid` PK | |
| `conversation_id` | `uuid` FK (CASCADE) | |
| `role` | `varchar(16)` | `user`/`assistant`/`system` |
| `content` | `text` | 消息正文 |
| `sources` | `jsonb` | 引用数组（见 5.6） |
| `source_type` | `varchar(16)` | `原文`/`归纳`/`联网`/`混合` |
| `created_at` | `timestamptz` | |

### 5.6 引用结构（`messages.sources` JSON）

```json
[
  {
    "document_id": "uuid",
    "document_title": "Vue3 组合式 API 笔记",
    "chunk_id": "uuid",
    "heading": "ref 与 reactive",
    "page_no": 12,
    "snippet": "ref 返回带 .value 的响应式引用……",
    "source_type": "知识库原文"
  }
]
```

约束：所有字段必须来自真实数据；无法确定的 `page_no`/`heading` 写 `null`，**不得伪造**。

### 5.7 `app_settings`

- `key`（`varchar` PK）、`value`（`jsonb`）、`updated_at`
- 仅存非敏感、用户可调配置；**密钥与数据库密码不进此表**（进 `.env`）

---

## 6. 向量存储与检索设计

### 6.1 向量维度与索引

- `dim` 由所选嵌入模型决定（如 768 / 1024），配置于 `.env`。
- 维度变更时：需重建 `embedding` 列与 HNSW 索引，系统应提示用户重建。
- 距离度量：**余弦距离**（`vector_cosine_ops`），检索时用 `<=>` 算子。

### 6.2 检索策略

| 检索类型 | 实现 | 说明 |
|---|---|---|
| 标题搜索 | `documents.title` + pg_trgm | 子串/相似度 |
| 正文关键词 | `chunks.content` + pg_trgm | `ILIKE` + `similarity()` |
| 标签搜索 | `tags` join | 精确匹配 |
| 语义检索 | `chunks.embedding <=> query_vec` | HNSW 加速 |
| 混合检索 | 关键词 + 语义按权重融合 | 见 6.3 |
| 分类筛选 | `documents.category_id` | |
| 更新时间筛选 | `documents.updated_at` | |

### 6.3 混合检索融合

```mermaid
flowchart LR
    Q["用户查询"] --> KW["关键词检索<br/>pg_trgm"]
    Q --> EM["查询嵌入<br/>嵌入模型"]
    EM --> VS["向量检索<br/>pgvector"]
    KW --> N1["归一化分数"]
    VS --> N2["归一化分数"]
    N1 --> F["加权融合<br/>score = α·kw + β·vec"]
    N2 --> F
    F --> R["Top-K 候选片段"]
```

- 权重 `α`（关键词）、`β`（语义）可配置，默认 `α=0.3, β=0.7`。
- 融合前对两路分数做归一化，避免量纲差异。
- 返回 Top-K（默认 8）片段，并携带文档定位信息。

### 6.4 中文检索策略

- 本机 PG **无中文分词器**，因此不使用 `tsvector` 做中文全文检索。
- 关键词命中：`content ILIKE '%关键词%'`（`pg_trgm` GIN 加速）。
- 相似度排序：`similarity(content, query)`。
- 语义兜底：pgvector 余弦检索覆盖同义与语义相近的表达。

---

## 7. 接口设计（REST API）

> 统一前缀 `/api`；除流式接口外均为 JSON；错误统一返回 `{ code, message, detail }`。

### 7.1 文档

| 方法 | 路径 | 说明 | 需求 |
|---|---|---|---|
| POST | `/api/documents` | 上传文档（支持批量/拖拽） | 5、7 |
| GET | `/api/documents` | 列表（分页、筛选、排序） | 7 |
| GET | `/api/documents/{id}` | 详情 | 7 |
| PUT | `/api/documents/{id}` | 更新标题/分类/内容 | 7 |
| DELETE | `/api/documents/{id}` | 删除（含文件与向量） | 7 |
| POST | `/api/documents/{id}/reindex` | 重建索引 | 7、10 |
| GET | `/api/documents/{id}/export` | 导出 Markdown/文本 | 7 |
| GET | `/api/documents/{id}/file` | 定位/下载原始文件 | 7 |

### 7.2 分类、标签与术语词典

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/categories` | 列表 / 创建 |
| PUT/DELETE | `/api/categories/{id}` | 修改 / 删除 |
| GET/POST | `/api/tags` | 列表 / 创建 |
| PUT/DELETE | `/api/tags/{id}` | 修改 / 删除 |
| POST | `/api/tags/suggest` | 基于内容推荐标签 |
| GET/POST | `/api/glossary` | 术语列表 / 创建 |
| PUT/DELETE | `/api/glossary/{id}` | 修改 / 删除 |
| POST | `/api/glossary/lookup` | 查询文本命中的术语（含渲染结果预览） |

**术语词典在问答中的作用**：提问时会先用术语名与别名做子串匹配，
命中的条目以「专属术语词典（用户自定义，优先采用）」注入上下文，
优先级高于知识库资料；词典与资料冲突时以词典为准，词典中没有的术语不得臆造。

### 7.3 检索

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/search` | 混合检索，返回片段与定位 |

请求体：`{ query, mode: "keyword"|"semantic"|"hybrid", category_id?, tags?, top_k? }`

### 7.4 问答（含流式）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/conversations` | 会话列表 / 新建 |
| PATCH/DELETE | `/api/conversations/{id}` | 改标题 / 删除 |
| POST | `/api/conversations/{id}/messages` | 提问（**SSE 流式返回**） |
| POST | `/api/messages/{id}/regenerate` | 重新生成 |
| POST | `/api/chat/abort` | 中止当前生成 |

### 7.5 设置与系统

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/PUT | `/api/settings` | 读取 / 更新设置 |
| POST | `/api/settings/test-model` | 检测模型服务可用性 |
| GET | `/api/settings/index-status` | 向量索引状态 |
| GET | `/api/health` | 健康检查（含数据库连通性） |

### 7.6 备份与恢复

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/data-dir` | 查看数据目录 |
| POST | `/api/backup` | 手动备份（返回包含内容说明） |
| POST | `/api/restore` | 恢复（先校验完整性/版本） |
| POST | `/api/cache/clean` | 清理缓存（不动正式数据） |

---

## 8. 关键流程时序图

### 8.1 文档导入处理流程（需求 5、6、10）

```mermaid
sequenceDiagram
    participant U as 用户
    participant F as 前端
    participant A as API
    participant S as DocumentService
    participant P as Parser
    participant ST as Storage
    participant E as Embedding
    participant DB as PostgreSQL

    U->>F: 上传文件
    F->>A: POST /api/documents
    A->>S: 创建文档记录(status=pending)
    S->>ST: 保存原始文件
    S->>P: 解析文本(保留标题/章节/页码)
    P-->>S: 纯文本 + 结构
    S->>DB: 保存元数据与全文
    S->>S: 分块(chunk)
    S->>E: 批量生成嵌入
    E-->>S: 向量列表
    S->>DB: 写入 chunks(含 embedding)
    S->>DB: 更新 status=indexed, chunk_count
    S-->>A: 处理结果
    A-->>F: 返回状态
    F-->>U: 展示处理结果
```

失败分支：任一环节异常 → `status=failed` + `error_message`，前端提供重试。

### 8.2 RAG 问答流程（需求 11、12、13、14）

```mermaid
sequenceDiagram
    participant U as 用户
    participant F as 前端
    participant A as API
    participant R as RAG
    participant AI as AI适配层
    participant DB as PostgreSQL

    U->>F: 提交问题
    F->>A: POST /conversations/{id}/messages
    A->>R: 检索(混合)
    R->>DB: pg_trgm 关键词 + pgvector 语义
    DB-->>R: 候选片段
    R->>R: 融合排序 Top-K
    R-->>A: 片段 + 元数据
    A->>A: 判断材料是否足够
    alt 材料足够
        A->>AI: 构建上下文并请求生成
        AI-->>A: 流式回答
        A->>DB: 保存消息 + sources(引用)
        A-->>F: SSE 流式输出 + 引用
    else 材料不足
        A->>DB: 保存消息(说明缺失)
        A-->>F: 明确告知缺少哪些信息
    end
    F-->>U: 渲染回答 + 可点击引用
```

### 8.3 会话保存与恢复（需求 16）

```mermaid
sequenceDiagram
    participant F as 前端
    participant A as API
    participant DB as PostgreSQL
    F->>A: 打开历史会话列表
    A->>DB: 查询 conversations
    DB-->>A: 会话列表
    A-->>F: 渲染
    F->>A: 进入某会话
    A->>DB: 查询 messages(含 sources)
    DB-->>A: 消息与引用
    A-->>F: 恢复完整历史
```

---

## 9. 数据库初始化（建库 / 建号 / 建扩展）

`scripts/init_db.sql`（示意，实际以可执行脚本形式提供）：

```sql
-- 1) 创建专用账号
CREATE ROLE kh_app WITH LOGIN PASSWORD '<由 .env 提供>';

-- 2) 创建专用数据库
CREATE DATABASE knowledgehub OWNER kh_app;

-- 3) 在目标库中启用扩展（需超级用户执行一次）
\c knowledgehub
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 4) 授权
GRANT ALL PRIVILEGES ON DATABASE knowledgehub TO kh_app;
```

表结构由 **Alembic 迁移**创建（不在 SQL 中手写建表）：

- 迁移中定义 `documents`、`chunks`、`categories`、`tags`、`document_tags`、`conversations`、`messages`、`app_settings`
- 在迁移中创建 HNSW 索引与 pg_trgm GIN 索引
- `embedding` 列维度从配置读取，维度变更需新增迁移

---

## 10. 错误处理与降级策略

| 场景 | 处理 |
|---|---|
| 数据库连接失败 | 启动脚本区分"服务未启动/账号密码错误/库不存在"，给出对应提示 |
| 模型服务不可用 | 返回明确错误，非 AI 功能仍可用；**不伪造成功** |
| 文档解析失败 | `status=failed` + 原因；提供重试 |
| 检索结果为空 | 明确告知无相关资料，不编造知识库内容 |
| 嵌入维度变更 | 提示需重建索引，提供重建入口 |
| 外部 API 超时 | 按配置超时中止，返回超时错误 |
| 删除文档 | 级联删除 chunks 与向量，二次确认 |
| 缓存清理 | 仅清 `data/cache/`，不触碰正式数据 |

**降级原则**：任何 AI 相关能力失败，都不得影响文档管理等本地基础功能。

---

## 11. 配置项与环境变量（`.env`）

| 变量 | 说明 | 默认 |
|---|---|---|
| `DATABASE_URL` | PG 连接串 | `postgresql+psycopg://kh_app:***@127.0.0.1:5432/knowledgehub` |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | 分项连接信息 | `127.0.0.1` / `5432` / `knowledgehub` / `kh_app` / — |
| `DATA_DIR` | 数据目录 | `./data` |
| `BACKEND_HOST` / `BACKEND_PORT` | 后端监听 | `127.0.0.1` / `8000` |
| `FRONTEND_PORT` | 前端端口 | `5173` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | 嵌入模型与维度 | 视模型而定 |
| `CHAT_MODEL` | 聊天模型 | — |
| `AI_MODE` | `local` / `external` | `local` |
| `LOCAL_MODEL_BASE_URL` | 本地模型地址 | `http://127.0.0.1:11434` |
| `EXTERNAL_API_BASE_URL` / `EXTERNAL_API_KEY` | 外部服务地址与密钥 | — |
| `REQUEST_TIMEOUT` | 请求超时（秒） | `60` |
| `MAX_UPLOAD_MB` | 上传大小上限 | `50` |
| `HYBRID_ALPHA` / `HYBRID_BETA` | 混合检索权重 | `0.3` / `0.7` |
| `STORAGE_MODE` | `postgres` / `sqlite` | `postgres` |

> `.env` 受 `.gitignore` 保护；必须提供 `.env.example` 模板。

---

## 12. 测试策略（对应需求 20）

| 层级 | 范围 | 说明 |
|---|---|---|
| 单元测试 | 分块、融合排序、解析器、引用构建 | 纯逻辑，不依赖外部服务 |
| 集成测试 | 数据库读写、迁移、pgvector 检索 | 使用测试库 |
| 端到端测试 | 上传→解析→索引→检索→问答 | 真实数据流 |
| 安全测试 | 密钥、监听地址、日志、删除清理 | 见需求 20.5 |

必须提供**可执行的测试命令**与**真实执行结果**；未执行的测试不得声称通过。

---

## 13. 后续扩展的架构预留

- `services/` 已按功能分模块，扩展模块新增独立 service 即可。
- `chunks` 表设计可被"知识关联""思维导图"直接复用。
- `messages.sources` 结构可被"面试点评""代码评审"复用为证据引用。
- 扩展模块各自拥有独立 Feature Spec（requirements/design/tasks），不修改本规格的表结构语义。

---

## 14. 与回退方案（SQLite + ChromaDB）的差异

| 维度 | 主方案 | 回退方案 |
|---|---|---|
| 关系数据 | PostgreSQL | SQLite |
| 向量 | pgvector | ChromaDB |
| 关键词 | pg_trgm | SQLite FTS / LIKE |
| 迁移 | Alembic（PG 方言） | Alembic（SQLite 方言） |
| 切换 | 由 `STORAGE_MODE` 决定 | 同左 |

回退仅在目标机器**无合适 PostgreSQL** 时启用；本机已具备，默认不启用。
