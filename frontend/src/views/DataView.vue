<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div>
        <h1 class="page-title">数据与备份</h1>
        <p class="page-sub">所有数据保存在本机数据目录。备份包含数据库记录与原始文件</p>
      </div>
    </div>

    <div class="card">
      <div class="section-title">数据目录</div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="目录">{{ info.data_dir }}</el-descriptions-item>
        <el-descriptions-item label="原始文档">{{ kb(info.documents_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="附件">{{ kb(info.attachments_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="导出">{{ kb(info.exports_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="备份">{{ kb(info.backups_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="缓存">{{ kb(info.cache_bytes) }}</el-descriptions-item>
      </el-descriptions>
      <div class="row mt">
        <el-button type="primary" :loading="busy" @click="doBackup">
          <el-icon><Download /></el-icon> 立即备份
        </el-button>
        <el-button @click="doClean">清理缓存</el-button>
        <el-button @click="load">刷新</el-button>
      </div>
      <div class="hint">备份内容：数据库全部业务表（JSON）+ documents/ 原始文档 + attachments/ 附件</div>
    </div>

    <div class="card mt">
      <div class="section-title">备份文件</div>
      <el-table :data="backups" size="small">
        <el-table-column prop="name" label="文件名" min-width="300" />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">{{ kb(row.size) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="doRestore(row.name)">恢复</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-hint">还没有备份</div></template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { systemApi } from '@/api'

const loading = ref(false)
const busy = ref(false)
const info = ref<Record<string, unknown>>({})
const backups = ref<{ name: string; size: number }[]>([])

const kb = (v: unknown) =>
  v === undefined || v === null ? '-' : `${(Number(v) / 1024).toFixed(1)} KB`

async function load() {
  loading.value = true
  try {
    info.value = await systemApi.dataDir()
    const res = await systemApi.backups()
    backups.value = res.items
  } finally {
    loading.value = false
  }
}

async function doBackup() {
  busy.value = true
  try {
    const res = await systemApi.backup()
    ElMessage.success(`备份完成：${res.name}`)
    load()
  } finally {
    busy.value = false
  }
}

async function doRestore(name: string) {
  await ElMessageBox.confirm(
    `恢复会覆盖当前全部数据（数据库记录与文件），确定使用「${name}」恢复吗？`,
    '恢复确认',
    { type: 'warning', confirmButtonText: '确认恢复' },
  )
  const res = await systemApi.restore(name)
  ElMessage.success(`恢复完成：${res.files} 个文件`)
  load()
}

async function doClean() {
  const res = await systemApi.cleanCache()
  ElMessage.success(`已清理 ${res.removed} 个缓存文件`)
  load()
}

onMounted(load)
</script>

<style scoped>
.section-title {
  font-weight: 600;
  margin-bottom: 14px;
}
.row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.mt {
  margin-top: 16px;
}
.hint {
  color: var(--kh-text-sub);
  font-size: 12px;
  margin-top: 10px;
}
</style>
