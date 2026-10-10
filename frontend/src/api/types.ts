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
}

export interface SearchResponse {
  query: string
  mode: SearchMode
  total: number
  hits: SearchHit[]
}

export interface MessageOut {
  id: string
  role: string
  content: string
  sources?: SearchHit[] | null
  source_type?: string | null
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
  storage_mode: string
  default_answer_mode: string
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
