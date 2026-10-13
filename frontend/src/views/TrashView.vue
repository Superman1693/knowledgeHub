<template>
  <div class="trash">
    <header class="tr-head">
      <div>
        <h2 class="tr-title">回收站</h2>
        <p class="tr-desc">
          删除的笔记会先进入这里，<b>原文件与索引都保留</b>，可随时恢复；
          只有「彻底删除」才会移除磁盘文件。
          <template v-if="retentionDays > 0">
            当前已开启保留期：超过 <b>{{ retentionDays }}</b> 天的项目会在启动时自动彻底删除。
          </template>
          <template v-else>保留期为 0（永不自动清理），可在「系统设置」中调整。</template>
        </p>
      </div>
      <div class="tr-actions">
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="danger" plain :disabled="!items.length" @click="emptyAll">
          <el-icon><Delete /></el-icon>
          <span>清空回收站</span>
        </el-button>
      </div>
    </header>

    <div v-loading="loading" class="tr-list">
      <div v-if="!items.length && !loading" class="tr-empty">
        <el-icon><Delete /></el-icon>
        <span>回收站是空的</span>
      </div>

      <div v-for="d in items" :key="d.id" class="tr-item">
        <div class="tr-item-main">
          <div class="tr-item-title">
            <el-icon class="tr-item-icon"><Document /></el-icon>
            <span>{{ d.title }}</span>
          </div>
          <div class="tr-item-meta">
            删除于 {{ fmt(d.deleted_at) }} · {{ sizeText(d.file_size) }} ·
            {{ d.chunk_count }} 个片段
            <template v-if="expireText(d)">· {{ expireText(d) }}</template>
          </div>
        </div>
        <div class="tr-item-actions">
          <el-button size="small" type="primary" plain @click="restore(d.id)">
            <el-icon><RefreshLeft /></el-icon>
            <span>恢复</span>
          </el-button>
          <el-button size="small" type="danger" plain @click="purge(d)">
            <el-icon><Delete /></el-icon>
            <span>彻底删除</span>
          </el-button>
        </div>
      </div>
    </div>

    <footer v-if="total > pageSize" class="tr-foot">
      <el-pagination
        layout="prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="onPage"
      />
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { documentsApi, settingsApi } from '@/api'
import type { DocumentOut } from '@/api/types'

const items = ref<DocumentOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
/** 回收站保留天数：0 = 永不自动清理 */
const retentionDays = ref(0)

function fmt(v?: string | null) {
  return v ? new Date(v).toLocaleString('zh-CN') : '-'
}

/** 距自动清理还剩几天（保留期为 0 时返回空串）。 */
function expireText(d: DocumentOut) {
  if (!retentionDays.value || !d.deleted_at) return ''
  const elapsedDays = (Date.now() - new Date(d.deleted_at).getTime()) / 86400000
  const left = Math.ceil(retentionDays.value - elapsedDays)
  if (left <= 0) return '即将自动清理'
  return `剩余 ${left} 天`
}

function sizeText(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  try {
    const res = await documentsApi.trash({ page: page.value, page_size: pageSize.value })
    items.value = res.items
    total.value = res.total
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

/** 保留期配置来自系统设置；取不到就按 0（不显示剩余天数）处理。 */
async function loadRetention() {
  try {
    const s = await settingsApi.get()
    retentionDays.value = s.trash_retention_days ?? 0
  } catch {
    retentionDays.value = 0
  }
}

function onPage(p: number) {
  page.value = p
  load()
}

async function restore(id: string) {
  await documentsApi.restore(id)
  ElMessage.success('已恢复到文档列表')
  await load()
}

async function purge(doc: DocumentOut) {
  try {
    await ElMessageBox.confirm(
      `「${doc.title}」将被彻底删除，磁盘上的原始文件也会一并移除，且无法恢复。是否继续？`,
      '彻底删除确认',
      { type: 'warning', confirmButtonText: '彻底删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await documentsApi.purge(doc.id)
  ElMessage.success('已彻底删除')
  await load()
}

async function emptyAll() {
  try {
    await ElMessageBox.confirm(
      `回收站中的 ${total.value} 项将被彻底删除且无法恢复。是否继续？`,
      '清空回收站确认',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const res = await documentsApi.emptyTrash()
  ElMessage.success(`已清空回收站（${res.removed} 项）`)
  page.value = 1
  await load()
}

onMounted(async () => {
  await Promise.all([loadRetention(), load()])
})
</script>

<style scoped>
.trash {
  padding: 22px 26px;
  height: 100vh;
  overflow-y: auto;
  background: var(--kh-bg);
}

.tr-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.tr-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 6px;
}

.tr-desc {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.7;
  margin: 0;
  max-width: 620px;
}

.tr-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.tr-list {
  min-height: 160px;
}

.tr-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 70px 0;
  color: var(--kh-text-mute);
  font-size: 13px;
}

.tr-empty .el-icon {
  font-size: 28px;
}

.tr-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 16px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border-light);
  border-radius: 10px;
  margin-bottom: 8px;
}

.tr-item-main {
  min-width: 0;
}

.tr-item-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
}

.tr-item-icon {
  color: var(--kh-text-mute);
}

.tr-item-meta {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  margin-top: 3px;
}

.tr-item-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.tr-foot {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
