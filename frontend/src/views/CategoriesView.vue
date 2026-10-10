<template>
  <div class="page">
    <h2 class="page-title">分类管理</h2>
    <p class="page-sub">用分类组织知识。删除分类只会解除关联，不会删除文档</p>

    <div class="card">
      <div class="row">
        <el-input v-model="newName" placeholder="新分类名称" style="width: 220px" @keyup.enter="create" />
        <el-input v-model="newDesc" placeholder="描述（可选）" style="width: 280px" />
        <el-button type="primary" @click="create">新建分类</el-button>
      </div>

      <el-table :data="items" class="mt" v-loading="loading" size="default">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
        <el-table-column prop="document_count" label="文档数" width="100" />
        <el-table-column prop="updated_at" label="更新时间" width="180">
          <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="rename(row)">重命名</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-hint">还没有分类</div></template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi } from '@/api'
import type { Category } from '@/api/types'

const loading = ref(false)
const items = ref<Category[]>([])
const newName = ref('')
const newDesc = ref('')

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function load() {
  loading.value = true
  try {
    items.value = await categoriesApi.list()
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!newName.value.trim()) {
    ElMessage.warning('请输入分类名称')
    return
  }
  await categoriesApi.create({ name: newName.value.trim(), description: newDesc.value || undefined })
  ElMessage.success('已创建')
  newName.value = ''
  newDesc.value = ''
  load()
}

async function rename(row: Category) {
  const { value } = await ElMessageBox.prompt('输入新的分类名称', '重命名', {
    inputValue: row.name,
  })
  if (!value) return
  await categoriesApi.update(row.id, { name: value })
  ElMessage.success('已更新')
  load()
}

async function remove(row: Category) {
  await ElMessageBox.confirm(
    `删除分类「${row.name}」？其中的 ${row.document_count} 个文档会变为未分类，文档本身不会被删除。`,
    '删除确认',
    { type: 'warning' },
  )
  await categoriesApi.remove(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.mt {
  margin-top: 16px;
}
</style>
