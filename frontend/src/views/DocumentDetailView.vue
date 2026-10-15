<template>
  <div class="page" v-loading="loading">
    <div class="head">
      <el-button link @click="$router.back()"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
      <span class="head-spacer" />
      <template v-if="doc">
        <el-button
          v-if="isEditable"
          type="primary"
          size="small"
          @click="$router.push(`/notes/${doc.id}/edit`)"
        >
          <el-icon><EditPen /></el-icon>
          <span>编辑正文</span>
        </el-button>
        <el-button v-if="isPdf" size="small" type="primary" plain @click="openAnnotator">
          <el-icon><Reading /></el-icon>
          <span>阅读与批注{{ annotationCount ? `（${annotationCount}）` : '' }}</span>
        </el-button>
        <el-button size="small" @click="toggleFavorite">
          <el-icon :class="{ 'is-on': doc.is_favorite }">
            <StarFilled v-if="doc.is_favorite" />
            <Star v-else />
          </el-icon>
          <span>{{ doc.is_favorite ? '已收藏' : '收藏' }}</span>
        </el-button>
        <el-button size="small" @click="togglePinned">
          <el-icon :class="{ 'is-on': doc.is_pinned }"><Top /></el-icon>
          <span>{{ doc.is_pinned ? '已置顶' : '置顶' }}</span>
        </el-button>
      </template>
    </div>

    <div v-if="doc" class="card">
      <div class="title-row">
        <el-input v-model="form.title" class="title-input" />
        <el-button type="primary" @click="save">保存</el-button>
      </div>

      <el-descriptions :column="3" border size="small" class="mt">
        <el-descriptions-item label="原始文件">{{ doc.original_filename }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ doc.file_type }}</el-descriptions-item>
        <el-descriptions-item label="大小">{{ (doc.file_size / 1024).toFixed(1) }} KB</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusType(doc.status)" size="small">{{ statusText(doc.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="片段数">{{ doc.chunk_count }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ fmt(doc.updated_at) }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="doc.error_message"
        class="mt-sm"
        type="error"
        :closable="false"
        :title="`处理失败：${doc.error_message}`"
      />

      <div class="mt row">
        <el-select v-model="form.category_id" placeholder="未分类" clearable style="width: 200px">
          <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="标签（可回车新建）"
          style="min-width: 260px; flex: 1"
        >
          <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.name" />
        </el-select>
        <el-button @click="saveTags">保存标签</el-button>
        <el-button @click="suggest(false)">词频推荐</el-button>
        <el-button type="primary" plain :loading="aiSuggesting" @click="suggest(true)">
          <el-icon><MagicStick /></el-icon> AI 推荐
        </el-button>
      </div>

      <div class="mt row">
        <el-button @click="reindex">重建索引</el-button>
        <el-button @click="doExport">导出 Markdown</el-button>
        <el-button tag="a" :href="originalUrl" target="_blank">打开原始文件</el-button>
        <el-tooltip
          content="关闭后该笔记不进入 AI 检索范围（在检索阶段即被排除）"
          placement="top"
        >
          <span class="ai-toggle">
            <el-icon><MagicStick /></el-icon>
            <span>允许 AI 读取</span>
            <el-switch v-model="aiEnabled" size="small" @change="toggleAi" />
          </span>
        </el-tooltip>
        <el-button type="danger" @click="remove">移入回收站</el-button>
      </div>
    </div>

    <div v-if="doc" class="card mt">
      <div class="section-title">内容预览</div>
      <MarkdownView v-if="isMarkdownLike" :content="doc.content_text || '（无正文）'" />
      <pre v-else class="plain mono">{{ doc.content_text || '（无正文）' }}</pre>
    </div>

    <div v-if="doc" class="card mt">
      <div class="section-title">
        关联笔记
        <span class="muted">
          （反向链接 {{ linkSummary.backlink_count }} · 出链 {{ linkSummary.outgoing_count }}）
        </span>
      </div>

      <div class="link-block">
        <div class="link-block-title">反向链接（谁引用了本笔记）</div>
        <div v-if="!linkSummary.backlinks.length" class="muted-sm">
          还没有其它笔记引用本笔记。在其它笔记里写
          <code>[[{{ doc.title }}]]</code> 即可建立关联。
        </div>
        <button
          v-for="b in linkSummary.backlinks"
          :key="b.link_id"
          class="link-item"
          type="button"
          @click="$router.push(`/documents/${b.source_document_id}`)"
        >
          <el-icon><Document /></el-icon>
          <span class="link-text">{{ b.source_document_title }}</span>
        </button>
      </div>

      <div class="link-block">
        <div class="link-block-title">出链（本笔记引用了谁）</div>
        <div v-if="!linkSummary.outgoing.length" class="muted-sm">
          正文里写 <code>[[笔记标题]]</code> 即可建立双链。
        </div>
        <button
          v-for="o in linkSummary.outgoing"
          :key="o.link_id"
          class="link-item"
          :class="{ 'is-unresolved': !o.resolved }"
          type="button"
          @click="
            o.resolved && o.target_document_id && $router.push(`/documents/${o.target_document_id}`)
          "
        >
          <el-icon><Document /></el-icon>
          <span class="link-text">{{ o.target_title }}</span>
          <span v-if="!o.resolved" class="link-tag">未创建</span>
        </button>
      </div>

      <!-- 内容相近的笔记：语义相似但未必已建立双链。
           此前这个能力只在「扩展模块 → 知识加工」里、且要手动下拉选文档；
           而「读到一半发现有篇相关笔记」正是它该出现的时刻。 -->
      <div class="link-block">
        <div class="link-block-title">
          内容相近的笔记
          <span v-if="relatedLoading" class="muted-sm">读取中…</span>
        </div>

        <div v-if="relatedError" class="muted-sm">
          {{ relatedError }}
        </div>
        <div v-else-if="!relatedLoading && !related.length" class="muted-sm">
          库里还没有内容相近的笔记。
        </div>

        <button
          v-for="r in related"
          :key="r.document_id"
          class="link-item related-item"
          type="button"
          @click="$router.push(`/documents/${r.document_id}`)"
        >
          <el-icon><Document /></el-icon>
          <span class="link-text">{{ r.document_title }}</span>
          <!-- 相似度条：只看数字不好判断“多像”，给个视觉刻度 -->
          <span class="related-bar" :title="`相似度 ${(r.similarity * 100).toFixed(0)}%`">
            <i :style="{ width: relatedPct(r.similarity) + '%' }" />
          </span>
          <span class="related-pct">{{ (r.similarity * 100).toFixed(0) }}%</span>
          <!-- 已建立双链的标出来，剩下的就是「值得建立但还没建」的候选 -->
          <span v-if="isLinked(r.document_id)" class="link-tag is-linked">已双链</span>
          <span v-else class="link-tag is-candidate">未关联</span>
        </button>

        <div v-if="related.length" class="muted-sm related-hint">
          标「未关联」的说明内容相近但正文里还没写 <code>[[双链]]</code>，
          可到编辑器用「关联」按钮补上。
        </div>
      </div>
    </div>

    <div v-if="doc" class="card mt">
      <div class="section-title">
        知识片段
        <span class="muted">（共 {{ chunks.length }} 个，检索与引用定位的最小单元）</span>
      </div>
      <div v-if="!chunks.length" class="empty-chunks">
        尚未生成片段。若文档状态为「失败」或「部分索引」，可点击上方「重建索引」生成。
      </div>
      <div v-else class="chunk-list">
        <div
          v-for="c in chunks"
          :key="c.id"
          :id="`chunk-${c.id}`"
          class="chunk-item"
          :class="{ 'is-target': c.id === targetChunkId }"
        >
          <div class="chunk-head">
            <span class="chunk-index">#{{ c.chunk_index + 1 }}</span>
            <el-tag v-if="c.heading" size="small" effect="plain">{{ c.heading }}</el-tag>
            <el-tag v-if="c.page_no" size="small" effect="plain">第 {{ c.page_no }} 页</el-tag>
            <el-tag size="small" :type="c.has_embedding ? 'success' : 'info'" effect="plain">
              {{ c.has_embedding ? '已向量化' : '仅关键词' }}
            </el-tag>
            <span class="muted">{{ c.token_count }} tokens</span>
          </div>
          <div class="chunk-body">{{ c.content }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { annotationsApi, categoriesApi, documentsApi, insightsApi, tagsApi } from '@/api'
import type {
  Category,
  ChunkOut,
  DocumentDetail,
  LinkSummary,
  RelatedDocument,
  Tag,
} from '@/api/types'
import MarkdownView from '@/components/MarkdownView.vue'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const route = useRoute()
const router = useRouter()
const id = route.params.id as string

const loading = ref(false)
const doc = ref<DocumentDetail | null>(null)
const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])
const chunks = ref<ChunkOut[]>([])
/** 双向链接：出链 + 反向链接。 */
const linkSummary = ref<LinkSummary>({
  outgoing: [],
  backlinks: [],
  unresolved: [],
  outgoing_count: 0,
  backlink_count: 0,
  unresolved_count: 0,
})
// 引用定位目标片段（来自 ?chunk=<id>）
const targetChunkId = ref<string | null>(null)
let highlightTimer: number | null = null

onBeforeUnmount(() => {
  // 高亮定时器必须随组件一起清理，否则会在卸载后改动已销毁的状态
  if (highlightTimer !== null) window.clearTimeout(highlightTimer)
  highlightTimer = null
})

const form = reactive({
  title: '',
  category_id: null as string | null,
  tags: [] as string[],
})

const originalUrl = computed(() => documentsApi.originalUrl(id))

/** 可在应用内编辑的纯文本格式（二进制格式不回写磁盘，故不提供编辑入口）。 */
const TEXT_TYPES = new Set([
  'md', 'markdown', 'txt', 'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'htm', 'css',
  'json', 'yaml', 'yml', 'ini', 'toml', 'conf', 'cfg', 'env', 'java', 'go', 'rs',
  'c', 'cpp', 'h', 'hpp', 'cs', 'php', 'rb', 'sql', 'sh', 'bat', 'xml', 'csv', 'log',
])
const isEditable = computed(() =>
  TEXT_TYPES.has((doc.value?.file_type ?? '').toLowerCase()),
)

/** 是否允许该笔记进入 AI 检索范围。 */
const aiEnabled = ref(true)

async function toggleFavorite() {
  if (!doc.value) return
  const next = !doc.value.is_favorite
  const updated = await documentsApi.setFavorite(id, next)
  doc.value.is_favorite = updated.is_favorite
  ElMessage.success(next ? '已加入收藏' : '已取消收藏')
}

async function togglePinned() {
  if (!doc.value) return
  const next = !doc.value.is_pinned
  const updated = await documentsApi.setPinned(id, next)
  doc.value.is_pinned = updated.is_pinned
  ElMessage.success(next ? '已置顶' : '已取消置顶')
}

async function toggleAi(value: string | number | boolean) {
  const enabled = Boolean(value)
  try {
    const updated = await documentsApi.update(id, { ai_enabled: enabled })
    doc.value = { ...(doc.value as DocumentDetail), ai_enabled: updated.ai_enabled }
    ElMessage.success(
      enabled ? '已允许 AI 读取该笔记' : '已设为私密：AI 检索阶段将排除该笔记',
    )
  } catch {
    aiEnabled.value = !enabled
  }
}
const isMarkdownLike = computed(() =>
  ['md', 'markdown', 'txt'].includes(doc.value?.file_type ?? ''),
)

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

/**
 * 是否是带「页」结构的 PDF。
 *
 * 只有 PDF 才有批注——批注的锚点是「页号 + 引文 + 归一化矩形」，
 * 普通笔记没有页这一层。所以在详情页里把这个入口限制给 PDF。
 */
const isPdf = computed(
  () => (doc.value?.file_type || '').toLowerCase().replace(/^\./, '') === 'pdf',
)
const annotationCount = ref(0)

function openAnnotator() {
  router.push(`/documents/${id}/annotate`)
}

/** 批注数只用于在按钮上显示「（N）」；失败静默，不影响页面其余部分 */
async function loadAnnotationCount() {
  if (!isPdf.value) return
  try {
    annotationCount.value = (await annotationsApi.list(id)).total
  } catch {
    /* 忽略 */
  }
}

async function load() {
  loading.value = true
  try {
    doc.value = await documentsApi.get(id)
    form.title = doc.value.title
    form.category_id = doc.value.category_id ?? null
    aiEnabled.value = doc.value.ai_enabled !== false
    const t = await tagsApi.list()
    tags.value = t
    chunks.value = await documentsApi.chunks(id)
    // 记录一次访问，供「最近访问」列表使用（失败不影响页面）
    documentsApi.touchViewed(id).catch(() => {})
    // 双向链接（失败不影响页面）；相关笔记要等出链拿到后再去重，故串在后面
    loadLinks().then(loadRelated)
    // 批注数（仅 PDF；失败静默）
    loadAnnotationCount()
  } finally {
    loading.value = false
  }
}

async function loadLinks() {
  try {
    linkSummary.value = await documentsApi.links(id)
  } catch {
    /* 忽略 */
  }
}

// ---------------- 内容相近的笔记 ----------------
const related = ref<RelatedDocument[]>([])
const relatedLoading = ref(false)
const relatedError = ref('')

/**
 * 拉取语义相近的文档。
 *
 * 该接口依赖**向量**，嵌入服务不可用时会失败——这种情况给出明确提示而不是
 * 静默空列表，否则用户会以为「知识库里真没有相关笔记」。
 */
async function loadRelated() {
  relatedLoading.value = true
  relatedError.value = ''
  try {
    const res = await insightsApi.related(id, 6)
    // 排除已在出链/反链里出现过的，避免同一篇笔记在「关联笔记」卡片里出现两次
    const linkedIds = new Set(
      linkSummary.value.outgoing.map((o) => o.target_document_id).filter(Boolean) as string[],
    )
    linkedIds.add(id)
    related.value = res.items.filter((r) => !linkedIds.has(r.document_id))
  } catch {
    relatedError.value = '内容相近的笔记需要语义向量，当前嵌入服务不可用或该笔记尚未建立索引。'
    related.value = []
  } finally {
    relatedLoading.value = false
  }
}

/** 相似度条宽度：0.3 以下基本不相关，映射到 0%；0.9 以上给满格。 */
function relatedPct(similarity: number) {
  const lo = 0.3
  const hi = 0.9
  const v = Math.min(1, Math.max(0, (similarity - lo) / (hi - lo)))
  return Math.round(v * 100)
}

/** 该文档是否已在出链里（用于区分「已双链」与「未关联」候选）。 */
function isLinked(documentId: string) {
  return linkSummary.value.outgoing.some((o) => o.target_document_id === documentId)
}

/**
 * 引用定位：URL 带 ?chunk=<片段ID> 时滚动到该片段并短暂高亮。
 * 片段不存在（如已重建索引导致 ID 变化）时静默跳过，不影响页面其余功能。
 */
async function locateChunk() {
  const target = (route.query.chunk as string | undefined) ?? null
  if (!target) return
  targetChunkId.value = target
  await nextTick()
  const el = document.getElementById(`chunk-${target}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (highlightTimer !== null) window.clearTimeout(highlightTimer)
  highlightTimer = window.setTimeout(() => {
    if (targetChunkId.value === target) targetChunkId.value = null
    highlightTimer = null
  }, 3000)
}

/** 块级引用定位：URL 带 ?h=<锚点> 时滚动到包含该小节的片段并高亮。
 *
 * 从 `[[标题#小节]]` 点进来会带这个参数。
 *
 * 注意详情页把正文按**片段**展示（不是渲染后的 Markdown），并没有 h1~h6 元素，
 * 所以这里是按「片段文本里出现该小节名」来定位，取第一个匹配的片段。
 * 匹配前去掉 markdown 井号头与空白：链接里写 `#安装步骤`，
 * 正文里实际是 `## 安装步骤`，两者应视为同一个目标。
 */
async function locateHeading() {
  const anchor = (route.query.h as string | undefined) ?? null
  if (!anchor) return
  await nextTick()
  const wanted = anchor.trim().toLowerCase().replace(/^#+\s*/, '').replace(/\s+/g, '')
  if (!wanted) return
  const items = Array.from(document.querySelectorAll<HTMLElement>('.chunk-item'))
  const hit = items.find((el) => {
    const text = (el.textContent || '').toLowerCase().replace(/\s+/g, '')
    return text.includes(wanted)
  })
  if (!hit) return
  hit.scrollIntoView({ behavior: 'smooth', block: 'center' })
  hit.classList.add('is-anchor-target')
  window.setTimeout(() => hit.classList.remove('is-anchor-target'), 2600)
}

async function save() {
  await documentsApi.update(id, { title: form.title, category_id: form.category_id })
  ElMessage.success('已保存')
  load()
}

async function saveTags() {
  await tagsApi.setDocumentTags(id, form.tags)
  ElMessage.success('标签已保存')
  tags.value = await tagsApi.list()
}

const aiSuggesting = ref(false)

/**
 * 推荐标签。
 * useAi=true 时调用对话模型按文档主题生成（更准，需已配置模型）；
 * false 时走词频启发式（快、不消耗额度）。
 * 两者都只是「建议」，需用户点「保存标签」才生效。
 */
async function suggest(useAi = false) {
  if (useAi) aiSuggesting.value = true
  try {
    const res = await tagsApi.suggest({ document_id: id, limit: 8, use_ai: useAi })
    if (!res.suggestions.length) {
      ElMessage.info('未生成标签建议')
      return
    }
    form.tags = Array.from(new Set([...form.tags, ...res.suggestions]))
    ElMessage.success(`${res.note}：${res.suggestions.join('、')}（需手动保存）`)
  } catch (err) {
    if (useAi) ElMessage.error((err as Error).message || 'AI 推荐失败，请检查模型配置')
  } finally {
    aiSuggesting.value = false
  }
}

async function reindex() {
  try {
    const res = await documentsApi.reindex(id)
    ElMessage.success(`重建完成，共 ${res.chunk_count} 个片段`)
    load()
  } catch {
    load()
  }
}

async function doExport() {
  const res = await documentsApi.export(id, 'md')
  const blob = new Blob([res.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = res.filename
  a.click()
  URL.revokeObjectURL(url)
}

async function remove() {
  await ElMessageBox.confirm(
    '该文档将移入回收站（原文件与索引保留，可随时恢复）。是否继续？',
    '移入回收站',
    { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' },
  )
  await documentsApi.remove(id)
  ElMessage.success('已移入回收站')
  router.push('/documents')
}

onMounted(async () => {
  categories.value = await categoriesApi.list()
  await load()
  await locateChunk()
  await locateHeading()
})

// 从问答页/检索页跳转到同一文档的其它片段时组件会被复用，需响应 query 变化
watch(
  () => route.query.chunk,
  () => locateChunk(),
)

// 同理：`[[标题#小节]]` 点进来后继续点另一条块级引用，要重新定位
watch(
  () => route.query.h,
  () => locateHeading(),
)
</script>

<style scoped>
.head {
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.head-spacer {
  flex: 1;
}
.ai-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--kh-text-sub);
  padding: 0 4px;
}
.is-on {
  color: #e6a23c;
}

/* ---- 关联笔记（双向链接） ---- */
.link-block {
  margin-bottom: 14px;
}

.link-block-title {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  margin-bottom: 7px;
}

.muted-sm {
  font-size: 12.5px;
  color: var(--kh-text-mute);
  line-height: 1.7;
}

.muted-sm code {
  background: var(--kh-bg-deep);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
}

.link-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 1px solid var(--kh-border-light);
  background: var(--kh-panel);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  color: var(--kh-text);
  text-align: left;
}

.link-item:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.link-item.is-unresolved {
  border-style: dashed;
  color: var(--kh-text-sub);
  cursor: default;
}

.link-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.link-tag {
  font-size: 10.5px;
  color: var(--kh-text-mute);
  border: 1px solid var(--kh-border);
  border-radius: 4px;
  padding: 0 4px;
  flex-shrink: 0;
}

/* ---------------- 内容相近的笔记 ---------------- */
.related-item {
  gap: 8px;
}

/* 相似度条：宽度按 0.3~0.9 映射，低于 0.3 不显示长度（基本不相关） */
.related-bar {
  width: 56px;
  height: 6px;
  border-radius: 3px;
  background: var(--kh-border-light);
  overflow: hidden;
  flex-shrink: 0;
}

.related-bar i {
  display: block;
  height: 100%;
  background: var(--kh-primary);
  border-radius: 3px;
}

.related-pct {
  font-size: 11.5px;
  color: var(--kh-text-sub);
  font-variant-numeric: tabular-nums;
  width: 32px;
  text-align: right;
  flex-shrink: 0;
}

/* 未关联的用醒目色：它正是「值得建立但还没建」的候选 */
.link-tag.is-candidate {
  color: #b88230;
  border-color: #e8d5b0;
  background: #fdf8ef;
}

.link-tag.is-linked {
  color: var(--kh-text-sub);
}

.related-hint {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--kh-border-light);
}

/* 窄屏：相似度条收窄，百分比保留 */
@media (max-width: 860px) {
  .related-bar {
    width: 36px;
  }
}
.title-row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.title-input :deep(input) {
  font-size: 18px;
  font-weight: 600;
}
.section-title {
  font-weight: 600;
  margin-bottom: 12px;
}
.row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.mt {
  margin-top: 16px;
}
.mt-sm {
  margin-top: 12px;
}
.plain {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60vh;
  overflow: auto;
}

/* ---- 知识片段 ---- */
.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 62vh;
  overflow: auto;
}

.chunk-item {
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--kh-panel);
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

/* 引用定位目标：短暂高亮，帮助用户快速找到对应片段 */
.chunk-item.is-target {
  border-color: var(--kh-primary);
  background: var(--kh-primary-soft);
  box-shadow: 0 0 0 3px var(--kh-primary-soft);
}

/* 块级引用定位（?h=<锚点>）：与上面的 is-target 同款高亮，类名不同以免互相覆盖 */
.chunk-item.is-anchor-target {
  border-color: var(--kh-primary);
  background: var(--kh-primary-soft);
  box-shadow: 0 0 0 3px var(--kh-primary-soft);
}

.chunk-head {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.chunk-index {
  font-weight: 600;
  color: var(--kh-primary);
  font-size: 12.5px;
}

.chunk-body {
  color: var(--kh-text);
  font-size: 13px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-chunks {
  color: var(--kh-text-sub);
  font-size: 13px;
  padding: 8px 0;
}

.muted {
  color: var(--kh-text-sub);
  font-size: 12px;
  font-weight: 400;
}
</style>
