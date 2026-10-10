<template>
  <div class="page">
    <h2 class="page-title">专属术语词典</h2>
    <p class="page-sub">
      定义技术缩写、项目自定义名词、框架术语与个人习惯用语。问答时会优先采用词典中的定义
    </p>

    <div class="card">
      <div class="row">
        <el-input v-model="keyword" placeholder="搜索术语或释义" clearable style="width: 240px" @keyup.enter="load" />
        <el-button type="primary" @click="load"><el-icon><Search /></el-icon>查询</el-button>
        <el-button @click="openCreate">新增术语</el-button>
      </div>
    </div>

    <div class="card mt">
      <div class="section-title">术语列表（{{ items.length }} 条）</div>
      <el-table :data="items" v-loading="loading" size="default">
        <el-table-column prop="term" label="术语" width="180">
          <template #default="{ row }">
            <span class="term-name">{{ row.term }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.category" size="small" effect="plain">{{ row.category }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="别名" width="180">
          <template #default="{ row }">
            <span v-if="row.aliases && row.aliases.length">{{ row.aliases.join('、') }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="definition" label="释义" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-hint">还没有术语，先新增一条吧</div></template>
      </el-table>
    </div>

    <div class="card mt">
      <div class="section-title">命中预览</div>
      <p class="hint">输入一段话，看看问答时会命中哪些术语</p>
      <div class="row">
        <el-input v-model="probe" placeholder="例如：KH 的 RAG 是怎么实现的？" style="flex: 1" @keyup.enter="doLookup" />
        <el-button @click="doLookup">试一下</el-button>
      </div>
      <div v-if="lookupResult" class="mt-sm">
        <div v-if="lookupResult.terms.length">
          <div v-for="t in lookupResult.terms" :key="t.id" class="hit-item">
            <el-tag size="small" type="success" effect="plain">{{ t.term }}</el-tag>
            <span class="hit-def">{{ t.definition }}</span>
          </div>
        </div>
        <div v-else class="empty-hint" style="padding: 16px 0">没有命中任何术语</div>
      </div>
    </div>

    <!-- 新增 / 编辑 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑术语' : '新增术语'" width="560px">
      <el-form label-width="90px">
        <el-form-item label="术语" required>
          <el-input v-model="form.term" placeholder="例如 RAG / KH / 组合式 API" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" placeholder="可选" clearable style="width: 100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名">
          <el-select
            v-model="form.aliases"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="回车可添加多个别名/缩写"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="释义" required>
          <el-input v-model="form.definition" type="textarea" :rows="4" placeholder="这个术语在本项目/本人语境下的准确含义" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { glossaryApi } from '@/api'
import type { GlossaryTerm } from '@/api/types'

const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const items = ref<GlossaryTerm[]>([])
const probe = ref('')
const lookupResult = ref<{ terms: GlossaryTerm[]; rendered: string } | null>(null)

const dialogVisible = ref(false)
const editing = ref<GlossaryTerm | null>(null)

const categories = ['缩写', '框架术语', '项目名词', '习惯用语', '其他']

const form = reactive({
  term: '',
  definition: '',
  aliases: [] as string[],
  category: '' as string,
})

async function load() {
  loading.value = true
  try {
    items.value = await glossaryApi.list(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { term: '', definition: '', aliases: [], category: '' })
  dialogVisible.value = true
}

function openEdit(row: GlossaryTerm) {
  editing.value = row
  Object.assign(form, {
    term: row.term,
    definition: row.definition,
    aliases: [...(row.aliases ?? [])],
    category: row.category ?? '',
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.term.trim() || !form.definition.trim()) {
    ElMessage.warning('术语与释义都不能为空')
    return
  }
  saving.value = true
  try {
    const payload = {
      term: form.term.trim(),
      definition: form.definition.trim(),
      aliases: form.aliases.length ? form.aliases : null,
      category: form.category || null,
    }
    if (editing.value) {
      await glossaryApi.update(editing.value.id, payload)
    } else {
      await glossaryApi.create(payload)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row: GlossaryTerm) {
  await ElMessageBox.confirm(`删除术语「${row.term}」？`, '删除确认', { type: 'warning' })
  await glossaryApi.remove(row.id)
  ElMessage.success('已删除')
  await load()
}

async function doLookup() {
  if (!probe.value.trim()) return
  lookupResult.value = await glossaryApi.lookup(probe.value)
}

onMounted(load)
</script>

<style scoped>
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
.section-title {
  font-weight: 600;
  margin-bottom: 12px;
}
.hint {
  color: var(--kh-text-sub);
  font-size: 12px;
  margin: 0 0 10px;
}
.term-name {
  font-weight: 600;
  color: #409eff;
}
.hit-item {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 6px 0;
}
.hit-def {
  color: #606266;
}
</style>
