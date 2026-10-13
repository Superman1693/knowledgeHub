<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">标签管理</h1>
        <p class="page-sub">为文档打标签，支持自动推荐与相似标签检测。一篇文档可以有多个标签</p>
      </div>
    </div>

    <el-alert class="guide" type="info" :closable="false" show-icon title="标签怎么用？">
      <div>
        标签是<b>细粒度交叉标记</b>（如「Vue3」「性能优化」），一篇文档可以有多个标签。
        给文档打标签的入口在「文档管理」里点开某篇文档 → 详情页的「标签」选择框，
        那里还有「推荐标签」可按文档内容自动生成建议。本页负责创建与管理标签本身，
        点下方<b>关联文档数</b>可查看带该标签的文档。
      </div>
    </el-alert>

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
        <el-table-column label="关联文档" width="120">
          <template #default="{ row }">
            <el-link
              v-if="row.document_count"
              type="primary"
              @click="openDocuments({ tag: row.name })"
            >
              {{ row.document_count }}
            </el-link>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ fmt(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDocuments({ tag: row.name })">
              查看文档
            </el-button>
            <el-button link type="primary" size="small" @click="rename(row)">重命名</el-button>
            <el-button link type="warning" size="small" @click="openMerge(row)">合并</el-button>
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

    <!-- 合并标签：把重复/近义标签收敛成一个 -->
    <el-dialog v-model="mergeOpen" title="合并标签" width="460px">
      <p class="merge-desc">
        把「<b>{{ mergeSource?.name }}</b>」合并到另一个标签：它的文档会改挂到目标标签，
        然后本标签被删除。用于收拾「vue / Vue / vuejs」这类重复标签。
      </p>
      <el-select
        v-model="mergeTarget"
        placeholder="选择要合并到的目标标签"
        filterable
        style="width: 100%"
      >
        <el-option
          v-for="t in mergeCandidates"
          :key="t.id"
          :label="`${t.name}（${t.document_count} 篇）`"
          :value="t.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="mergeOpen = false">取消</el-button>
        <el-button type="primary" :loading="merging" :disabled="!mergeTarget" @click="doMerge">
          确认合并
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tagsApi } from '@/api'
import client from '@/api/client'
import type { Tag } from '@/api/types'

const router = useRouter()
const loading = ref(false)
const items = ref<Tag[]>([])
const newName = ref('')
const probe = ref('')
const similar = ref<string[]>([])

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

/** 跳转到文档管理并预置标签筛选。 */
function openDocuments(query: Record<string, string>) {
  router.push({ path: '/documents', query })
}

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
  // 取消对话框时 ElMessageBox 会 reject；不捕获会产生 unhandled promise rejection
  let res: { value: string }
  try {
    res = await ElMessageBox.prompt('输入新的标签名称', '重命名', {
      inputValue: row.name,
    })
  } catch {
    return
  }
  if (!res.value) return
  await tagsApi.update(row.id, res.value)
  ElMessage.success('已更新')
  load()
}

async function remove(row: Tag) {
  try {
    await ElMessageBox.confirm(`删除标签「${row.name}」？文档本身不受影响。`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }
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

// ---------------- 合并标签 ----------------
const mergeOpen = ref(false)
const merging = ref(false)
const mergeSource = ref<Tag | null>(null)
const mergeTarget = ref<string | null>(null)

/** 可合并的目标：排除自己（后端也会再校验一次）。 */
const mergeCandidates = computed(() =>
  items.value.filter((t) => t.id !== mergeSource.value?.id),
)

function openMerge(row: Tag) {
  mergeSource.value = row
  // 若相似检测结果里恰好有同名标签，预选第一个作为目标，省一次点击
  const guess = mergeCandidates.value.find((t) => similar.value.includes(t.name))
  mergeTarget.value = guess?.id ?? null
  mergeOpen.value = true
}

async function doMerge() {
  const source = mergeSource.value
  const target = mergeTarget.value
  if (!source || !target) return
  const targetName = items.value.find((t) => t.id === target)?.name ?? ''
  try {
    await ElMessageBox.confirm(
      `「${source.name}」的文档将全部改挂到「${targetName}」，随后「${source.name}」会被删除。是否继续？`,
      '合并确认',
      { type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  merging.value = true
  try {
    const res = await tagsApi.merge(source.id, target)
    ElMessage.success(
      `已把「${res.merged}」合并到「${res.target_name}」（迁移 ${res.moved} 篇）`,
    )
    mergeOpen.value = false
    similar.value = []
    await load()
  } finally {
    merging.value = false
  }
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
.guide {
  margin-bottom: 16px;
}
.muted {
  color: var(--kh-text-mute);
}
.merge-desc {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.7;
  margin: 0 0 12px;
}
</style>
