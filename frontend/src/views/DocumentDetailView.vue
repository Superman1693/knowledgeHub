<template>
  <div class="page" v-loading="loading">
    <div class="head">
      <el-button link @click="$router.back()"><el-icon><ArrowLeft /></el-icon> 返回</el-button>
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
        <el-button type="danger" @click="remove">删除文档</el-button>
      </div>
    </div>

    <div v-if="doc" class="card mt">
      <div class="section-title">内容预览</div>
      <MarkdownView v-if="isMarkdownLike" :content="doc.content_text || '（无正文）'" />
      <pre v-else class="plain mono">{{ doc.content_text || '（无正文）' }}</pre>
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
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi, documentsApi, tagsApi } from '@/api'
import type { Category, ChunkOut, DocumentDetail, Tag } from '@/api/types'
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
// 引用定位目标片段（来自 ?chunk=<id>）
const targetChunkId = ref<string | null>(null)
let highlightTimer: number | null = null

const form = reactive({
  title: '',
  category_id: null as string | null,
  tags: [] as string[],
})

const originalUrl = computed(() => documentsApi.originalUrl(id))
const isMarkdownLike = computed(() =>
  ['md', 'markdown', 'txt'].includes(doc.value?.file_type ?? ''),
)

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function load() {
  loading.value = true
  try {
    doc.value = await documentsApi.get(id)
    form.title = doc.value.title
    form.category_id = doc.value.category_id ?? null
    const t = await tagsApi.list()
    tags.value = t
    chunks.value = await documentsApi.chunks(id)
  } finally {
    loading.value = false
  }
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
  await ElMessageBox.confirm('确定删除该文档？将同时删除原始文件与索引。', '删除确认', {
    type: 'warning',
  })
  await documentsApi.remove(id)
  ElMessage.success('已删除')
  router.push('/documents')
}

onMounted(async () => {
  categories.value = await categoriesApi.list()
  await load()
  await locateChunk()
})

// 从问答页/检索页跳转到同一文档的其它片段时组件会被复用，需响应 query 变化
watch(
  () => route.query.chunk,
  () => locateChunk(),
)
</script>

<style scoped>
.head {
  margin-bottom: 10px;
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
