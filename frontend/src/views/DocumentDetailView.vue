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
        <el-button @click="suggest">推荐标签</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi, documentsApi, tagsApi } from '@/api'
import type { Category, DocumentDetail, Tag } from '@/api/types'
import MarkdownView from '@/components/MarkdownView.vue'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const route = useRoute()
const router = useRouter()
const id = route.params.id as string

const loading = ref(false)
const doc = ref<DocumentDetail | null>(null)
const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])

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
  } finally {
    loading.value = false
  }
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

async function suggest() {
  const res = await tagsApi.suggest({ document_id: id, limit: 8 })
  if (!res.suggestions.length) {
    ElMessage.info('未生成标签建议')
    return
  }
  form.tags = Array.from(new Set([...form.tags, ...res.suggestions]))
  ElMessage.success(`已加入建议：${res.suggestions.join('、')}（仅供参考，需手动保存）`)
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
})
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
</style>
