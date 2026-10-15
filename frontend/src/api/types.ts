// ===== 与后端 schema 对应的类型定义 =====

export type DocStatus = 'pending' | 'processing' | 'indexed' | 'partial' | 'failed'
export type AnswerMode = 'detail' | 'brief' | 'example'
export type SearchMode = 'keyword' | 'semantic' | 'hybrid'
/** 检索排序：相关度 / 更新时间 / 创建时间 */
export type SearchSort = 'relevance' | 'updated' | 'created'
/** 文档列表视图：全部 / 收藏 / 置顶 / 最近访问 / 我的笔记 */
export type DocumentView = 'all' | 'favorite' | 'pinned' | 'recent' | 'note'

export interface DocumentOut {
  id: string
  title: string
  original_filename: string
  file_type: string
  file_size: number
  status: DocStatus
  error_message?: string | null
  chunk_count: number
  category_id?: string | null
  /** 文档上挂载的标签（后端 DocumentOut 已带）。 */
  tags?: { id: string; name: string }[]
  /** upload = 导入的文件；note = 应用内新建或编辑过。 */
  source?: string
  is_favorite?: boolean
  is_pinned?: boolean
  /** 是否允许进入 AI 检索范围（false 表示私密笔记）。 */
  ai_enabled?: boolean
  last_viewed_at?: string | null
  deleted_at?: string | null
  created_at: string
  updated_at: string
}

export interface DocumentDetail extends DocumentOut {
  content_text?: string | null
  /** 正文指纹（sha256）：编辑器保存时原样回传，用作乐观锁基线 */
  content_hash: string
}

export interface DocumentListOut {
  total: number
  page: number
  page_size: number
  items: DocumentOut[]
}

/** 正文历史版本（列表不含全文）。 */
export interface RevisionOut {
  id: string
  document_id: string
  title: string
  char_count: number
  note?: string | null
  created_at: string
}

export interface RevisionDetail extends RevisionOut {
  content_text?: string | null
}

/** 知识片段（引用定位用）。 */
export interface ChunkOut {
  id: string
  chunk_index: number
  heading?: string | null
  page_no?: number | null
  content: string
  token_count: number
  has_embedding: boolean
}

export interface Category {
  id: string
  name: string
  description?: string | null
  /** 多级文件夹：为空表示根分类。 */
  parent_id?: string | null
  created_at: string
  updated_at: string
  document_count: number
}

export interface Tag {
  id: string
  name: string
  created_at: string
  document_count: number
}

export interface GlossaryTerm {
  id: string
  term: string
  definition: string
  aliases?: string[] | null
  category?: string | null
  created_at: string
  updated_at: string
}

export interface SearchHit {
  document_id: string
  document_title: string
  chunk_id: string
  heading?: string | null
  page_no?: number | null
  snippet: string
  score: number
  keyword_score?: number | null
  semantic_score?: number | null
  /** 父子检索：命中片段所属父块的完整内容（用于「展开上下文」）。 */
  parent_id?: string | null
  parent_content?: string | null
  /** 命中的查询词，前端据此在 snippet 中高亮。 */
  highlights?: string[]
  /** 所属文档的更新时间/创建时间，用于按时间排序。 */
  document_updated_at?: string | null
  document_created_at?: string | null
}

export interface SearchResponse {
  query: string
  mode: SearchMode
  total: number
  hits: SearchHit[]
}

/** 保存的检索条件（智能集合）。 */
export interface SavedSearchOut {
  id: string
  name: string
  /** 筛选条件原文，字段与检索请求对齐 */
  params: {
    query?: string
    mode?: string
    category_id?: string | null
    tags?: string[] | null
    sort?: string
    date_from?: string | null
    date_to?: string | null
    top_k?: number
  }
  created_at?: string | null
  updated_at?: string | null
}

/** 联网补充信息的一条结果（真实链接，来自联网检索）。 */
export interface WebResult {
  title: string
  url: string
  snippet: string
}

export interface MessageOut {
  id: string
  role: string
  content: string
  sources?: SearchHit[] | null
  source_type?: string | null
  /** 联网结果仅随流式响应返回，不落库；重开会话后为 undefined。 */
  web_results?: WebResult[] | null
  /** 推理模型的思考过程（可空），用于折叠展示，不计入回答正文。 */
  reasoning?: string | null
  created_at: string
}

export interface ConversationOut {
  id: string
  title: string
  mode: AnswerMode
  created_at: string
  updated_at: string
  message_count: number
}

export interface ConversationDetail extends ConversationOut {
  messages: MessageOut[]
}

export interface SettingsOut {
  ai_mode: string
  local_model_base_url: string
  external_api_base_url: string
  has_external_key: boolean
  chat_model: string
  embedding_model: string
  embedding_dim: number
  embedding_base_url: string
  has_embedding_key: boolean
  request_timeout: number
  data_dir: string
  max_upload_mb: number
  hybrid_alpha: number
  hybrid_beta: number
  search_top_k: number
  chunk_mode: string
  parent_child_enabled: boolean
  storage_mode: string
  default_answer_mode: string
  web_search_enabled: boolean
  web_search_provider: string
  web_search_api_url: string
  web_search_top_k: number
  has_web_search_key: boolean
  /** LLM 重排序：检索后用对话模型精排（更准但更慢、更费额度） */
  rerank_enabled: boolean
  /** 送入重排的候选片段数 */
  rerank_candidates: number
  /** 回收站保留天数：0 = 永不自动清理 */
  trash_retention_days: number
}

export interface IndexStatus {
  document_total: number
  indexed: number
  partial: number
  pending: number
  processing: number
  failed: number
  chunk_total: number
  embedded_chunks: number
  /** 应用内新建的笔记数 */
  note_total?: number
  /** 回收站中的文档数 */
  trash_total?: number
}

export interface HealthOut {
  status: string
  database_ok: boolean
  database_message: string
  storage_mode: string
  ai_mode: string
  data_dir: string
}

// ===== 扩展模块：AI 知识加工 =====

export interface ChunkBrief {
  chunk_id: string
  document_id: string
  document_title: string
  heading: string | null
  snippet: string
}

export interface DuplicatePair {
  distance: number
  similarity: number
  same_document: boolean
  left: ChunkBrief
  right: ChunkBrief
}

export interface RelatedDocument {
  document_id: string
  document_title: string
  chunk_count: number
  similarity: number
}

export interface OrganizeSuggestion {
  document_id: string
  current_title: string
  suggested_title: string
  category: string
  tags: string[]
  summary: string
  reason: string
  note: string
}

// ===== 扩展模块：学习辅助 =====

export interface QuizQuestion {
  question: string
  reference_answer: string
  source_chunk_id: string | null
  source_document_id: string | null
  source_document_title: string | null
}

export interface QuizQuestionSet {
  mode: string
  direction: string | null
  difficulty: string
  total: number
  questions: QuizQuestion[]
  note: string
}

export interface GradeResult {
  record_id: string
  score: number
  passed: boolean
  feedback: string | null
  missing: string[]
  note: string
}

export interface QuizRecord {
  id: string
  question: string
  reference_answer: string | null
  user_answer: string | null
  score: number | null
  feedback: string | null
  direction: string | null
  difficulty: string | null
  mastered: boolean
  missing: string[]
  source_document_id: string | null
  created_at: string
}

export interface ReviewStats {
  total_answered: number
  mistakes: number
  mistakes_pending: number
  mastered: number
  average_score: number
  pass_score: number
}

// ===== 扩展模块：项目开发辅助 =====

export interface ReviewPoint {
  point: string
  basis?: string
  reason?: string
  level?: string
}

export interface CodeReviewResult {
  language: string | null
  from_knowledge: ReviewPoint[]
  suggestions: ReviewPoint[]
  summary: string
  context_count: number
  note: string
}

export interface TroubleshootCause {
  cause: string
  basis?: string
  verify?: string
  action?: string
}

export interface TroubleshootResult {
  confirmed: TroubleshootCause[]
  possible: TroubleshootCause[]
  need_more_info: string[]
  context_count: number
  note: string
}

export interface BreakdownTask {
  title: string
  detail?: string
  acceptance?: string
  basis?: string
}

export interface BreakdownResult {
  goal: string
  tasks: BreakdownTask[]
  risks: string[]
  assumptions: string[]
  context_count: number
  note: string
}

export interface TimelineEvent {
  date: string
  date_known: boolean
  event: string
  source: string
}

export interface TimelineResult {
  documents: string[]
  total: number
  events: TimelineEvent[]
  undated: number
  note: string
}

// ===== 工作区：工作台 / 每日笔记 / 模板 / 扫描 =====

/** 笔记简要信息（工作台列表用）。 */
export interface NoteBrief {
  id: string
  title: string
  source: string
  status: DocStatus
  chunk_count: number
  category_id?: string | null
  is_favorite?: boolean
  is_pinned?: boolean
  ai_enabled?: boolean
  updated_at?: string | null
  created_at?: string | null
  last_viewed_at?: string | null
}

export interface WorkbenchCounts {
  documents: number
  notes: number
  favorites: number
  inbox: number
  trash: number
  failed: number
  private: number
}

/** 体检清单条目（孤立 / 从未访问 / 陈旧 / 未索引）的共有字段。 */
export interface KbHealthItem {
  document_id: string
  title: string
  source?: string | null
  chunk_count?: number | null
  created_at?: string | null
  updated_at?: string | null
  last_viewed_at?: string | null
  days_since_created?: number | null
  /** 仅 unindexed 项有 */
  status?: string
  error_message?: string | null
}

/** 悬空链接：指向不存在笔记的 [[双链]]，是「本打算写但忘了」的坑。 */
export interface DanglingLink {
  target_title: string
  source_document_id: string
  source_document_title: string
}

export interface KbHealthSummary {
  total: number
  orphans: number
  never_viewed: number
  inbox: number
  stale_inbox: number
  unindexed: number
  dangling_links: number
  favorites: number
  /** 重复片段对数；嵌入服务不可用时为 null（其余项不受影响） */
  duplicate_pairs: number | null
  /** 关联率：至少参与一条双链的文档占比；无文档时为 null */
  linked_ratio: number | null
}

export interface KbHealthOut {
  summary: KbHealthSummary
  orphans: KbHealthItem[]
  never_viewed: KbHealthItem[]
  stale_inbox: KbHealthItem[]
  unindexed: KbHealthItem[]
  dangling: DanglingLink[]
  thresholds: { stale_inbox_days: number }
  note: string
}

/** 归一化矩形：相对页面可视区左上角，0..1，与缩放/旋转无关。 */
export interface AnnotationRect {
  x: number
  y: number
  w: number
  h: number
}

/** 一条 PDF 高亮/批注。`quote` 是主锚（坐标丢了靠它重新定位）。 */
export interface PdfAnnotation {
  id: string
  document_id: string
  page_no: number
  quote: string
  prefix: string | null
  suffix: string | null
  rects: AnnotationRect[]
  rotation: number
  color: string
  comment: string | null
  created_at: string
  updated_at: string
}

export interface AnnotationListOut {
  /** 该文档**全部**批注数（按页过滤时 items 变少但 total 不变） */
  total: number
  items: PdfAnnotation[]
}

export interface AnnotationExportOut {
  document_id: string
  title: string
  annotation_count: number
  /** true = 新建了笔记；false = 更新了此前导出的那一篇（导出是幂等的） */
  created: boolean
}

export interface WorkbenchOut {
  recent_edited: NoteBrief[]
  recent_viewed: NoteBrief[]
  inbox: NoteBrief[]
  favorites: NoteBrief[]
  counts: WorkbenchCounts
  chunk_total: number
  daily_note?: NoteBrief | null
  daily_title: string
  /** 启动时的只读扫描结果（未做任何改动）；null 表示未扫描或扫描失败 */
  startup_scan?: {
    changed_count: number
    missing_count: number
    orphan_count: number
    scanned_at: string
  } | null
}

/** 一条出链。 */
export interface NoteLinkOut {
  link_id: string
  target_title: string
  target_document_id?: string | null
  target_document_title?: string | null
  resolved: boolean
  /** 块级引用锚点：`[[标题#小节]]` 中 `#` 后的部分；为空表示引用整篇 */
  target_anchor?: string | null
  /** 是否是嵌入引用 `![[标题]]`（语义与渲染都不同于普通链接） */
  is_embed?: boolean
}

/** 一条反向链接。 */
export interface BacklinkOut {
  link_id: string
  source_document_id: string
  source_document_title: string
  target_title: string
  target_anchor?: string | null
  is_embed?: boolean
}

export interface LinkSummary {
  outgoing: NoteLinkOut[]
  backlinks: BacklinkOut[]
  unresolved: NoteLinkOut[]
  outgoing_count: number
  backlink_count: number
  unresolved_count: number
}

export interface TemplateOut {
  name: string
  filename: string
  size: number
  updated_at: string
}

export interface ScanItem {
  document_id?: string
  title?: string
  file_path: string
  db_size?: number
  disk_size?: number
  filename?: string
  size?: number
}

export interface ScanResult {
  changed: ScanItem[]
  missing: ScanItem[]
  orphan: ScanItem[]
  changed_count: number
  missing_count: number
  orphan_count: number
  applied: { reindexed: number; registered: string[] }
  note: string
}

// ===== 多级分类 =====

export interface CategoryTreeNode extends Category {
  children: CategoryTreeNode[]
  /** 含子孙分类的总文档数 */
  total_count: number
}

// ===== 闪卡与间隔复习（SRS）=====

export type CardState = 'new' | 'learning' | 'review'

export interface Flashcard {
  id: string
  front: string
  back: string
  document_id?: string | null
  source_chunk_id?: string | null
  tags?: string[]
  state: CardState
  ease: number
  interval_days: number
  repetitions: number
  lapses: number
  due_at?: string | null
  last_reviewed_at?: string | null
  suspended: boolean
  created_at?: string | null
}

export interface ReviewLogItem {
  id: string
  rating: number
  prev_interval: number
  next_interval: number
  ease_after: number
  reviewed_at?: string | null
}

export interface SrsStats {
  total: number
  due: number
  new: number
  learning: number
  review: number
  suspended: number
  reviewed_today: number
  streak_days: number
  reviewed_days: number
  /** 近两周每日复习量（含 0 的日期），用于趋势图 */
  daily: { date: string; count: number }[]
  /** 掌握程度分布：按当前复习间隔分档 */
  mastery: { label: string; count: number }[]
  /** 遗忘曲线：按间隔分档的实际回忆成功率。
   *  rate 为 null 表示该档位还没有复习数据（区别于 0 —— 「全忘」） */
  retention: { label: string; attempts: number; passed: number; rate: number | null }[]
}

// ===== 附件 =====

export interface AttachmentOut {
  name: string
  sub: string
  size: number
  url: string
}

export interface AttachmentUploadResult {
  path: string
  url: string
  markdown: string
  size: number
  filename: string
  kind: 'image' | 'file'
}

// ===== 知识图谱 =====

export interface GraphNode {
  id: string
  title: string
  source: string
  category_id?: string | null
  category_name?: string | null
  chunk_count: number
  ai_enabled: boolean
  updated_at?: string | null
  /** 度数：用于决定节点半径，枢纽笔记一眼可见 */
  degree: number
}

export interface GraphEdge {
  source: string
  target: string
  kind: 'link' | 'tag'
  weight: number
}

export interface GraphStats {
  node_count: number
  edge_count: number
  link_edges: number
  tag_edges: number
  isolated: number
  focus_id?: string | null
  include_tags: boolean
}

export interface GraphOut {
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: GraphStats
}

// ===== 笔记页内 AI 助手 =====

export type AssistAction = 'explain' | 'summarize' | 'cards' | 'related'

export interface AssistResult {
  action: AssistAction
  text: string
  /** explain / summarize 的文本结果 */
  result?: string
  /** cards 生成的卡片 */
  cards?: Flashcard[]
  count?: number
  /** related 命中的知识片段 */
  related?: SearchHit[]
}
