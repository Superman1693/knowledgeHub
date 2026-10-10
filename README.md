# KnowledgeHub · 本地个人知识库 AI 平台

一款**完全运行在个人电脑本地**的个人知识库软件。通过 AI 与 RAG（检索增强生成）技术，把散落的个人资料变成**可检索、可问答、可追溯**的私有知识资产。

> 不是云端 SaaS，不是多人协作平台，也不是单纯的 AI 聊天机器人。
> 所有数据默认保存在本机，不上传第三方。

---

## 一、功能特性（核心闭环）

| 模块 | 能力 |
|---|---|
| **工程与基础设施** | 一键启停脚本（自动避让端口）、本地数据目录、PostgreSQL 数据库、配置管理、首次启动初始化 |
| **文档管理** | 多格式导入（md/txt/pdf/docx/代码）、解析、处理状态、预览、编辑、重命名、分类、标签、删除、导出 |
| **术语词典** | 自定义术语/缩写/项目名词及其别名，问答时优先采用词典定义 |
| **知识检索（RAG）** | 文本分块、向量嵌入、pgvector 索引、关键词（pg_trgm 分词命中）+ 语义 + 混合检索、来源定位 |
| **AI 问答** | 本地模型 / 外部 API 双模式、对话与嵌入可分离、RAG 上下文构建、引用标注、会话历史、多轮追问、三种输出模式、重新生成与中止 |

**后续扩展**（已在规格中规划，将作为独立 Feature Spec 实现）：AI 知识加工、学习辅助（模拟面试/错题）、项目开发辅助。

---

## 二、技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Vue Router + Pinia + Element Plus + Axios + Markdown/代码高亮 |
| 后端 | Python + FastAPI + SQLAlchemy 2.x + Alembic + Pydantic |
| 数据库 | **PostgreSQL 18 + pgvector**（关系 + 向量 + pg_trgm 关键词，一库搞定） |
| 文件存储 | 本地文件系统 `data/` |
| AI | 本地模型（Ollama 兼容）或外部 OpenAI 兼容 API |

> 本机 PostgreSQL 无中文分词器，因此关键词检索使用 `pg_trgm`（子串/相似度）而非 `tsvector`。

---

## 三、目录结构

```
KnowledgeHub/
├── frontend/          # Vue 3 前端
├── backend/           # FastAPI 后端
│   ├── app/
│   │   ├── api/       # 路由
│   │   ├── core/      # 配置 / 数据库 / 日志 / 异常
│   │   ├── models/    # SQLAlchemy 模型
│   │   ├── schemas/   # Pydantic 模型
│   │   ├── services/  # 业务逻辑
│   │   ├── rag/       # 分块 / 检索
│   │   ├── ai/        # 模型适配
│   │   └── storage/   # 文件存储
│   ├── alembic/       # 数据库迁移
│   └── tests/         # 测试
├── data/              # 运行期数据（不进版本库）
├── docs/specs/        # Kiro 规格文档
├── scripts/           # 启动脚本与建库 SQL
├── .env.example
└── README.md
```

---

## 四、环境要求

- **Python** 3.11+（本项目在 3.13 下开发）
- **Node.js** 18+
- **PostgreSQL** 18（需已安装并运行；本项目使用 pgvector、pg_trgm 扩展）
- 不需要 Docker、Redis

---

## 五、首次安装与启动

### 1. 初始化数据库（只需一次）

```bash
# 以 PostgreSQL 超级用户执行，创建专用库、账号与扩展
psql -h 127.0.0.1 -p 5432 -U postgres -f scripts/init_db.sql
```

该脚本会创建：
- 数据库 `knowledgehub`
- 专用账号 `kh_app`
- 扩展 `vector`、`pg_trgm`、`pgcrypto`、`uuid-ossp`

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 DB_PASSWORD（kh_app 的密码）
```

### 3. 启动

**Windows：** 双击 `scripts/start.bat`（自动检查环境、装依赖、迁移、启动前后端）

**跨平台：**
```bash
python scripts/run.py
```

**手动启动：**
```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

### 4. 访问

- 前端：http://127.0.0.1:5173
- 后端接口文档：http://127.0.0.1:8000/docs

> **端口自动避让**：若 8000 或 5173 已被其他程序占用，启动脚本会自动改用下一个空闲端口，
> 并把实际地址打印在控制台（前端代理也会自动指向正确的后端端口）。
> 实际使用的端口记录在 `.kh_runtime.json`，`stop.bat` 据此精确停止。

> **Windows 说明**：`start.bat` / `stop.bat` 为**纯 ASCII** 引导脚本，仅负责调用
> `scripts/run.py` / `scripts/stop.py`。所有中文提示由 Python 输出——
> 因为 cmd.exe 用 GBK 解析批处理文件，UTF-8 中文会导致乱码与语法错误。

---

## 六、日常使用

1. **导入文档** → 「导入文档」页拖拽上传，后台自动解析并建立索引。
2. **配置模型** → 「系统设置」页选择本地模型或外部 API，填写地址与模型名，点「检测模型服务」（会同时检测对话与嵌入）。
3. **维护术语** → 「术语词典」页录入技术缩写、项目名词与别名，问答时优先采用词典定义。
4. **检索** → 「知识检索」页输入关键词或自然语言，支持关键词/语义/混合三种模式。
5. **问答** → 「AI 问答」页提问，回答会标注引用来源，可点击跳转到原文；支持「复制」与「重新生成」。
6. **维护** → 「数据与备份」页执行备份、恢复与缓存清理。

> 未配置 AI 模型时，文档管理、分类、标签、关键词检索等**非 AI 功能仍可正常使用**；文档状态会显示为「失败」，配置好嵌入模型后可在文档管理中「重建索引」。

---

## 七、配置说明

配置分两处：

| 类型 | 位置 | 示例 |
|---|---|---|
| 敏感信息 | `.env`（不进版本库） | `DB_PASSWORD`、`EXTERNAL_API_KEY` |
| 可调参数 | 数据库 `app_settings` 表（经设置页修改） | 模型名、超时、检索权重、上传上限 |

主要环境变量见 `.env.example`。

---

## 八、备份与恢复

- **备份**：`data/backups/knowledgehub_backup_<时间>.zip`
  内容 = 数据库全部业务表（JSON）+ `documents/` 原始文档 + `attachments/` 附件
- **恢复**：先校验 manifest 与版本，需二次确认后覆盖导入

---

## 九、测试

```bash
cd backend
python -m pytest tests -v
```

---

## 十、已实现 / 未实现 / 已知限制

### 已实现
- 后端：文档上传解析（md/txt/pdf/docx/代码）、分块、嵌入、pgvector 索引、pg_trgm + 语义混合检索、RAG 问答（SSE 流式）、引用标注、会话管理、分类/标签 CRUD、设置管理、备份恢复、健康检查
- 前端：工作台、文档管理、文档详情、导入、分类、标签、检索、AI 问答、系统设置、数据与备份、扩展路线图

### 未实现（后续扩展）
- AI 知识加工（笔记归档、标签推荐增强、冗余检测、知识关联、思维导图）
- 学习辅助（模拟面试、错题、复习）
- 项目开发辅助（代码评审、故障排查、需求拆解、时间线）
- 联网补充信息（接口已预留 `use_web`，未接入实际联网检索）

### 已知限制
- **中文检索**：本机 PostgreSQL 无中文分词器。关键词检索采用「中文 2-gram + 英文整词」分词后做多词命中计数（pg_trgm），语义检索由 pgvector 承担。
- **对话与嵌入可分离**：两者可以是不同服务（见 `.env` 中的 `EXTERNAL_API_*` 与 `EMBEDDING_*`）；`EMBEDDING_BASE_URL` 留空则复用对话服务。
- **嵌入维度**：`EMBEDDING_DIM` 必须与嵌入模型实际输出一致（不一致时「检测模型服务」会直接报出实际维度），修改后需重建全部索引。
- **推理模型**：若对话模型会输出思考过程（`reasoning_content`，如 deepseek-v4 / qwen3.7 系列），系统会将其与正文分离——界面显示「模型思考中…（已思考 N 字）」，思考内容不计入回答与引用。
- **PDF 扫描件**：无文本层的扫描件无法解析，需先 OCR。
- **回退方案**：`STORAGE_MODE=sqlite`（SQLite + ChromaDB）为预留回退路径，需额外安装 `backend/requirements-fallback.txt`。

### 文档处理状态说明

| 状态 | 含义 |
|---|---|
| 等待 / 处理中 | 后台正在解析与建索引 |
| 已索引 | 已分块并完成向量化，关键词与语义检索均可用 |
| 部分索引 | 已分块但**未向量化**（嵌入模型未配置或不可用）：关键词检索可用，语义检索不可用。配置嵌入模型后点「重建索引」即可补齐 |
| 失败 | 处理出错，可在文档详情查看原因并重试 |

---

## 十一、常见问题

**Q：启动报「数据库连接失败」？**
A：确认 PostgreSQL 已启动、`.env` 中 `DB_PASSWORD` 正确、已执行 `scripts/init_db.sql`。

**Q：文档一直是「失败」状态？**
A：多为嵌入模型未配置或不可用。在「系统设置」配置并检测模型服务后，到文档管理点「重建索引」。

**Q：检索不到内容？**
A：确认文档状态为「已索引」，并尝试切换到「关键词检索」模式。

**Q：启动时提示端口被占用？**
A：脚本会自动改用空闲端口（如 8001），请以控制台打印的地址为准。

**Q：双击 `start.bat` 出现「不是内部或外部命令」等报错？**
A：这是旧版本批处理的编码问题（已在当前版本修复）。请确认 `scripts/start.bat` 为纯 ASCII；
若仍异常，可直接运行 `python scripts/run.py`。

---

## 十二、规格文档

本项目采用 Kiro 规格驱动开发（Spec-Driven Development），规格文档位于 `docs/specs/`：

- `steering/`：product.md、tech.md、structure.md
- `knowledgehub-core/`：requirements.md、design.md、tasks.md
