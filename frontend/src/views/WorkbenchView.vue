<template>
  <div class="page">
    <h2 class="page-title">知识工作台</h2>
    <p class="page-sub">本地个人知识库总览 · 数据全部保存在本机</p>

    <el-row :gutter="16" class="stats">
      <el-col :span="6" v-for="s in statCards" :key="s.label">
        <div class="card stat">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <el-col :span="12">
        <div class="card">
          <div class="section-title">快捷入口</div>
          <div class="actions">
            <el-button type="primary" @click="$router.push('/upload')">
              <el-icon><UploadFilled /></el-icon> 导入文档
            </el-button>
            <el-button @click="$router.push('/chat')">
              <el-icon><ChatDotRound /></el-icon> 开始问答
            </el-button>
            <el-button @click="$router.push('/search')">
              <el-icon><Search /></el-icon> 检索知识
            </el-button>
            <el-button @click="loadStatus">
              <el-icon><Refresh /></el-icon> 刷新状态
            </el-button>
          </div>
          <el-alert
            v-if="status.failed > 0"
            class="mt-sm"
            type="warning"
            :closable="false"
            :title="`有 ${status.failed} 个文档处理失败，可在文档管理中查看原因并重建索引`"
          />
        </div>
      </el-col>

      <el-col :span="12">
        <div class="card">
          <div class="section-title">索引状态</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="文档总数">{{ status.document_total }}</el-descriptions-item>
            <el-descriptions-item label="已索引">{{ status.indexed }}</el-descriptions-item>
            <el-descriptions-item label="处理中">{{ status.processing + status.pending }}</el-descriptions-item>
            <el-descriptions-item label="失败">{{ status.failed }}</el-descriptions-item>
            <el-descriptions-item label="片段总数">{{ status.chunk_total }}</el-descriptions-item>
            <el-descriptions-item label="已向量化">{{ status.embedded_chunks }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-col>
    </el-row>

    <div class="card mt">
      <div class="section-title">最近更新的文档</div>
      <el-table :data="recent" size="small" v-loading="loading">
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" @click="$router.push(`/documents/${row.id}`)">{{ row.title }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="90" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="片段" width="80" />
        <el-table-column prop="updated_at" label="更新时间" width="180">
          <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
        </el-table-column>
        <template #empty><div class="empty-hint">还没有文档，先去「导入文档」吧</div></template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { documentsApi, settingsApi } from '@/api'
import type { DocumentOut, IndexStatus } from '@/api/types'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const loading = ref(false)
const recent = ref<DocumentOut[]>([])
const status = ref<IndexStatus>({
  document_total: 0,
  indexed: 0,
  partial: 0,
  pending: 0,
  processing: 0,
  failed: 0,
  chunk_total: 0,
  embedded_chunks: 0,
})

const statCards = computed(() => [
  { label: '文档总数', value: status.value.document_total },
  { label: '已索引', value: status.value.indexed },
  { label: '知识片段', value: status.value.chunk_total },
  { label: '处理失败', value: status.value.failed },
])

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function loadStatus() {
  status.value = await settingsApi.indexStatus()
}

async function loadRecent() {
  loading.value = true
  try {
    const data = await documentsApi.list({ page: 1, page_size: 8 })
    recent.value = data.items
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadStatus(), loadRecent()])
})
</script>

<style scoped>
.stats {
  margin-bottom: 16px;
}
.stat {
  text-align: center;
}
.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: #409eff;
}
.stat-label {
  color: var(--kh-text-sub);
  font-size: 13px;
  margin-top: 4px;
}
.section-title {
  font-weight: 600;
  margin-bottom: 12px;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.mt {
  margin-top: 16px;
}
.mt-sm {
  margin-top: 12px;
}
</style>
