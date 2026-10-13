# KnowledgeHub 缺陷修复报告（2026-10-12）

- 范围：对 2026-10-11 排查之后的**新一轮**代码通读、缺陷定位与修复
- 方法：源码逐文件核对 + 对真实数据库执行查询验证 + 补充回归用例
- 详细技术说明见 [`localmind-design-mapping.md` 第十一节](./localmind-design-mapping.md)（第七批）
- 验证基线：后端 **85 passed, 1 skipped** · `vue-tsc -b` 退出码 0 · `vite build` 成功 · `alembic check` 无新操作

---

## 一、缺陷总览

| 级别 | 编号 | 缺陷 | 影响 | 状态 |
|---|---|---|---|---|
| 🔴 P0 | F-1 | 备份/恢复漏了 `note_revisions`（版本历史） | 换机恢复后版本历史 **100% 丢失** | ✅ 已修 |
| 🔴 P0 | F-2 | 恢复先 `commit()` 清空全库再插入，且不校验 dump | 恢复失败 → **全库已清空且无法回滚**；空 dump 可清空全库后"成功"返回 | ✅ 已修 |
| 🟠 P1 | F-3 | 出题素材（`_pick_chunks`）未过滤回收站与私密笔记 | 私密笔记内容被整段发给对话模型 | ✅ 已修 |
| 🟠 P1 | F-4 | 代码评审/排障检索未传 `ai_only=True` | 同上 | ✅ 已修 |
| 🟡 P2 | F-5 | 重复检测 / 关联文档未过滤 `deleted_at` | 回收站文档被列为"重复/相关" | ✅ 已修 |
| 🟡 P2 | F-6 | 重复检测 O(n²) 全量配对，无法走 HNSW | 大库下接口超时 | ✅ 已修（LATERAL + LIMIT） |
| 🟡 P2 | F-7 | 知识图谱标签边"先全量配对再截断" | 热门标签可产生约 8 万条边 | ✅ 已修（上限 2 万） |
| 🟡 P2 | F-8 | 文档列表 N+1（`tags` 未预加载） | 一页 100 条 = 101 次查询 | ✅ 已修（`selectinload`） |
| 🟡 P2 | F-9 | 标签文档数把回收站也算进去 | 与文档列表数字对不上 | ✅ 已修 |
| 🟡 P2 | F-10 | 扩展模块参数错误仍报 503 / 500 | 前端无法区分"参数错"与"AI 挂了" | ✅ 已修（统一 422） |
| 🟡 P2 | F-11 | `IndexStatusOut` 少 2 个字段 | `note_total` / `trash_total` 被静默丢弃 | ✅ 已修 |
| 🟡 P2 | F-12 | `DocumentUpdate.title` 无 `min_length` | 标题可被更新成空串 | ✅ 已修 |
| 🟡 P2 | F-13 | 初始迁移硬编码 `VECTOR(dim=1024)` | 改 `EMBEDDING_DIM` 后全新安装列维度不匹配 | ✅ 已修 |
| 🟡 P2 | F-14 | `InsightsView` 用 hash 跳转（项目是 history 路由） | 点"查看文档"**无任何反应** | ✅ 已修 |
| 🟡 P2 | F-15 | `NoteEditView` 无路由离开守卫 | 点侧边栏 / Ctrl+K / 后退**静默丢失**未保存内容 | ✅ 已修 |
| 🟡 P2 | F-16 | Markdown 净化用正则黑名单，可被 `<svg/onload=…>` 绕过 | 导入内容可执行脚本（潜在 XSS） | ✅ 已修（DOMPurify） |
| 🟡 P2 | F-17 | `ChatView` 会话切换无请求序号 | 慢响应覆盖后选中的会话（内容与高亮不符） | ✅ 已修 |
| 🟡 P2 | F-18 | `ChatView` 无卸载清理 | 生成中离开页面，SSE 仍写已销毁组件 | ✅ 已修 |
| 🟡 P2 | F-19 | SSE 流意外断开不回调终态事件 | "生成中"永久卡住，中止按钮失效 | ✅ 已修 |
| 🟢 P3 | F-20 | 工作台 `?view=` 跳转被文档页忽略 | 统计卡点击后仍显示"全部" | ✅ 已修 |
| 🟢 P3 | F-21 | `CommandPalette` 防抖定时器未清理 | 卸载后仍发请求 | ✅ 已修 |
| 🟢 P3 | F-22 | `MermaidDiagram` 用 `securityLevel: 'loose'` 渲染 AI 代码 | 注入面 + 失败后重渲染空白 | ✅ 已修 |
| 🟢 P3 | F-23 | `SearchView` `!== null` 判断漏 `undefined` | 显示"关键词 undefined" | ✅ 已修 |
| 🟢 P3 | F-24 | `DocumentDetailView` 高亮定时器未清理 | 卸载后改动已销毁状态 | ✅ 已修 |
| 🟢 P3 | F-25 | 取消对话框产生 unhandled rejection（4 个页面） | 控制台报错 | ✅ 已修 |
| 🟢 P3 | F-26 | `LearningView` / `DevHelperView` 单接口失败整页挂死 | 页面白屏 | ✅ 已修（`allSettled`） |
| 🟠 P1 | F-27 | 用例 `test_scan_reports_orphan_file` 会**收录目录中所有**未收录文件 | 一次文件残留就让知识库从 **3 篇膨胀到 66 篇**，后续用例变慢/失败 | ✅ 已修（基线守卫 + skip） |
| 🟠 P1 | F-28 | 「一并收录未收录文件」没有数量上限 | 目录里堆上百个文件时请求长时间挂起，超时后留下"收了一半"的状态 | ✅ 已修（上限 200，超出明确 422） |

---

## 二、最有价值的一条：把"漏表"变成自动化防线

`glossary_terms` / `quiz_records`（10-11 排查）与 `note_revisions`（本轮）**是同一类错误的第二次复发**：
备份表清单是硬编码的，新增表时靠人记得同步。

本轮除了补表，更关键的是加了**会自己失败的断言**：

```python
# tests/test_audit_fixes_2026_10_12.py
dumped   = {name for name, _ in backup_service.DUMP_TABLES} | {"document_tags"}
expected = {t.name for t in Base.metadata.sorted_tables}
assert not (expected - dumped), f"以下表未纳入备份清单：{sorted(expected - dumped)}"
```

今后任何人新增一张表却忘了登记，`pytest` 会立即指出表名——这类缺陷不再依赖人工排查。

---

## 三、第二类系统性风险：测试反过来污染了知识库（本次排查中最值得记录的一条）

排查过程中反复出现「全绿 → 突然 2~3 个用例失败 → 再跑又全绿」，一度以为是随机抖动。
追下去发现是一条**完整的破坏链**：

```
系统拦截文件删除（>50 个/次 触发「安全删除」保护）
        ↓
用例 purge 时文件删不掉 → data/documents 里堆下残留文件（孤儿）
        ↓
test_scan_reports_orphan_file 调用 register_orphans=true
        ↓
该接口按设计会收录目录中【所有】未收录文件
        ↓
63 个残留文件被一次性导入 → 知识库 3 篇 → 66 篇（实测，25 秒内完成）
        ↓
后续用例要在 66 篇文档上跑：批量嵌入变慢、可能超时/限流 → 随机失败
```

- **实测证据**：`select count(*) from documents` 一度为 66，其中 63 篇的标题是
  `^[0-9a-f]{32}\.md$`（纯 UUID 文件名），`created_at` 全部落在 **11:04:49–11:05:14** 的 25 秒窗口内，
  与一次 `register_orphans` 调用完全吻合；同时 `data/documents` 有 66 个文件、
  其中 63 个在数据库里没有对应记录。
- **恢复**：把 63 行按 id 备份到 `data/backups/_test_debris_backup_2026-10-12.json` 后删除，
  分批清掉 63 个孤儿文件；数据库与数据目录都回到 `3 篇 / 146 片段 / 3 个文件`。
- **修复（两层）**：
  1. **用例层**：`test_scan_reports_orphan_file` 先读基线，若目录里已有未收录文件就 `skip`
     并说明原因——**宁可跳过，也不把环境残留导入用户的知识库**；
     同时把断言收紧为 `orphan_count == 1` / `len(registered) == 1`，环境不干净时立刻暴露。
  2. **产品层**：`register_orphans` 增加上限 `MAX_REGISTER_ORPHANS = 200`，超出直接 422
     并给出「分批处理或改用导入页」的指引，避免请求挂起后留下半成品。
- **顺带修掉的环境坑**：pytest 清理 `%TEMP%` 下的旧临时目录时会触发同一套删除保护，
  导致测试进程**被中途掐断且不打印任何失败详情**（只见 `F` 不见 traceback）。
  解决办法是固定临时目录：`pytest tests --basetemp=.pytest_tmp`。
  **这是本机跑测试的必需参数**，已写入 README 并加入 `.gitignore`。

> 结论：这条链之所以危险，是因为**每一步本身都是"正确设计"**——
> 产品尊重用户显式确认、删除保护防止误删、用例自建自清。
> 问题出在它们叠加时，一个环境异常会被放大成"知识库被批量注入垃圾"。
> 因此修法不是推翻任何一步，而是给最危险的那一步（批量收录）加上**上限**与**前置检查**。

---

## 四、回归用例（新增 10 例）

`backend/tests/test_audit_fixes_2026_10_12.py`

| 用例 | 断言 |
|---|---|
| `test_backup_covers_note_revisions` | 转储与清空清单都含 `note_revisions` |
| `test_backup_covers_every_registered_table` | **自动**比对 `Base.metadata` 与备份清单 |
| `test_dump_is_referentially_complete` | 每行带全列；`chunks`/`note_links`/`note_revisions` 的外键在转储内可解析 |
| `test_clear_order_deletes_children_before_parents` | `note_revisions`/`chunks` 先于 `documents`；`review_logs` 先于 `flashcards` |
| `test_validate_dump_rejects_incomplete_backup` | `{}`、非对象、非数组一律 422；缺 `note_revisions` 的旧备份仍放行 |
| `test_bad_uuid_returns_422_not_503` | 3 个接口的非法 id → 422 |
| `test_learning_invalid_params_return_422` | 缺 `document_id` / `rating="abc"` / `count="x"` → 422 |
| `test_pick_chunks_excludes_private_and_deleted` | 私密 → 排除；开关打开 → 纳入；移入回收站 → 再次排除 |
| `test_tag_counts_exclude_trashed_documents` | 软删除后标签计数归 0 |
| `test_mass_orphan_registration_is_capped` | 超出上限时返回 422 且**不导入任何文件** |

---

## 五、本轮**未**处理（明确留待后续）

1. **测试未隔离**：`tests/` 直连真实库与真实 `data/`，靠"自建自清"。
   本次已给最危险的用例加了守卫，但**根治需要独立的测试库与测试数据目录**
   （每用例事务回滚或独立 schema）——注意两者必须同时隔离：
   只换 `DATA_DIR` 而共用数据库，会让库中记录的相对路径指向不存在的文件。
2. **备份/恢复真实往返仍未演练**：`test_backup_restore_roundtrip_and_orphan_cleanup`
   在库中有数据时会 `skip`，日常从未执行。需在**空库**环境单独跑一次。
3. **文件删除受系统保护时会产生残留**：`delete_file()` 是"尽力删除、绝不抛异常"（刻意设计），
   残留文件靠「扫描同步」可见。本机需注意 `data/documents` 与 `data/exports` 的堆积。
4. **前端错误提示可能重复**：拦截器与页面各弹一次，需要"静默请求"约定来统一。
5. **`GraphView` RAF 循环**在报错后仍绘制旧数据，且重复点击"刷新"无在途保护。

---

## 六、验证汇总

| 验证项 | 结果 |
|---|---|
| 后端测试 | **86 passed, 1 skipped**（原 76 + 新增 10） |
| 连续重跑 | 3 次均全绿，且 `data/documents` 保持 3 个文件（无残留） |
| 前端类型检查 `vue-tsc -b` | 退出码 0 |
| 前端生产构建 `vite build` | 成功（DOMPurify 正确打包） |
| `alembic check` | No new upgrade operations detected |
| 数据库/磁盘一致性 | `documents=3`、`chunks=146`、`data/documents` 3 个文件 |

