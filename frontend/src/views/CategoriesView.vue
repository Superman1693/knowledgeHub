<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">分类管理</h1>
        <p class="page-sub">用分类组织知识。删除分类只会解除关联，不会删除文档</p>
      </div>
    </div>

    <el-alert class="guide" type="info" :closable="false" show-icon title="分类怎么用？">
      <div>
        分类是<b>粗粒度分区</b>（如「工作」「学习」「生活」），一篇文档只能属于一个分类。
        给文档设置分类的入口在「文档管理」里点开某篇文档 → 详情页的「分类」下拉框。
        本页负责创建与管理分类本身，点下方<b>文档数</b>可查看该分类下的文档。
      </div>
    </el-alert>

    <div class="card">
      <div class="row">
        <el-input v-model="newName" placeholder="新分类名称" style="width: 220px" @keyup.enter="create" />
        <el-input v-model="newDesc" placeholder="描述（可选）" style="width: 280px" />
        <el-button type="primary" @click="create">新建分类</el-button>
      </div>

      <el-table :data="items" class="mt" v-loading="loading" size="default">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
        <el-table-column label="文档数" width="110">
          <template #default="{ row }">
            <el-link
              v-if="row.document_count"
              type="primary"
              @click="openDocuments({ category: row.id })"
            >
              {{ row.document_count }}
            </el-link>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="180">
          <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              @click="openDocuments({ category: row.id })"
            >
              查看文档
            </el-button>
            <el-button link type="primary" size="small" @click="rename(row)">重命名</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <div class="empty-icon"><el-icon><FolderOpened /></el-icon></div>
            <div class="empty-title">还没有分类</div>
            <div class="empty-desc">
              分类适合做粗粒度的知识分区（如「工作」「学习」「生活」）。一篇文档只能属于一个分类。
            </div>
          </div>
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi } from '@/api'
import type { Category } from '@/api/types'

const router = useRouter()
const loading = ref(false)
const items = ref<Category[]>([])
const newName = ref('')
const newDesc = ref('')

/** 跳转到文档管理并预置分类筛选。 */
function openDocuments(query: Record<string, string>) {
  router.push({ path: '/documents', query })
}

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
.guide {
  margin-bottom: 16px;
}
.muted {
  color: var(--kh-text-mute);
}
</style>
