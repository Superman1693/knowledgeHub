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
          <el-link type="primary" @click="openHit(hit)">
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
import { categoriesApi, searchApi } from '@/api'
import type { Category, SearchHit, SearchResponse } from '@/api/types'

const router = useRouter()
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

/** 打开命中片段所在的文档，并定位到该片段（需求 11.7）。 */
function openHit(hit: SearchHit) {
  router.push({
    path: `/documents/${hit.document_id}`,
    query: { chunk: hit.chunk_id },
  })
}

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
  color: var(--kh-primary);
  font-weight: 600;
}
.hit-snippet {
  color: #3f4652;
  line-height: 1.72;
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
</style>
