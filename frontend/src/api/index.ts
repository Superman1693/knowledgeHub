import client from './client'
import type {
  BreakdownResult,
  Category,
  ChunkOut,
  CodeReviewResult,
  ConversationDetail,
  ConversationOut,
  DocumentDetail,
  DocumentListOut,
  DuplicatePair,
  GlossaryTerm,
  GradeResult,
  HealthOut,
  IndexStatus,
  OrganizeSuggestion,
  QuizQuestionSet,
  QuizRecord,
  RelatedDocument,
  ReviewStats,
  SearchResponse,
  SettingsOut,
  Tag,
  TimelineResult,
  TroubleshootResult,
  WebResult,
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
  }) {
    return client.get<DocumentListOut>('/documents', { params }).then((r) => r.data)
  },
  get(id: string) {
    return client.get<DocumentDetail>(`/documents/${id}`).then((r) => r.data)
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
  update(id: string, payload: Record<string, unknown>) {
    return client.put(`/documents/${id}`, payload).then((r) => r.data)
  },
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
}

// ===== 分类 =====
export const categoriesApi = {
  list() {
    return client.get<Category[]>('/categories').then((r) => r.data)
  },
  create(payload: { name: string; description?: string }) {
    return client.post<Category>('/categories', payload).then((r) => r.data)
  },
  update(id: string, payload: { name?: string; description?: string }) {
    return client.put<Category>(`/categories/${id}`, payload).then((r) => r.data)
  },
  remove(id: string) {
    return client.delete(`/categories/${id}`).then((r) => r.data)
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
  }) {
    return client.post<SearchResponse>('/search', payload).then((r) => r.data)
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

  const dispatch = (block: string) => {
    const lines = block.split('\n')
    let event = 'message'
    let data = ''
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!data) return
    try {
      const parsed = JSON.parse(data)
      if (event === 'sources') handlers.onSources?.(parsed)
      else if (event === 'glossary') handlers.onGlossary?.(parsed)
      else if (event === 'web') handlers.onWeb?.(parsed)
      else if (event === 'thinking')
        handlers.onThinking?.({ text: parsed.text ?? '', chars: parsed.chars ?? 0 })
      else if (event === 'delta') handlers.onDelta?.(parsed.text ?? '')
      else if (event === 'done') handlers.onDone?.(parsed)
      else if (event === 'error') handlers.onError?.(parsed.message ?? '未知错误')
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
    if (buffer.trim()) dispatch(buffer)
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
