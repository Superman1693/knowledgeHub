# KnowledgeHub 功能盘点与待补功能建议（2026-10-12）

> ## ⚠️ 实施状态（2026-10-12 晚更新）
>
> 本文盘出的缺口**已按优先级实施完毕**，详见 [`localmind-design-mapping.md` 第十二节](./localmind-design-mapping.md)。
> 逐项对照：
>
> | 类别 | 已补齐 |
> |---|---|
> | **A 后端有实现、前端无入口**（3 项） | ✅ 全部补齐：批量摘要入口、重排序开关、附件管理页 |
> | **B 只做了一半**（5 项） | ✅ 5 项全补：版本 diff、标签合并、检索日期区间、设置页参数、数据目录静默丢弃 |
> | **C 完全没有**（9 项） | ✅ 9 项全补：编辑器自动保存、并发冲突检测、批量操作、图片 OCR 导入、静默请求约定、前端测试、保存的检索条件、回收站保留期、学习统计图表 |
> | **D 文档与代码脱节**（3 处） | ✅ `tasks.md` 已更正（任务组 6 勾选、视图数与测试基线同步） |
>
> 后端测试 **86 → 96 → 101 passed, 3 skipped**；前端 **0 → 19 passed**（Vitest）；
> `vue-tsc -b` 与 `vite build` 通过；`alembic check` 无新操作。
> 第三轮（2026-10-13）补齐剩余 P2 项，另修掉一个真 bug：
> **嵌入服务不可用时编辑笔记必返回 503**（内容其实已写库写盘，见
> `docs/localmind-design-mapping.md` 第 13.6 节）。
> **本轮未新增数据表、未产生迁移**。
>
> 下文为当时的盘点原文，保留作为对照基线。

- **盘点方式**：源码逐项核对 —— 后端 96 个接口 / 14 张表 / 8 个迁移 / 79 个 py 文件，前端 18 个页面 / 16 个侧栏入口；
  再把 `docs/specs/knowledgehub-core/requirements.md` 的 20 条需求、**逐条验收标准**与代码比对；
  最后做**反向核对**（从后端接口反查前端调用点），找出"实现了但没人用"的部分。
- **与 10-11 版差距分析的差别**：上一版结论是「三个闭环全断」；本版三个闭环**已全部闭合**，
  问题性质从"缺功能"变成了「**有实现但没接完**」——这是两轮之间最大的变化。

---

## 一、结论速览

> KnowledgeHub 现在是一个**功能基本完整、核心闭环全部闭合**的本地知识库：
> 写入（新建/编辑写回/版本/回收站）、关联（双链/反链/图谱）、复习（闪卡/SM-2）三大闭环都已跑通，
> 规格文档里的 20 条需求、共 80 余条验收标准**全部有对应实现且已实测**。

真正待补的不是"缺一个大模块"，而是四类**接不上的地方**：

| 类别 | 数量 | 性质 | 典型代表 |
|---|---|---|---|
| **A. 后端有实现、前端无入口** | 3 | 实现被浪费（"死功能"） | 批量 AI 摘要、LLM 重排序、附件管理 |
| **B. 只做了一半** | 5 | 有半成品，差最后一环 | 版本历史无 diff、相似标签无合并、检索无日期区间 |
| **C. 完全没有** | 9 | 真实缺口 | 自动保存、冲突检测、批量操作、图片 OCR 导入、前端测试 |
| **D. 文档与代码脱节** | 3 处 | 文档要同步 | `tasks.md` 仍把三个扩展模块标为"未实现" |

---

## 二、已实现的功能（盘点）

### 2.1 规模与基线

| 项目 | 数值 |
|---|---|
| 后端接口 | **96 个**（16 个路由模块） |
| 数据表 | **14 张**（8 个 Alembic 迁移） |
| 前端页面 | **18 个**（侧栏分组：知识库 / 整理 / 使用 / 扩展能力 / 系统） |
| 后端测试 | **86 passed, 1 skipped**（12 个测试文件） |
| 前端校验 | `vue-tsc -b` 退出码 0 · `vite build` 通过 |
| 迁移一致性 | `alembic check` → No new upgrade operations detected |

### 2.2 规格需求（1–20）落地情况

| 需求 | 状态 | 关键实现 |
|---|---|---|
| 1 本地优先与隐私 | ✅ | 无遥测；`ai_enabled` 在 **SQL 层**排除；密钥只写 `.env` |
| 2 一键启停 | ✅ | `start.bat` / `stop.bat` / `run.py` / `stop.py`，分步中文报错 |
| 3 PostgreSQL 与迁移 | ✅ | PG18 + `kh_app` 专用账号 + Alembic + `init_db.sql` |
| 4 可用性检测 | ✅ | `/api/health` 返回 `storage_mode`；非法 STORAGE_MODE 明确报错 |
| 5 导入与解析 | ✅ | md/txt/pdf/docx/代码 10+ 格式；PDF 页码；**扫描件自动 OCR**；重复文件提示 |
| 6 处理流水线与状态 | ✅ | `pending/processing/indexed/partial/failed` + 失败重试入口 |
| 7 文档管理 | ✅ | 上传（拖拽/批量）、预览编辑、重命名、分类标签、导出、`reveal` 定位原文件、软删除+二次确认、重建索引 |
| 8 分类管理 | ✅ | CRUD + **多级树**（`parent_id`，删父上提子） |
| 9 标签管理 | ⚠️ 9.5 半 | CRUD、筛选、文档数统计、AI 推荐、**相似检测有、合并操作无** |
| 10 分块与向量索引 | ✅ | 语义分块 + 父子检索 + HNSW；维度变更提示 |
| 11 检索 | ⚠️ 11.4 半 | 关键词/语义/混合、分类标签筛选、排序（相关度/更新/创建）、高亮、片段定位；**无日期区间** |
| 12 RAG 问答 | ✅ | SSE 流式、多轮上下文、材料不足明确告知、模型不可用不伪造 |
| 13 引用可追溯 | ✅ | 📄/📑/🌐 三类标注、点击跳转并高亮片段 |
| 14 事实性约束 | ✅ | 三类来源判定、**提示词层**要求并列展示矛盾来源 |
| 15 AI 服务配置 | ✅ | 本地/外部双模式、聊天与嵌入可分离、超时、密钥入 `.env` 且脱敏回显 |
| 16 会话历史 | ✅ | CRUD + 重命名 + 重新生成 + 中止 + 持久化 |
| 17 输出模式与术语词典 | ✅ | 详细/极简/举例 + 词典优先 + 无结果不臆造 |
| 18 设置页与首次启动 | ⚠️ 18.1 部分 | 大部分可配；**rerank / chunk_size 等参数未暴露** |
| 19 备份与恢复 | ✅ | 转储+文件打包、完整性校验、二次确认、缓存清理不误删 |
| 20 测试与质量 | ⚠️ | 后端 86 例；**前端零测试**（仅类型检查） |

### 2.3 超出规格的扩展能力（已完成）

| 批次 | 能力 |
|---|---|
| 第二批 | `[[双向链接]]` + 反向链接面板 + 工作台 + 每日笔记 + 4 个内置模板 + 外部变更扫描 |
| 第三批 | 闪卡 + **SM-2 间隔复习** + 复习历史 + 多级文件夹 + 附件上传（粘贴截图） |
| 第四批 | 知识图谱（Canvas 力导向）+ 笔记页内 AI（解释/总结/出卡/找关联） |
| 第五批 | 批量摘要 / LLM 重排序 / 附件引用提取 `POST /api/insights/batch-summary` |
| 第六批 | jieba 中文分词 + RapidOCR（纯 pip，无需 Tesseract） |
| 第七批 | 备份补表 + 恢复原子化 + 隐私口径统一 + 前端 13 项可靠性修复 |

---

## 三、四类"不完整"（逐条给证据）

### A. 后端有实现、前端无入口 —— 最可惜的一类

| # | 能力 | 后端证据 | 前端证据 | 后果 |
|---|---|---|---|---|
| A1 | **批量 AI 摘要** | `POST /api/insights/batch-summary` + `summary_service.py`（并发上限 3） | `grep batch-summary\|batchSummary` 在 `frontend/src` **零命中**，`insightsApi` 也没有对应方法 | 写完的并发摘要流水线**完全没人调用** |
| A2 | **LLM 重排序** | `rag/reranker.py` + `hybrid_search_reranked()` + `settings.rerank_enabled` | 前端零引用；且 `SettingsUpdate` **不含** `rerank_enabled` / `rerank_candidates` | 想开重排序**只能手改 `.env`**，界面上看不到、也不知道有这功能 |
| A3 | **附件管理** | `GET /api/attachments`（列表）、`DELETE /api/attachments/file/{sub}/{name}` | `attachmentsApi.list()` / `.remove()` **封装已写好**，但只有 `NoteEditView` 调了 `.upload` | 附件**只进不出**：传了图不能浏览、不能删、不能复用，久了变成看不见的磁盘占用 |

> A3 是投入产出比最高的一个：**API 封装已就绪，只缺一个页面**。

### B. 只做了一半

| # | 能力 | 已有 | 缺 | 关联需求 |
|---|---|---|---|---|
| B1 | 版本历史 | 列表、全文预览、回滚（回滚前自动备份当前版） | **diff 对比**（看"改了什么"） | — |
| B2 | 相似标签 | `GET /api/tags/similar` 检测 + 前端提示 | **合并 / 重命名并传播** | 需求 9.5 |
| B3 | 检索筛选 | 排序（relevance/updated/created）、分类、标签 | **日期区间** `date_from/date_to` | 需求 11.4「按更新时间筛选」 |
| B4 | 设置页 | `chunk_mode`、`parent_child_enabled` 可配 | `chunk_size`、`chunk_overlap`、`parent_chunk_size`、`rerank_*` | 需求 18.1 |
| B5 | 外部变更同步 | 手动「扫描同步」可发现并重建索引 | **启动时/定时自动扫描**（现在必须用户想起来点） | 需求 6 |

### C. 完全没有

| # | 缺口 | 为什么是问题 |
|---|---|---|
| C1 | **编辑器自动保存** | 只有 Ctrl+S / 保存按钮。写长笔记时忘记保存＝白写；虽然有未保存离开确认，但那是"防丢"不是"防忘" |
| C2 | **并发编辑冲突检测** | `update_document` 无版本号/时间戳校验。**用 VS Code 改了文件、同时应用里也在编辑 → 谁后保存谁覆盖，另一份静默消失**（扫描同步能事后发现，但已经覆盖了） |
| C3 | **批量操作** | `DocumentsView` 无多选：删 20 篇文档要点 20 次、改分类要一篇篇改。资料一多就不可用 |
| C4 | **回收站保留期 / 自动清理** | 只能手工「清空回收站」或逐个「彻底删除」；长期使用后回收站无限膨胀 |
| C5 | **图片 OCR 导入** | OCR 目前**只作用于 PDF 页面**（`_ocr_pdf_pages`）。截图（PNG/JPG）不能作为文档导入，**截图里的报错信息/配置没法规整进知识库**——而这是技术人最高频的场景 |
| C6 | **定时/自动备份** | 只有手动备份。用户不会记得每天点一次，而备份恰恰是"平时不做、出事就晚"的事 |
| C7 | **保存的检索条件** | 同一套筛选（某分类 + 某标签 + 关键词）每次重填；没有"智能集合" |
| C8 | **前端测试** | 零。`vue-tsc` 只查类型，拦不住逻辑回归（如上次修的"点查看文档没反应"这类运行时问题它查不出来） |
| C9 | 块级引用/嵌入 `![[笔记#段落]]` | 只能引整篇，无法复用某一段（高阶能力） |

### D. 文档与代码脱节（3 处，需同步）

| 位置 | 文档说法 | 实际 | 
|---|---|---|
| `docs/specs/knowledgehub-core/tasks.md` 头部 | 「**未实现**：任务组 6（后续扩展）」 | 三个扩展模块**早已实现并上线**（`insights` / `learning` / `devhelper` 共 25 个接口） |
| 同上，任务 28/29/30 | 全部 `- [ ]` 未勾选 | 全部已完成 |
| 同上，实现状态段 | 「前端 **12** 个视图」「`pytest` → **28 passed**」 | 实际 **18** 个视图 / **86 passed** |

> `README.md` 与 `localmind-design-mapping.md` 已在 10-12 修复轮同步过，**只剩 `tasks.md` 没跟上**。

---

## 四、建议新增或完善的功能（按优先级）

优先级定义：**P0 = 不做会丢数据或直接卡住日常使用**；**P1 = 补完已有半成品，投入小见效快**；**P2 = 明显提升长期价值**；**P3 = 锦上添花**。

### P0 —— 数据安全与可用性（4 项）

| # | 功能 | 作用与必要性 | 改动范围 |
|---|---|---|---|
| **P0-1** | **编辑器自动保存 + 冲突检测（乐观锁）** | 解决 C1+C2。自动保存让"忘记按 Ctrl+S"不再丢内容；`updated_at` 乐观锁让"外部改了 + 应用内也改了"变成**明确的冲突提示**而不是静默覆盖。这是知识库的信任底线：**用户必须先相信"我写的东西一定在、一定不会被别人/别的工具无声抹掉"**，才会把真正重要的内容放进来 | 后端：`schemas/document.py` 加 `expected_updated_at`；`services/document_service.py::update_document` 比对后抛 `ValidationError(409)`；`api/documents.py` 返回冲突时的双方内容。前端：`NoteEditView.vue`（800ms 防抖 autosave + 冲突对话框 + 并排对比）、`api/types.ts` |
| **P0-2** | **自动备份（间隔可配 + 保留 N 份）** | 解决 C6。备份要在"还没想到"的时候发生。建议实现为：启动时若距上次备份超过 N 小时则自动备份一次 + 备份目录只保留最近 M 份（避免撑爆磁盘） | 后端：`services/backup_service.py` 加 `auto_backup_if_due()` / `prune_backups(keep)`；`core/config.py` 加 `backup_interval_hours`、`backup_keep`；`main.py` lifespan 调用；`api/backup.py` 暴露策略配置。前端：`DataView.vue` 显示上次备份时间 + 策略开关 |
| **P0-3** | **批量操作（多选 / 批量删除 / 批量改分类 / 批量打标签）** | 解决 C3。没有批量，资料一过百篇，整理成本就超过收益——而后端其实已有 `set_document_tags`、`PUT /documents/{id}` 等单篇接口，批量只是"循环调用 + 一个多选 UI" | 后端：新增 `POST /api/documents/batch`（`action: delete\|move\|tag\|pin`，`ids: []`，带**上限与逐条结果返回**）。前端：`DocumentsView.vue` 加 `el-table` 多选列 + 批量操作条 |
| **P0-4** | **附件管理页**（复用已有接口） | 解决 A3。**投入最小**：后端接口和前端 API 封装都已存在，只缺页面。作用：能看/能删/能复用旧图，附件目录不再是无底洞 | 前端：新增 `views/AttachmentsView.vue`（列表 + 预览 + 删除 + 复制 Markdown 引用）；`router/index.ts` + `layouts/MainLayout.vue` 加入口。后端：无改动（或给 `GET /api/attachments` 加分页） |

### P1 —— 补完已实现的半成品（6 项，投入小、立刻可感知）

| # | 功能 | 作用与必要性 | 改动范围 |
|---|---|---|---|
| **P1-1** | **重排序开关（设置页）** | 解决 A2。能力已实现却无法开启＝白写。暴露后用户可自行权衡"精度↑ / 延迟与额度↓" | 后端：`schemas/settings.py::SettingsUpdate` 加 `rerank_enabled` / `rerank_candidates`（`settings_service` 的 DB 覆盖层已通用，无需改）。前端：`SettingsView.vue` 加两个字段 |
| **P1-2** | **批量摘要入口** | 解决 A1。`summary_service` 的并发流水线已写好，接一个入口就能用（选中多篇 → 生成摘要 → 写回笔记或展示） | 前端：`api/index.ts` 加 `insightsApi.batchSummary()`；`InsightsView.vue` 加"批量摘要"标签页（文档多选 + 结果展示）。后端：无改动 |
| **P1-3** | **版本历史 diff 对比** | 解决 B1。现在只能"看全文"，几百字的笔记要肉眼比对。有了 diff 才敢放心回滚 | 前端为主：`NoteEditView.vue` 历史抽屉加 diff 视图（**建议自己写轻量行级 diff，不新增依赖**）。后端：无改动（两份全文都已有） |
| **P1-4** | **检索日期区间筛选** | 解决 B3，也是需求 11.4 的另一半。查"上个月写的东西"目前做不到 | 后端：`schemas/search.py::SearchRequest` 加 `date_from`/`date_to`；`rag/retriever.py::_build_filters` 加时间条件；`services/search_service.py` 透传。前端：`SearchView.vue` 加日期选择器 |
| **P1-5** | **标签合并 / 重命名并传播** | 解决 B2。标签会越用越乱（`vue` / `Vue` / `vuejs`），检测有了但不能合，用户只能手工一篇篇改 | 后端：`services/tag_service.py` 加 `merge_tags(src, dst)`（迁移关联行 + 删源标签 + 处理唯一约束冲突）；`api/tags.py` 加 `POST /api/tags/{id}/merge`。前端：`TagsView.vue` 相似标签区加"合并到…" |
| **P1-6** | **图片 OCR 导入** | 解决 C5。截图是技术笔记最常见的载体。`ocr_service.ocr_image_bytes()` **已经存在**（PDF 页面识别就在用它），只需把 `png/jpg` 接进导入流程 | 后端：`services/parsers.py` 加 `_parse_image()`（复用 `ocr_service`）；`files.is_allowed` / `storage/files.py::save_upload` 放开图片扩展名；`api/documents.py` 上传白名单。前端：`UploadView.vue` 提示支持图片 |

### P2 —— 提升长期价值（5 项，全部 ✅ 已实现）

| # | 功能 | 作用与必要性 | 改动范围 | 状态 |
|---|---|---|---|---|
| **P2-1** | **启动时自动扫描外部变更** | 解决 B5。现在必须用户想起来点「扫描同步」；启动时静默扫一次，发现差异就在工作台提示"检测到 N 个文件被外部修改"，一键重建 | 后端：`main.py` lifespan 调 `workspace_service.startup_scan(apply=False)`（**只扫描不自动改**，保持"改知识库必须用户确认"的既有原则）；结果挂到 workbench。前端：`WorkbenchView.vue` 提示条 | ✅ |
| **P2-2** | **回收站保留期与自动清理** | 解决 C4。给回收站加"超过 N 天自动彻底删除"，并在清空前给出可撤销提示 | 后端：`core/config.py` 加 `trash_retention_days`（**默认 0 = 永不自动清理**，保持原行为）；`services/document_service.py` 加 `purge_expired_trash()` + `POST /api/documents/trash/purge-expired`。前端：`TrashView.vue` 显示剩余天数、设置页可配 | ✅ |
| **P2-3** | **前端测试（Vitest）** | 解决 C8。类型检查拦不住运行时缺陷——上一轮修掉的「`InsightsView` 用 hash 跳转导致点击无反应」「SSE 断流后卡在生成中」都属此类。优先覆盖：API 层 SSE 解析、`utils/markdown.ts` 净化、路由跳转 | 新增：`frontend/vitest.config.ts`、`frontend/src/**/__tests__/`；`package.json` 加 `test` 脚本与 devDependencies | ✅ **19 passed** |
| **P2-4** | **学习统计图表化** | 学习页现在只有数字（待复习/连续天数）。加上复习量趋势，才能看出"我到底学进去了没有" | 前端为主：`LearningView.vue` 统计标签页加图表（**纯 CSS 柱状图，未引 echarts**）。后端：`srs_service.review_stats` 加 `trend_14d` 按日聚合 | ✅（只做趋势图；掌握度分布/遗忘曲线未做） |
| **P2-5** | **保存的检索条件（智能集合）** | 解决 C7。把"分类 + 标签 + 关键词 + 排序"存成命名集合，随时重跑 | 后端：新表 `saved_searches`（已登记进 `DUMP_TABLES` / `CLEAR_ORDER`）+ 迁移 `c1f2a3b4d5e6` + CRUD。前端：`SearchView.vue` 加"保存当前条件" | ✅ |

### P3 —— 锦上添花（4 项）

### P3 —— 锦上添花（4 项，全部 ✅ 已实现）

| # | 功能 | 说明 | 改动范围 | 状态 |
|---|---|---|---|---|
| P3-1 | 块级引用 `![[笔记#段落]]` | 复用笔记的某一段而非整篇 | `services/link_service.py` 扩展正则 + `note_links` 加 `target_anchor` / `is_embed`；正文链接可点击 + `?h=` 锚点定位 | ✅ |
| P3-2 | 卡片 / 笔记批量导出 | 闪卡导出为 Anki 可导入格式（CSV/TSV），笔记导出已有 | `services/srs_service.py` 加 `export_anki_text()`；`LearningView.vue` 加按钮 | ✅ |
| P3-3 | 模糊 / 拼音搜索 | 记不清确切用词时也能搜到（编辑距离 / 拼音首字母） | 拼音：新增 `rag/pinyin.py` + `chunks.pinyin` / `pinyin_initials` 两列（含回填迁移）；模糊：`keyword_search` 加 `word_similarity` 分支，`keyword_only` 两阶段回退 | ✅（拼音 + 编辑距离都做了） |
| P3-4 | 窄屏 / 移动端适配 | 三栏在窄屏塌成单栏 | 侧栏改 off-canvas 抽屉（`MainLayout.vue`）；共通规则收口在 `styles.css` 全局媒体查询，特殊布局各组件内单独处理 | ✅ |

---

## 五、改动范围汇总（按文件，便于排期）

| 优先级 | 后端文件 | 前端文件 | 文档 |
|---|---|---|---|
| P0-1 自动保存+冲突 | `schemas/document.py`、`services/document_service.py`、`api/documents.py` | `views/NoteEditView.vue`、`api/types.ts`、`api/index.ts` | README 已知限制 |
| P0-2 自动备份 | `services/backup_service.py`、`core/config.py`、`main.py`、`api/backup.py` | `views/DataView.vue` | README |
| P0-3 批量操作 | `api/documents.py`（新增 `/batch`）、`services/document_service.py` | `views/DocumentsView.vue` | docs 变更日志 |
| P0-4 附件管理页 | （无，或 `api/attachments.py` 加分页） | **新增** `views/AttachmentsView.vue`、`router/index.ts`、`layouts/MainLayout.vue` | README 功能表 |
| P1-1 重排序开关 | `schemas/settings.py` | `views/SettingsView.vue` | docs |
| P1-2 批量摘要入口 | （无） | `api/index.ts` 加方法、`views/InsightsView.vue` | docs |
| P1-3 版本 diff | （无） | `views/NoteEditView.vue` | docs |
| P1-4 日期区间筛选 | `schemas/search.py`、`rag/retriever.py`、`services/search_service.py` | `views/SearchView.vue` | docs |
| P1-5 标签合并 | `services/tag_service.py`、`api/tags.py` | `views/TagsView.vue` | docs |
| P1-6 图片 OCR 导入 | `services/parsers.py`、`storage/files.py`、`api/documents.py` | `views/UploadView.vue` | README |
| P2-1 启动自动扫描 | `main.py`、`api/workspace.py` | `views/WorkbenchView.vue` | docs |
| P2-2 回收站保留期 | `core/config.py`、`services/document_service.py` | `views/TrashView.vue` | README |
| P2-3 前端测试 | （无） | **新增** `vitest.config.ts`、`__tests__/`、`package.json` | README 测试节 |
| P2-4 学习统计图表 | `services/srs_service.py`（加聚合） | `views/LearningView.vue` | docs |
| P2-5 保存的检索条件 | **新表 + 迁移**、`services/saved_search_service.py`、`api/saved_searches.py` | `views/SearchView.vue`、`api/types.ts`、`api/index.ts` | docs |

> ✅ **实施状态（2026-10-13）**：P0-1 ~ P0-4、P1-1 ~ P1-6、P2-1 ~ P2-5、P3-1 ~ P3-4
> **已全部实现**，且前两轮的「只做了一半」也已补齐：
> **P3-3 补上编辑距离模糊匹配**（拼错 `vuee`→vue，仅精确结果不足时启用）、
> **P2-4 补上掌握度分布与遗忘曲线**（后者按 `prev_interval` 从真实复习记录算出回忆成功率）。
> 清单清完之后，第五轮又回头补了两个前几轮刻意没动的基础缺口：
> **文档标题可检索**（此前搜 `Harness.md` 的「Harness」0 命中）与
> **新建笔记即可设私密**（此前 `NoteCreate` 无 `ai_enabled`，而 Pydantic 静默忽略未知字段）。
> 落地细节见 `docs/localmind-design-mapping.md` 第十二 ~ 十五节。
> 此后又按 PKM 对比调研补齐了输入/输出两端：相关笔记、速记、局域网访问、
> 网页剪藏、知识库体检、静态站导出、**PDF 批注**（见第十六 ~ 二十一节）。

> ⚠️ 两条硬约定（来自本项目反复踩过的坑，实施时务必遵守）：
> 1. **新增任何表，必须同步登记进 `backup_service.DUMP_TABLES` 与 `CLEAR_ORDER`**
>    （`test_backup_covers_every_registered_table` 会自动断言，漏了会直接测失败）；`CLEAR_ORDER` 必须先子后父。
> 2. **改完 API 文件跑一次路由自检**（历史上同一次 Edit 误删过函数定义行）。

---

## 六、建议一并完成的文档同步

| 文件 | 需要改什么 |
|---|---|
| `docs/specs/knowledgehub-core/tasks.md` | 头部"未实现"改为已完成；任务 28/29/30 勾选；视图数 12→18；测试基线 28→86 |
| `docs/specs/knowledgehub-core/design.md` | 补上第 2–7 批新增的表（`note_revisions`/`note_links`/`flashcards`/`review_logs`）与 96 个接口中新增的部分 |
| `README.md` | 若采纳 P0-4 / P1-6 / P2-3，需同步功能表与测试节 |
| `docs/localmind-design-mapping.md` | 按既有惯例新增一批（第八批）记录 |

---

## 七、可复现的核对方式

本文所有"已实现 / 未实现"判断都可用下列命令复核：

```bash
# 1) 后端全部接口清单
cd backend && ./.venv/Scripts/python.exe -c "import app.main as m; print(len(m.app.routes))"

# 2) 各模块路由明细（按 api/*.py 打印 prefix + 方法 + 路径）
#    见本文档编写时使用的脚本；或直接看 http://127.0.0.1:8000/docs

# 3) 反向核对：某后端能力是否有前端调用
cd frontend/src && grep -rn "batch-summary\|batchSummary" .   # → 零命中（A1）
cd frontend/src && grep -rn "rerank" .                        # → 零命中（A2）
cd frontend/src && grep -rn "attachmentsApi" .                # → 仅 upload 被调用（A3）

# 4) 数据表与备份清单是否一致
cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_audit_fixes_2026_10_12.py -q --basetemp=.pytest_tmp

# 5) 迁移一致性
cd backend && ./.venv/Scripts/python.exe -m alembic check
```

---

## 八、如果只做三件事

按"投入产出比 × 风险"排序，建议先做这三件：

1. **P0-1 编辑器自动保存 + 冲突检测** —— 唯一会导致用户**丢掉亲手写的内容**的缺口，且是信任底线。
2. **P0-4 附件管理页** —— 后端接口和前端 API 封装都已存在，**只缺一个页面**，是所有项里最便宜的。
3. **P1-1 重排序开关 + P1-2 批量摘要入口** —— 两个"已实现但无法使用"的功能，改 `SettingsUpdate` 和加一个标签页即可。

这三件事做完，项目就**没有"实现了却用不上"的功能**了，之后再做 P2 才是纯增量。
