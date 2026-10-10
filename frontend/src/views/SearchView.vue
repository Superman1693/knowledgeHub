<template>
  <div class="page">
    <h2 class="page-title">知识检索</h2>
    <p class="page-sub">关键词（pg_trgm）+ 语义（pgvector）混合检索，结果可定位到原文</p>

    <div class="card">
      <div class="row">
        <el-input
          v-model="query"
          placeholder="输入关键词或自然语言问题"
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
        <el-button type="primary" size="large" :loading="loading" @click="doSearch">检索</el-button>
      </div>
    </div>

    <div v-if="searched" class="card mt">
      <div class="result-head">
        <span>共 {{ result?.total ?? 0 }} 条结果</span>
        <span class="muted">模式：{{ modeLabel }}</span>
      </div>

      <div v-for="(hit, i) in result?.hits ?? []" :key="hit.chunk_id" class="hit">
        <div class="hit-head">
          <span class="hit-index">[{{ i + 1 }}]</span>
          <el-link type="primary" @click="$router.push(`/documents/${hit.document_id}`)">
            {{ hit.document_title }}
          </el-link>
          <el-tag v-if="hit.heading" size="small" effect="plain">{{ hit.heading }}</el-tag>
          <el-tag v-if="hit.page_no" size="small" effect="plain">第 {{ hit.page_no }} 页</el-tag>
          <span class="muted">
            综合 {{ hit.score.toFixed(3) }}
            <template v-if="hit.keyword_score !== null">· 关键词 {{ hit.keyword_score?.toFixed(3) }}</template>
            <template v-if="hit.semantic_score !== null">· 语义 {{ hit.semantic_score?.toFixed(3) }}</template>
          </span>
        </div>
        <div class="hit-snippet">{{ hit.snippet }}</div>
      </div>

      <div v-if="!result?.hits.length" class="empty-hint">
        没有找到相关片段。可尝试更换关键词，或改用「混合检索」模式。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { categoriesApi, searchApi } from '@/api'
import type { Category, SearchResponse } from '@/api/types'

const query = ref('')
const mode = ref('hybrid')
const categoryId = ref<string | null>(null)
const loading = ref(false)
const searched = ref(false)
const result = ref<SearchResponse | null>(null)
const categories = ref<Category[]>([])

const modeLabel = computed(
  () => ({ hybrid: '混合检索', keyword: '关键词检索', semantic: '语义检索' })[mode.value] ?? mode.value,
)

async function doSearch() {
  if (!query.value.trim()) return
  loading.value = true
  searched.value = true
  try {
    result.value = await searchApi.search({
      query: query.value,
      mode: mode.value,
      category_id: categoryId.value,
      top_k: 10,
    })
  } catch {
    result.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  categories.value = await categoriesApi.list()
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
  color: #409eff;
  font-weight: 600;
}
.hit-snippet {
  color: #606266;
  line-height: 1.7;
}
.muted {
  color: var(--kh-text-sub);
  font-size: 12px;
}
</style>
