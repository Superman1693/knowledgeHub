<template>
  <div class="page">
    <h2 class="page-title">文档管理</h2>
    <p class="page-sub">浏览、筛选、预览、删除与导出你的本地文档</p>

    <div class="card toolbar">
      <el-input v-model="filters.q" placeholder="搜索标题 / 文件名" clearable style="width: 220px" @keyup.enter="reload" />
      <el-select v-model="filters.category_id" placeholder="全部分类" clearable style="width: 160px" @change="reload">
        <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-select v-model="filters.tag" placeholder="全部标签" clearable style="width: 150px" @change="reload">
        <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.name" />
      </el-select>
      <el-select v-model="filters.sort" style="width: 150px" @change="reload">
        <el-option label="按更新时间" value="updated_at" />
        <el-option label="按创建时间" value="created_at" />
      </el-select>
      <el-button type="primary" @click="reload"><el-icon><Search /></el-icon>查询</el-button>
      <el-button @click="$router.push('/upload')"><el-icon><UploadFilled /></el-icon>导入</el-button>
    </div>

    <div class="card mt">
      <el-table :data="items" v-loading="loading" size="default">
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" @click="$router.push(`/documents/${row.id}`)">{{ row.title }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="90" />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ (row.file_size / 1024).toFixed(1) }} KB</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip :disabled="!row.error_message" :content="row.error_message || ''">
              <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="片段" width="80" />
        <el-table-column prop="updated_at" label="更新时间" width="170">
          <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="reindex(row)">重建索引</el-button>
            <el-button link type="primary" size="small" @click="exportDoc(row)">导出</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-hint">暂无文档</div></template>
      </el-table>

      <el-pagination
        class="mt"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="filters.page_size"
        :current-page="filters.page"
        @current-change="onPage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi, documentsApi, tagsApi } from '@/api'
import type { Category, DocumentOut, Tag } from '@/api/types'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const loading = ref(false)
const items = ref<DocumentOut[]>([])
const total = ref(0)
const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])

const filters = reactive({
  q: '',
  category_id: null as string | null,
  tag: null as string | null,
  sort: 'updated_at',
  page: 1,
  page_size: 20,
})

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function reload() {
  loading.value = true
  try {
    const data = await documentsApi.list({ ...filters })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPage(p: number) {
  filters.page = p
  reload()
}

async function reindex(row: DocumentOut) {
  try {
    const res = await documentsApi.reindex(row.id)
    ElMessage.success(`重建完成，共 ${res.chunk_count} 个片段`)
    reload()
  } catch {
    reload()
  }
}

async function exportDoc(row: DocumentOut) {
  const res = await documentsApi.export(row.id, 'md')
  const blob = new Blob([res.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = res.filename
  a.click()
  URL.revokeObjectURL(url)
}

async function remove(row: DocumentOut) {
  await ElMessageBox.confirm(
    `确定删除《${row.title}》？将同时删除原始文件与向量索引，且不可恢复。`,
    '删除确认',
    { type: 'warning' },
  )
  await documentsApi.remove(row.id)
  ElMessage.success('已删除')
  reload()
}

onMounted(async () => {
  const [cats, tgs] = await Promise.all([categoriesApi.list(), tagsApi.list()])
  categories.value = cats
  tags.value = tgs
  await reload()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.mt {
  margin-top: 16px;
}
</style>
