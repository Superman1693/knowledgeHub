/** 文档处理状态与标签类型的统一映射（避免各视图重复定义）。 */

export type TagType = 'success' | 'info' | 'warning' | 'danger' | 'primary'

export const DOC_STATUS_TEXT: Record<string, string> = {
  pending: '等待',
  processing: '处理中',
  indexed: '已索引',
  partial: '部分索引',
  failed: '失败',
}

export const DOC_STATUS_TYPE: Record<string, TagType> = {
  pending: 'info',
  processing: 'warning',
  indexed: 'success',
  // 已分块但未向量化：关键词检索可用，语义检索不可用
  partial: 'warning',
  failed: 'danger',
}

export const DOC_STATUS_HINT: Record<string, string> = {
  indexed: '已分块并完成向量化，关键词与语义检索均可用',
  partial: '已分块但未向量化：关键词检索可用，语义检索不可用（配置嵌入模型后重建索引即可）',
  failed: '处理失败，可在文档详情查看原因并重建索引',
}

export function docStatusText(status: string): string {
  return DOC_STATUS_TEXT[status] ?? status
}

export function docStatusType(status: string): TagType {
  return DOC_STATUS_TYPE[status] ?? 'info'
}
