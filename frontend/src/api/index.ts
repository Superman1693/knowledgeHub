import client from './client'
import type {
  AssistResult,
  AttachmentOut,
  AttachmentUploadResult,
  BreakdownResult,
  Category,
  CategoryTreeNode,
  ChunkOut,
  CodeReviewResult,
  ConversationDetail,
  ConversationOut,
  DocumentDetail,
  DocumentListOut,
  DocumentOut,
  DuplicatePair,
  Flashcard,
  GlossaryTerm,
  GradeResult,
  GraphOut,
  HealthOut,
  IndexStatus,
  LinkSummary,
  OrganizeSuggestion,
  QuizQuestionSet,
  QuizRecord,
  RelatedDocument,
  ReviewLogItem,
  ReviewStats,
  RevisionDetail,
  RevisionOut,
  SavedSearchOut,
  ScanResult,
  SearchResponse,
  SettingsOut,
  SrsStats,
  Tag,
  TemplateOut,
  TimelineResult,
  TroubleshootResult,
  WebResult,
  WorkbenchOut,
} from './types'

// ===== 文档 =====
export const documentsApi = {
  list(params: {
    page?: number
    page_size?: number
    category_id?: string | null
    tag?: string | null
    q?: string | null
    sort?: string
    /** all | favorite | pinned | recent | note */
    view?: string
  }) {
    return client.get<DocumentListOut>('/documents', { params }).then((r) => r.data)
  },
  get(id: string) {
    return client.get<DocumentDetail>(`/documents/${id}`).then((r) => r.data)
  },
  /** 新建笔记（不经过文件上传，直接写正文）。 */
  createNote(payload: {
    title: string
    content_text?: string
    category_id?: string | null
    tags?: string[] | null
    /** 是否允许进入 AI 检索范围；默认 true。私密笔记建时就该是私密。 */
    ai_enabled?: boolean
  }) {
    return client.post<DocumentDetail>('/documents/notes', payload).then((r) => r.data)
  },
  upload(files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return client
      .post<{ items: { document: DocumentDetail; duplicate_warning: boolean }[] }>(
        '/documents',
        form,
      )
      .then((r) => r.data)
  },
  /**
   * 更新文档。`opts.silent` 用于自动保存：不弹全局错误提示，
   * 让调用方自己处理（如把 409 冲突转成对比对话框）。
   */
  update(id: string, payload: Record<string, unknown>, opts?: { silent?: boolean }) {
    return client
      .put<DocumentDetail>(`/documents/${id}`, payload, { silent: opts?.silent })
      .then((r) => r.data)
  },
  /** 批量操作：delete / restore / purge / favorite / pin / move / tag（逐条返回成败）。 */
  batch(payload: {
    action: 'delete' | 'restore' | 'purge' | 'favorite' | 'pin' | 'move' | 'tag'
    ids: string[]
    category_id?: string | null
    tags?: string[] | null
    value?: boolean
  }) {
    return client
      .post<{
        action: string
        requested: number
        ok_count: number
        ok: string[]
        failed: { id: string; error: string }[]
      }>('/documents/batch', payload)
      .then((r) => r.data)
  },
  /** 移入回收站（软删除）。 */
  remove(id: string) {
    return client.delete(`/documents/${id}`).then((r) => r.data)
  },
  reindex(id: string) {
    return client.post(`/documents/${id}/reindex`).then((r) => r.data)
  },
  export(id: string, fmt = 'md') {
    return client
      .get<{ filename: string; content: string }>(`/documents/${id}/export`, {
        params: { fmt },
      })
      .then((r) => r.data)
  },
  /** 知识片段列表（引用定位与片段预览）。 */
  chunks(id: string) {
    return client.get<ChunkOut[]>(`/documents/${id}/chunks`).then((r) => r.data)
  },
  originalUrl(id: string) {
    return `/api/documents/${id}/file`
  },

  // ---- 个人知识库：收藏 / 置顶 / 最近访问 ----
  setFavorite(id: string, value: boolean) {
    return client
      .post<DocumentOut>(`/documents/${id}/favorite`, { value })
      .then((r) => r.data)
  },
  setPinned(id: string, value: boolean) {
    return client.post<DocumentOut>(`/documents/${id}/pin`, { value }).then((r) => r.data)
  },
  touchViewed(id: string) {
    return client.post<DocumentOut>(`/documents/${id}/view`).then((r) => r.data)
  },

  // ---- 回收站 ----
  trash(params: { page?: number; page_size?: number }) {
    return client.get<DocumentListOut>('/documents/trash', { params }).then((r) => r.data)
  },
  restore(id: string) {
    return client.post<DocumentOut>(`/documents/${id}/restore`).then((r) => r.data)
  },
  purge(id: string) {
    return client.delete(`/documents/${id}/purge`).then((r) => r.data)
  },
  emptyTrash() {
    return client.post<{ removed: number }>('/documents/trash/empty').then((r) => r.data)
  },

  // ---- 版本历史 ----
  revisions(id: string) {
    return client.get<RevisionOut[]>(`/documents/${id}/revisions`).then((r) => r.data)
  },
  revision(id: string, revisionId: string) {
    return client
      .get<RevisionDetail>(`/documents/${id}/revisions/${revisionId}`)
      .then((r) => r.data)
  },
  restoreRevision(id: string, revisionId: string) {
    return client
      .post<DocumentDetail>(`/documents/${id}/revisions/${revisionId}/restore`)
      .then((r) => r.data)
  },

  /** 整库导出为 Markdown 目录树（zip）。 */
  exportAll() {
    return client
      .post<{ name: string; path: string; count: number; size: number }>(
        '/documents/export-all',
      )
      .then((r) => r.data)
  },

  // ---- 双向链接 ----
  /** 出链 + 反向链接 + 未解析链接。 */
  links(id: string) {
    return client.get<LinkSummary>(`/documents/${id}/links`).then((r) => r.data)
  },
  /** 可被 `[[ ]]` 引用的笔记标题（编辑器补全用）。 */
  /** 可被 `[[ ]]` 引用的笔记标题（编辑器补全 + 正文链接点击跳转用）。
   *
   * `items` 带文档 ID：正文里的 `[[标题#锚点]]` 要变成能点的链接，
   * 必须知道标题对应的文档 ID。 */
  linkTargets() {
    return client
      .get<{
        total: number
        titles: string[]
        items: { id: string; title: string }[]
      }>('/documents/link-targets')
      .then((r) => r.data)
  },
}

// ===== 工作区：工作台 / 每日笔记 / 模板 / 扫描 =====
export const workspaceApi = {
  /** 工作台汇总：最近编辑 / 最近访问 / 待整理 / 收藏 / 计数 / 今日笔记。 */
  workbench() {
    return client.get<WorkbenchOut>('/workspace/workbench').then((r) => r.data)
  },
  /** 获取或创建今日笔记。 */
  daily() {
    return client.post<DocumentDetail>('/workspace/daily').then((r) => r.data)
  },
  templates() {
    return client
      .get<{ total: number; items: TemplateOut[] }>('/workspace/templates')
      .then((r) => r.data)
  },
  template(name: string) {
    return client
      .get<{ name: string; content: string }>(
        `/workspace/templates/${encodeURIComponent(name)}`,
      )
      .then((r) => r.data)
  },
  /** 扫描磁盘与库的差异；apply 重建索引，registerOrphans 收录未登记文件。 */
  scan(apply = false, registerOrphans = false) {
    return client
      .post<ScanResult>('/workspace/scan', null, {
        params: { apply, register_orphans: registerOrphans },
      })
      .then((r) => r.data)
  },
}

// ===== 分类 =====
export const categoriesApi = {
  list() {
    return client.get<Category[]>('/categories').then((r) => r.data)
  },
  /** 分类树（含子孙文档数）。 */
  tree() {
    return client.get<CategoryTreeNode[]>('/categories/tree').then((r) => r.data)
  },
  create(payload: { name: string; description?: string; parent_id?: string | null }) {
    return client.post<Category>('/categories', payload).then((r) => r.data)
  },
  update(
    id: string,
    payload: {
      name?: string
      description?: string
      parent_id?: string | null
      /** 显式移动到根（因为 parent_id=null 与「不修改」无法区分） */
      move_to_root?: boolean
    },
  ) {
    return client.put<Category>(`/categories/${id}`, payload).then((r) => r.data)
  },
  remove(id: string) {
    return client.delete(`/categories/${id}`).then((r) => r.data)
  },
}

// ===== 附件 =====
export const attachmentsApi = {
  list() {
    return client
      .get<{ total: number; items: AttachmentOut[] }>('/attachments')
      .then((r) => r.data)
  },
  upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client
      .post<AttachmentUploadResult>('/attachments', form)
      .then((r) => r.data)
  },
  remove(sub: string, name: string) {
    return client
      .delete(`/attachments/file/${sub}/${encodeURIComponent(name)}`)
      .then((r) => r.data)
  },
}

// ===== 标签 =====
export const tagsApi = {
  list() {
    return client.get<Tag[]>('/tags').then((r) => r.data)
  },
  create(name: string) {
    return client.post<Tag>('/tags', { name }).then((r) => r.data)
  },
  update(id: string, name: string) {
    return client.put<Tag>(`/tags/${id}`, { name }).then((r) => r.data)
  },
  remove(id: string) {
    return client.delete(`/tags/${id}`).then((r) => r.data)
  },
  suggest(payload: {
    document_id?: string
    text?: string
    limit?: number
    /** true = 调用模型按文档主题推荐；false = 词频启发式 */
    use_ai?: boolean
  }) {
    return client
      .post<{ suggestions: string[]; note: string }>('/tags/suggest', payload)
      .then((r) => r.data)
  },
  setDocumentTags(documentId: string, names: string[]) {
    return client
      .post<{ tags: string[] }>(`/tags/document/${documentId}`, { names })
      .then((r) => r.data)
  },
  /** 相似标签（用于提示可能的重复标签）。 */
  similar(name: string) {
    return client
      .get<{ similar: string[] }>('/tags/similar', { params: { name } })
      .then((r) => r.data)
  },
  /** 把该标签合并到 targetId（文档改挂目标标签，随后删除来源标签）。 */
  merge(id: string, targetId: string) {
    return client
      .post<{ merged: string; target_id: string; target_name: string; moved: number }>(
        `/tags/${id}/merge`,
        { target_id: targetId },
      )
      .then((r) => r.data)
  },
}

// ===== 术语词典 =====
export const glossaryApi = {
  list(q?: string) {
    return client.get<GlossaryTerm[]>('/glossary', { params: { q } }).then((r) => r.data)
  },
  create(payload: {
    term: string
    definition: string
    aliases?: string[] | null
    category?: string | null
  }) {
    return client.post<GlossaryTerm>('/glossary', payload).then((r) => r.data)
  },
  update(
    id: string,
    payload: {
      term?: string
      definition?: string
      aliases?: string[] | null
      category?: string | null
    },
  ) {
    return client.put<GlossaryTerm>(`/glossary/${id}`, payload).then((r) => r.data)
  },
  remove(id: string) {
    return client.delete(`/glossary/${id}`).then((r) => r.data)
  },
  lookup(text: string) {
    return client
      .post<{ terms: GlossaryTerm[]; rendered: string }>('/glossary/lookup', { text })
      .then((r) => r.data)
  },
}

// ===== 检索 =====
export const searchApi = {
  search(payload: {
    query: string
    mode?: string
    category_id?: string | null
    tags?: string[] | null
    top_k?: number
    /** relevance | updated | created */
    sort?: string
    /** 是否只检索允许 AI 读取的笔记 */
    ai_only?: boolean
    /** 按文档更新时间筛选区间（ISO 字符串） */
    date_from?: string | null
    date_to?: string | null
  }) {
    return client.post<SearchResponse>('/search', payload).then((r) => r.data)
  },
}

// ===== 保存的检索条件（智能集合） =====
export const savedSearchApi = {
  list() {
    return client.get<SavedSearchOut[]>('/saved-searches').then((r) => r.data)
  },
  create(name: string, params: SavedSearchOut['params']) {
    return client
      .post<SavedSearchOut>('/saved-searches', { name, params })
      .then((r) => r.data)
  },
  rename(id: string, name: string) {
    return client.put<SavedSearchOut>(`/saved-searches/${id}`, { name }).then((r) => r.data)
  },
  remove(id: string) {
    return client.delete(`/saved-searches/${id}`).then((r) => r.data)
  },
}

// ===== 会话与问答 =====
export const chatApi = {
  list() {
    return client.get<ConversationOut[]>('/conversations').then((r) => r.data)
  },
  create(payload: { title?: string; mode?: string }) {
    return client.post<ConversationOut>('/conversations', payload).then((r) => r.data)
  },
  get(id: string) {
    return client.get<ConversationDetail>(`/conversations/${id}`).then((r) => r.data)
  },
  update(id: string, payload: { title?: string; mode?: string }) {
    return client.patch<ConversationOut>(`/conversations/${id}`, payload).then((r) => r.data)
  },
  remove(id: string) {
    return client.delete(`/conversations/${id}`).then((r) => r.data)
  },
}

export interface SseHandlers {
  onSources?: (sources: unknown[]) => void
  onGlossary?: (terms: { term: string; definition: string; category?: string | null }[]) => void
  onWeb?: (data: { results: WebResult[]; ok: boolean; message: string }) => void
  onThinking?: (data: { text: string; chars: number }) => void
  onDelta?: (text: string) => void
  onDone?: (data: {
    message_id: string
    sources: unknown[]
    source_type?: string | null
    web_results?: WebResult[]
  }) => void
  onError?: (message: string) => void
  onAbort?: () => void
}

/** 通用 SSE 流解析（提问与重新生成共用）。 */
async function streamSse(
  url: string,
  body: unknown,
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if (signal?.aborted) {
      handlers.onAbort?.()
      return
    }
    handlers.onError?.(`请求失败：${(err as Error).message}`)
    return
  }

  if (!resp.ok || !resp.body) {
    handlers.onError?.(`请求失败：${resp.status}`)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  // 是否收到了终态事件（done / error）。缺失说明连接被意外中断。
  let terminal = false

  const dispatch = (block: string) => {
    const lines = block.split('\n')
    let event = 'message'
    // SSE 规范：多条 data: 行需用 \n 连接（直接相加会把多行 JSON 拼坏）
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5))
    }
    const data = dataLines.join('\n').trim()
    if (!data) return
    try {
      const parsed = JSON.parse(data)
      if (event === 'sources') handlers.onSources?.(parsed)
      else if (event === 'glossary') handlers.onGlossary?.(parsed)
      else if (event === 'web') handlers.onWeb?.(parsed)
      else if (event === 'thinking')
        handlers.onThinking?.({ text: parsed.text ?? '', chars: parsed.chars ?? 0 })
      else if (event === 'delta') handlers.onDelta?.(parsed.text ?? '')
      else if (event === 'done') {
        terminal = true
        handlers.onDone?.(parsed)
      } else if (event === 'error') {
        terminal = true
        handlers.onError?.(parsed.message ?? '未知错误')
      }
    } catch {
      /* 忽略解析失败片段 */
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      parts.forEach(dispatch)
    }
    // 冲刷解码器：否则结尾处一个被切开的 UTF-8 多字节字符会丢失
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
    // 流正常结束却没有 done/error：说明连接中断。
    // 必须显式报错，否则调用方的 streaming 状态会永久卡在「生成中」。
    if (!terminal) handlers.onError?.('连接中断，回答可能不完整')
  } catch (err) {
    if (signal?.aborted) {
      handlers.onAbort?.()
      return
    }
    handlers.onError?.(`读取流失败：${(err as Error).message}`)
  }
}

/** 提问（SSE 流式）。 */
export function askStream(
  conversationId: string,
  payload: { question: string; mode?: string; use_web?: boolean },
  handlers: SseHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(`/api/conversations/${conversationId}/messages`, payload, handlers, signal)
}

/** 重新生成某条 AI 回答（SSE 流式）。useWeb 传入当前联网开关状态。 */
export function regenerateStream(
  messageId: string,
  handlers: SseHandlers,
  signal?: AbortSignal,
  useWeb = false,
): Promise<void> {
  const qs = useWeb ? '?use_web=true' : ''
  return streamSse(
    `/api/messages/${messageId}/regenerate${qs}`,
    undefined,
    handlers,
    signal,
  )
}

// ===== 设置 =====
export const settingsApi = {
  get() {
    return client.get<SettingsOut>('/settings').then((r) => r.data)
  },
  update(payload: Record<string, unknown>) {
    return client.put<SettingsOut>('/settings', payload).then((r) => r.data)
  },
  testModel() {
    return client
      .post<{
        ok: boolean
        message: string
        models: string[]
        embedding_ok: boolean
        embedding_message: string
      }>('/settings/test-model')
      .then((r) => r.data)
  },
  indexStatus() {
    return client.get<IndexStatus>('/settings/index-status').then((r) => r.data)
  },
}

// ===== 备份与系统 =====
export const systemApi = {
  health() {
    return client.get<HealthOut>('/health').then((r) => r.data)
  },
  dataDir() {
    return client.get<Record<string, unknown>>('/data-dir').then((r) => r.data)
  },
  backup() {
    return client.post<Record<string, unknown>>('/backup').then((r) => r.data)
  },
  backups() {
    return client.get<{ items: { name: string; size: number }[] }>('/backups').then((r) => r.data)
  },
  restore(name: string) {
    return client.post('/restore', { name, confirm: true }).then((r) => r.data)
  },
  cleanCache() {
    return client.post('/cache/clean').then((r) => r.data)
  },
}

// ===== 扩展模块：AI 知识加工 =====
export const insightsApi = {
  /** 冗余检测：内容高度相似的片段对（纯向量计算，不消耗对话模型）。 */
  duplicates(threshold = 0.1, limit = 20) {
    return client
      .get<{ total: number; items: DuplicatePair[]; note: string }>('/insights/duplicates', {
        params: { threshold, limit },
      })
      .then((r) => r.data)
  },
  /** 跨文档关联：与指定文档内容最相近的其它文档。 */
  related(documentId: string, limit = 5) {
    return client
      .get<{ total: number; items: RelatedDocument[] }>(`/insights/related/${documentId}`, {
        params: { limit },
      })
      .then((r) => r.data)
  },
  /** 思维导图：AI 依据文档生成 Mermaid（节点取自原文）。 */
  mindmap(documentId: string) {
    return client
      .post<{ document_title: string; mermaid: string; note: string }>(
        `/insights/mindmap/${documentId}`,
      )
      .then((r) => r.data)
  },
  /** 整理归档：生成标题 / 分类 / 标签建议（不会自动应用）。 */
  organize(documentId: string) {
    return client.post<OrganizeSuggestion>(`/insights/organize/${documentId}`).then((r) => r.data)
  },
  /** 笔记页内 AI 助手：对选中文字做 解释 / 总结 / 生成卡片 / 找关联。 */
  assist(payload: {
    text: string
    action: 'explain' | 'summarize' | 'cards' | 'related'
    document_id?: string | null
    count?: number
  }) {
    return client.post<AssistResult>('/insights/assist', payload).then((r) => r.data)
  },
  /** 批量摘要：对多篇文档并发生成 AI 摘要（后端并发上限 3、单次上限 20 篇）。

  此前后端已实现但前端从未调用，等于功能不可达。 */
  batchSummary(documentIds: string[]) {
    return client
      .post<{
        total: number
        items: { document_id: string; title: string; summary: string }[]
        missing: string[]
      }>('/insights/batch-summary', { document_ids: documentIds })
      .then((r) => r.data)
  },
}

// ===== 知识图谱 =====
export const graphApi = {
  /** 关系网络：节点 + 边 + 统计。 */
  get(params: { focus_id?: string | null; include_tags?: boolean; limit?: number } = {}) {
    return client.get<GraphOut>('/graph', { params }).then((r) => r.data)
  },
}

// ===== 扩展模块：学习辅助 =====
export const learningApi = {
  questions(payload: { count?: number; direction?: string; difficulty?: string; mode?: string }) {
    return client.post<QuizQuestionSet>('/learning/questions', payload).then((r) => r.data)
  },
  grade(payload: {
    question: string
    reference_answer: string
    user_answer: string
    direction?: string
    difficulty?: string
    source_chunk_id?: string | null
    source_document_id?: string | null
  }) {
    return client.post<GradeResult>('/learning/grade', payload).then((r) => r.data)
  },
  mistakes(includeMastered = false) {
    return client
      .get<{ total: number; items: QuizRecord[] }>('/learning/mistakes', {
        params: { include_mastered: includeMastered },
      })
      .then((r) => r.data)
  },
  setMastered(recordId: string, mastered: boolean) {
    return client
      .post<QuizRecord>(`/learning/mistakes/${recordId}/mastered`, { mastered })
      .then((r) => r.data)
  },
  removeMistake(recordId: string) {
    return client.delete(`/learning/mistakes/${recordId}`).then((r) => r.data)
  },
  stats() {
    return client.get<ReviewStats>('/learning/stats').then((r) => r.data)
  },

  // ---- 闪卡与间隔复习（SRS）----
  cards(params: { due_only?: boolean; document_id?: string | null; limit?: number }) {
    return client
      .get<{ total: number; items: Flashcard[] }>('/learning/cards', { params })
      .then((r) => r.data)
  },
  createCard(payload: {
    front: string
    back: string
    document_id?: string | null
    source_chunk_id?: string | null
    tags?: string[] | null
  }) {
    return client.post<Flashcard>('/learning/cards', payload).then((r) => r.data)
  },
  generateCards(payload: { document_id: string; count?: number }) {
    return client
      .post<{ total: number; items: Flashcard[] }>('/learning/cards/generate', payload)
      .then((r) => r.data)
  },
  updateCard(cardId: string, payload: { front?: string; back?: string; suspended?: boolean }) {
    return client.put<Flashcard>(`/learning/cards/${cardId}`, payload).then((r) => r.data)
  },
  removeCard(cardId: string) {
    return client.delete(`/learning/cards/${cardId}`).then((r) => r.data)
  },
  /** 提交复习评分（0~5），按 SM-2 更新下次复习时间。 */
  reviewCard(cardId: string, rating: number) {
    return client
      .post<{ card: Flashcard; stats: SrsStats }>(`/learning/cards/${cardId}/review`, {
        rating,
      })
      .then((r) => r.data)
  },
  cardReviews(cardId: string) {
    return client
      .get<{ total: number; items: ReviewLogItem[] }>(`/learning/cards/${cardId}/reviews`)
      .then((r) => r.data)
  },
  srsStats() {
    return client.get<SrsStats>('/learning/srs-stats').then((r) => r.data)
  },
  /** 导出卡片为 Anki 文本导入格式（TSV）。
   *
   * 用 blob 接收：返回的是纯文本附件而不是 JSON，直接按 JSON 解析会失败。
   * 下载后到 Anki「文件 → 导入」选择该文件，勾选「允许 HTML」。
   */
  exportAnki(params: { document_id?: string | null; include_suspended?: boolean } = {}) {
    return client
      .get('/learning/cards/export-anki', { params, responseType: 'blob' })
      .then((r) => r.data as Blob)
  },
}

// ===== 扩展模块：项目开发辅助 =====
export const devhelperApi = {
  review(payload: { code: string; language?: string; focus?: string }) {
    return client.post<CodeReviewResult>('/devhelper/review', payload).then((r) => r.data)
  },
  troubleshoot(payload: { symptom: string; context?: string }) {
    return client.post<TroubleshootResult>('/devhelper/troubleshoot', payload).then((r) => r.data)
  },
  breakdown(payload: { requirement: string }) {
    return client.post<BreakdownResult>('/devhelper/breakdown', payload).then((r) => r.data)
  },
  timeline(payload: { document_id?: string; query?: string }) {
    return client.post<TimelineResult>('/devhelper/timeline', payload).then((r) => r.data)
  },
  timelineDates(documentId: string) {
    return client
      .get<{ dates: string[]; total: number }>(`/devhelper/timeline/dates/${documentId}`)
      .then((r) => r.data)
  },
}
