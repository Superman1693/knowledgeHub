<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">知识检索</h1>
        <p class="page-sub">
          不调用 AI 也能直接查资料，结果可定位到原文片段
        </p>
      </div>
    </div>

    <div class="card">
      <div class="row">
        <el-input
          v-model="query"
          placeholder="输入关键词或自然语言问题，支持拼音（shujuku）与拼错容错（vuee）"
          size="large"
          style="flex: 1"
          clearable
          @keyup.enter="doSearch"
        />
        <el-select v-model="mode" size="large" style="width: 170px">
          <el-option label="混合检索" value="hybrid" />
          <el-option label="关键词检索" value="keyword" />
          <el-option label="语义检索" value="semantic" />
        </el-select>
        <el-select v-model="categoryId" placeholder="全部分类" clearable size="large" style="width: 170px">
          <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-select v-model="sort" size="large" style="width: 150px">
          <el-option label="按相关度" value="relevance" />
          <el-option label="按更新时间" value="updated" />
          <el-option label="按创建时间" value="created" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          size="large"
          unlink-panels
          range-separator="至"
          start-placeholder="更新起始"
          end-placeholder="更新截止"
          value-format="YYYY-MM-DD"
          style="width: 250px"
        />
        <el-button type="primary" size="large" :loading="loading" @click="doSearch">检索</el-button>
        <el-button size="large" :loading="saving" @click="saveCondition">
          <el-icon><Star /></el-icon>
          <span>保存条件</span>
        </el-button>
      </div>
    </div>

    <!-- 常用检索（保存的检索条件）：点一下套用并立即检索 -->
    <div v-if="saved.length" class="card mt saved-bar">
      <span class="saved-label">常用检索</span>
      <el-tag
        v-for="s in saved"
        :key="s.id"
        class="saved-chip"
        type="info"
        effect="plain"
        closable
        @click="applySaved(s)"
        @close="removeSaved(s)"
      >
        {{ s.name }}
      </el-tag>
    </div>

    <div v-if="searched" class="card mt">
      <div class="result-head">
        <span>共 {{ result?.total ?? 0 }} 条结果</span>
        <span class="muted">模式：{{ modeLabel }}</span>
      </div>

      <div v-for="(hit, i) in result?.hits ?? []" :key="hit.chunk_id" class="hit">
        <div class="hit-head">
          <span class="hit-index">[{{ i + 1 }}]</span>
          <el-link type="primary" @click="openHit(hit)">
            <!-- 标题也可能被命中（标题检索）：一并高亮，否则用户看到
                 结果被召回却不明白为什么 -->
            <span v-html="highlighted(hit.document_title, hit.highlights)" />
          </el-link>
          <el-tag v-if="hit.heading" size="small" effect="plain">{{ hit.heading }}</el-tag>
          <el-tag v-if="hit.page_no" size="small" effect="plain">第 {{ hit.page_no }} 页</el-tag>
          <span class="muted">
            综合 {{ hit.score.toFixed(3) }}
            <template v-if="hit.keyword_score != null">· 关键词 {{ hit.keyword_score.toFixed(3) }}</template>
            <template v-if="hit.semantic_score != null">· 语义 {{ hit.semantic_score.toFixed(3) }}</template>
          </span>
        </div>
        <div class="hit-snippet" v-html="highlighted(hit.snippet, hit.highlights)" />
      </div>

      <div v-if="!result?.hits.length" class="empty-state">
        <div class="empty-icon"><el-icon><Search /></el-icon></div>
        <div class="empty-title">没有找到相关片段</div>
        <div class="empty-desc">
          可以试试：换用更口语化的描述（走语义检索）、减少限定词，
          或者确认相关文档是否已完成索引。
        </div>
      </div>
    </div>

    <!-- 未检索时：说明三种模式的区别，降低理解成本 -->
    <div v-if="!searched" class="card mt">
      <div class="card-title">
        <el-icon><InfoFilled /></el-icon>三种检索模式怎么选
      </div>
      <div class="mode-guide">
        <div class="mode-item">
          <div class="mode-name">关键词检索</div>
          <div class="mode-desc">
            按字面分词命中，快且精确。适合查具体名词、报错信息、函数名。
          </div>
        </div>
        <div class="mode-item">
          <div class="mode-name">语义检索</div>
          <div class="mode-desc">
            按向量相似度找「意思相近」的片段。适合用大白话描述一个概念。
          </div>
        </div>
        <div class="mode-item is-recommended">
          <div class="mode-name">
            混合检索
            <span class="rec-tag">推荐</span>
          </div>
          <div class="mode-desc">
            关键词与语义加权融合（0.3 / 0.7），兼顾精确与联想，大多数情况效果最好。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi, savedSearchApi, searchApi } from '@/api'
import type { Category, SavedSearchOut, SearchHit, SearchResponse } from '@/api/types'

const router = useRouter()
const query = ref('')
const mode = ref('hybrid')
const categoryId = ref<string | null>(null)
/** relevance | updated | created */
const sort = ref('relevance')
/** 更新时间区间筛选（YYYY-MM-DD，由 el-date-picker 给出） */
const dateRange = ref<[string, string] | null>(null)
const loading = ref(false)
const searched = ref(false)
const result = ref<SearchResponse | null>(null)
const categories = ref<Category[]>([])

const modeLabel = computed(
  () => ({ hybrid: '混合检索', keyword: '关键词检索', semantic: '语义检索' })[mode.value] ?? mode.value,
)

function escapeHtml(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  )
}

/** 先转义再一次性高亮命中词，避免 XSS 与二次包裹。 */
function highlighted(text: string, terms: string[] = []): string {
  const esc = escapeHtml(text || '')
  const valid = (terms || [])
    .filter(Boolean)
    .map((t) => escapeHtml(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!valid.length) return esc
  return esc.replace(new RegExp(`(${valid.join('|')})`, 'gi'), '<mark>$1</mark>')
}

/** 打开命中片段所在的文档，并定位到该片段（需求 11.7）。 */
function openHit(hit: SearchHit) {
  router.push({
    path: `/documents/${hit.document_id}`,
    query: { chunk: hit.chunk_id },
  })
}

/**
 * 当前筛选条件（检索与「保存条件」共用同一份来源，
 * 避免两处各写一遍导致保存下来的条件和实际检索的不一致）。
 */
function currentParams() {
  const [from, to] = dateRange.value ?? []
  return {
    query: query.value.trim(),
    mode: mode.value,
    category_id: categoryId.value,
    tags: null as string[] | null,
    top_k: 10,
    sort: sort.value,
    // 起始取 00:00:00、截止取 23:59:59，否则用户选「同一天」会因为只比到 00:00 而查不到
    date_from: from ? `${from}T00:00:00` : null,
    date_to: to ? `${to}T23:59:59` : null,
  }
}

async function doSearch() {
  if (!query.value.trim()) return
  loading.value = true
  searched.value = true
  try {
    result.value = await searchApi.search(currentParams())
  } catch {
    result.value = null
  } finally {
    loading.value = false
  }
}

// ---------------- 保存的检索条件（智能集合） ----------------
const saved = ref<SavedSearchOut[]>([])
const saving = ref(false)

async function loadSaved() {
  try {
    saved.value = await savedSearchApi.list()
  } catch {
    saved.value = []
  }
}

async function saveCondition() {
  if (!query.value.trim()) {
    ElMessage.warning('先输入关键词并检索一次，再保存这套条件')
    return
  }
  let res: { value: string }
  try {
    res = await ElMessageBox.prompt('给这套检索条件起个名字', '保存检索条件', {
      inputPlaceholder: '如：Vue 响应式',
    })
  } catch {
    return // 用户取消
  }
  const name = (res.value || '').trim()
  if (!name) return
  saving.value = true
  try {
    await savedSearchApi.create(name, currentParams())
    ElMessage.success('已保存，下次点标签即可套用')
    await loadSaved()
  } finally {
    saving.value = false
  }
}

/** 套用一个保存的条件并立即检索。 */
async function applySaved(s: SavedSearchOut) {
  const p = s.params || {}
  query.value = p.query || ''
  mode.value = p.mode || 'hybrid'
  categoryId.value = p.category_id ?? null
  sort.value = p.sort || 'relevance'
  dateRange.value =
    p.date_from && p.date_to ? [p.date_from.slice(0, 10), p.date_to.slice(0, 10)] : null
  await doSearch()
}

async function removeSaved(s: SavedSearchOut) {
  await savedSearchApi.remove(s.id)
  ElMessage.success('已删除')
  await loadSaved()
}

onMounted(async () => {
  categories.value = await categoriesApi.list()
  await loadSaved()
})
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
.result-head {
  display: flex;
  justify-content: space-between;
  color: var(--kh-text-sub);
  font-size: 13px;
  margin-bottom: 12px;
}
.hit {
  border-top: 1px solid var(--kh-border);
  padding: 12px 0;
}
.hit-head {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.hit-index {
  color: var(--kh-primary);
  font-weight: 600;
}
.hit-snippet {
  color: #3f4652;
  line-height: 1.72;
}
.hit-snippet :deep(mark) {
  background: #fff2ba;
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}
.muted {
  color: var(--kh-text-sub);
  font-size: 12px;
}

/* ---- 模式说明 ---- */
.mode-guide {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.mode-item {
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  padding: 14px 15px;
  background: var(--kh-panel);
}

.mode-item.is-recommended {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.mode-name {
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: 5px;
  display: flex;
  align-items: center;
  gap: 7px;
}

.rec-tag {
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  background: var(--kh-primary);
  border-radius: 4px;
  padding: 1px 6px;
}

.mode-desc {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.62;
}

/* ---------------- 常用检索（保存的检索条件） ---------------- */
.saved-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.saved-label {
  font-size: 12.5px;
  color: var(--kh-text-sub);
}

.saved-chip {
  cursor: pointer;
}

.saved-chip:hover {
  border-color: var(--kh-primary);
  color: var(--kh-primary);
}
</style>
