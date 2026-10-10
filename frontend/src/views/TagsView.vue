<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">标签管理</h1>
        <p class="page-sub">为文档打标签，支持自动推荐与相似标签检测。一篇文档可以有多个标签</p>
      </div>
    </div>

    <div class="card">
      <div class="row">
        <el-input v-model="newName" placeholder="新标签名称" style="width: 220px" @keyup.enter="create" />
        <el-button type="primary" @click="create">新建标签</el-button>
        <el-input v-model="probe" placeholder="检测相似标签（输入一个词）" style="width: 260px" />
        <el-button @click="checkSimilar">检测相似</el-button>
      </div>

      <el-alert
        v-if="similar.length"
        class="mt-sm"
        type="warning"
        :closable="true"
        :title="`与「${probe}」相似的标签：${similar.join('、')}`"
      />

      <el-table :data="items" class="mt" v-loading="loading" size="default">
        <el-table-column prop="name" label="标签" min-width="200" />
        <el-table-column prop="document_count" label="关联文档" width="120" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="rename(row)">重命名</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <div class="empty-icon"><el-icon><PriceTag /></el-icon></div>
            <div class="empty-title">还没有标签</div>
            <div class="empty-desc">
              标签适合做细粒度的交叉标记（如「Vue3」「性能优化」）。
              也可以在文档详情页用「推荐标签」自动生成。
            </div>
          </div>
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tagsApi } from '@/api'
import client from '@/api/client'
import type { Tag } from '@/api/types'

const loading = ref(false)
const items = ref<Tag[]>([])
const newName = ref('')
const probe = ref('')
const similar = ref<string[]>([])

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function load() {
  loading.value = true
  try {
    items.value = await tagsApi.list()
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!newName.value.trim()) {
    ElMessage.warning('请输入标签名')
    return
  }
  await tagsApi.create(newName.value.trim())
  ElMessage.success('已创建')
  newName.value = ''
  load()
}

async function rename(row: Tag) {
  const { value } = await ElMessageBox.prompt('输入新的标签名称', '重命名', {
    inputValue: row.name,
  })
  if (!value) return
  await tagsApi.update(row.id, value)
  ElMessage.success('已更新')
  load()
}

async function remove(row: Tag) {
  await ElMessageBox.confirm(`删除标签「${row.name}」？文档本身不受影响。`, '删除确认', {
    type: 'warning',
  })
  await tagsApi.remove(row.id)
  ElMessage.success('已删除')
  load()
}

async function checkSimilar() {
  if (!probe.value.trim()) return
  const res = await client
    .get<{ similar: string[] }>('/tags/similar', { params: { name: probe.value } })
    .then((r) => r.data)
  similar.value = res.similar
  if (!res.similar.length) ElMessage.info('未发现相似标签')
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
.mt-sm {
  margin-top: 12px;
}
</style>
