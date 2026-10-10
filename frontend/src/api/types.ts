// ===== 与后端 schema 对应的类型定义 =====

export type DocStatus = 'pending' | 'processing' | 'indexed' | 'partial' | 'failed'
export type AnswerMode = 'detail' | 'brief' | 'example'
export type SearchMode = 'keyword' | 'semantic' | 'hybrid'

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
  created_at: string
  updated_at: string
}

export interface DocumentDetail extends DocumentOut {
  content_text?: string | null
}

export interface DocumentListOut {
  total: number
  page: number
  page_size: number
  items: DocumentOut[]
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
}

export interface SearchResponse {
  query: string
  mode: SearchMode
  total: number
  hits: SearchHit[]
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
}

export interface HealthOut {
  status: string
  database_ok: boolean
  database_message: string
  storage_mode: string
  ai_mode: string
  data_dir: string
}
