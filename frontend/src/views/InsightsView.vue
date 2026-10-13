<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">知识加工</h1>
        <p class="page-sub">
          冗余检测与跨文档关联基于向量计算（不消耗对话模型）；思维导图与归档建议由 AI 生成，
          均为**建议**，不会自动改动任何内容
        </p>
      </div>
    </div>

    <div class="card">
      <el-tabs v-model="tab">
        <!-- ============ 冗余检测 ============ -->
        <el-tab-pane label="冗余检测" name="duplicates">
          <div class="row">
            <span class="label">相似阈值</span>
            <el-slider
              v-model="threshold"
              :min="0.01"
              :max="0.3"
              :step="0.01"
              :format-tooltip="(v: number) => `距离 ${v}`"
              style="width: 220px"
            />
            <el-button type="primary" :loading="loadingDup" @click="loadDuplicates">
              检测
            </el-button>
            <span class="hint">距离越小越相似；阈值 0.10 约等于相似度 0.90 以上</span>
          </div>

          <el-alert
            v-if="duplicates.length"
            class="mt-sm"
            type="info"
            :closable="false"
            show-icon
            :title="`发现 ${duplicates.length} 对相似片段（仅供参考，系统不会自动合并或删除）`"
          />

          <el-table v-if="duplicates.length" :data="duplicates" class="mt" size="small">
            <el-table-column label="相似度" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.similarity > 0.95 ? 'danger' : 'warning'">
                  {{ (row.similarity * 100).toFixed(1) }}%
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="片段 A" min-width="260">
              <template #default="{ row }">
                <div class="src-line">
                  <el-link type="primary" @click="openDoc(row.left)">{{ row.left.document_title }}</el-link>
                  <span v-if="row.left.heading" class="muted">· {{ row.left.heading }}</span>
                </div>
                <div class="snippet">{{ row.left.snippet }}</div>
              </template>
            </el-table-column>
            <el-table-column label="片段 B" min-width="260">
              <template #default="{ row }">
                <div class="src-line">
                  <el-link type="primary" @click="openDoc(row.right)">{{ row.right.document_title }}</el-link>
                  <span v-if="row.right.heading" class="muted">· {{ row.right.heading }}</span>
                  <el-tag v-if="row.same_document" size="small" effect="plain">同文档</el-tag>
                </div>
                <div class="snippet">{{ row.right.snippet }}</div>
              </template>
            </el-table-column>
          </el-table>
          <div v-else-if="dupChecked" class="empty-hint mt">未发现达到阈值的相似片段</div>
        </el-tab-pane>

        <!-- ============ 跨文档关联 ============ -->
        <el-tab-pane label="跨文档关联" name="related">
          <div class="row">
            <el-select v-model="relatedDocId" placeholder="选择一篇文档" style="width: 300px" filterable>
              <el-option v-for="d in documents" :key="d.id" :label="d.title" :value="d.id" />
            </el-select>
            <el-button type="primary" :loading="loadingRel" :disabled="!relatedDocId" @click="loadRelated">
              查找关联
            </el-button>
            <span class="hint">找出与所选文档内容最相近的其它文档，用于发现同一主题散落多篇的情况</span>
          </div>

          <el-table v-if="related.length" :data="related" class="mt" size="small">
            <el-table-column prop="document_title" label="文档" min-width="220">
              <template #default="{ row }">
                <el-link type="primary" @click="$router.push(`/documents/${row.document_id}`)">
                  {{ row.document_title }}
                </el-link>
              </template>
            </el-table-column>
            <el-table-column prop="chunk_count" label="片段数" width="100" />
            <el-table-column label="内容相似度" width="160">
              <template #default="{ row }">
                <el-progress
                  :percentage="Math.round(Math.max(0, row.similarity) * 100)"
                  :stroke-width="12"
                  :show-text="true"
                />
              </template>
            </el-table-column>
          </el-table>
          <div v-else-if="relChecked" class="empty-hint mt">没有找到其它相关文档</div>
        </el-tab-pane>

        <!-- ============ 思维导图 ============ -->
        <el-tab-pane label="思维导图" name="mindmap">
          <div class="row">
            <el-select v-model="mapDocId" placeholder="选择一篇文档" style="width: 300px" filterable>
              <el-option v-for="d in documents" :key="d.id" :label="d.title" :value="d.id" />
            </el-select>
            <el-button type="primary" :loading="loadingMap" :disabled="!mapDocId" @click="loadMindmap">
              生成思维导图
            </el-button>
            <span class="hint">由 AI 依据文档结构整理，节点取自原文，不补充知识库之外的信息</span>
          </div>

          <div v-if="mindmap" class="mt">
            <el-alert type="success" :closable="false" show-icon :title="mindmap.note" class="mb" />
            <div class="card inner">
              <MermaidDiagram :code="mindmap.mermaid" />
            </div>
            <el-collapse class="mt-sm">
              <el-collapse-item title="查看 Mermaid 源码">
                <pre class="code-block">{{ mindmap.mermaid }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-tab-pane>

        <!-- ============ 整理归档 ============ -->
        <el-tab-pane label="整理归档" name="organize">
          <div class="row">
            <el-select v-model="orgDocId" placeholder="选择一篇文档" style="width: 300px" filterable>
              <el-option v-for="d in documents" :key="d.id" :label="d.title" :value="d.id" />
            </el-select>
            <el-button type="primary" :loading="loadingOrg" :disabled="!orgDocId" @click="loadOrganize">
              生成归档建议
            </el-button>
            <span class="hint">AI 建议，需你确认后才会应用</span>
          </div>

          <div v-if="suggestion" class="mt">
            <el-alert type="warning" :closable="false" show-icon :title="suggestion.note" class="mb" />
            <el-descriptions :column="1" border>
              <el-descriptions-item label="当前标题">
                {{ suggestion.current_title }}
              </el-descriptions-item>
              <el-descriptions-item label="建议标题">
                <span v-if="suggestion.suggested_title">{{ suggestion.suggested_title }}</span>
                <span v-else class="muted">（AI 未能给出，保持原样）</span>
              </el-descriptions-item>
              <el-descriptions-item label="建议分类">
                <el-tag v-if="suggestion.category" size="small">{{ suggestion.category }}</el-tag>
                <span v-else class="muted">（未给出）</span>
              </el-descriptions-item>
              <el-descriptions-item label="建议标签">
                <template v-if="suggestion.tags.length">
                  <el-tag v-for="t in suggestion.tags" :key="t" size="small" class="tag-gap">{{ t }}</el-tag>
                </template>
                <span v-else class="muted">（未给出）</span>
              </el-descriptions-item>
              <el-descriptions-item label="内容摘要">{{ suggestion.summary || '—' }}</el-descriptions-item>
              <el-descriptions-item label="归档理由">{{ suggestion.reason || '—' }}</el-descriptions-item>
            </el-descriptions>

            <div class="row mt">
              <el-button
                type="primary"
                :disabled="!suggestion.tags.length"
                @click="applyTags"
              >
                将建议标签加入该文档
              </el-button>
              <span class="hint">只写入标签，不会修改文档内容或标题</span>
            </div>
          </div>
        </el-tab-pane>

        <!-- ============ 批量摘要 ============ -->
        <el-tab-pane label="批量摘要" name="batch">
          <div class="row">
            <el-select
              v-model="summaryDocIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="选择要生成摘要的文档（单次最多 20 篇）"
              style="width: 460px"
            >
              <el-option v-for="d in documents" :key="d.id" :label="d.title" :value="d.id" />
            </el-select>
            <el-button
              type="primary"
              :loading="loadingSummary"
              :disabled="!summaryDocIds.length"
              @click="loadBatchSummary"
            >
              生成摘要
            </el-button>
            <span class="hint">后端并发调用模型（同时最多 3 篇），可能较慢</span>
          </div>

          <div v-if="summaries.length" class="mt">
            <el-alert
              class="mb"
              type="info"
              :closable="false"
              show-icon
              :title="`已生成 ${summaries.length} 篇摘要（由 AI 依据正文生成，仅供参考）`"
            />
            <div v-for="s in summaries" :key="s.document_id" class="sum-item">
              <div class="sum-head">
                <span class="sum-title">{{ s.title }}</span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click="router.push(`/documents/${s.document_id}`)"
                >
                  打开笔记
                </el-button>
              </div>
              <div class="sum-body">{{ s.summary }}</div>
            </div>
          </div>
          <el-empty
            v-else-if="summaryDone"
            description="没有生成任何摘要（可能是模型不可用，或文档正文为空）"
          />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { documentsApi, insightsApi, tagsApi } from '@/api'
import type {
  ChunkBrief,
  DocumentOut,
  DuplicatePair,
  OrganizeSuggestion,
  RelatedDocument,
} from '@/api/types'
import MermaidDiagram from '@/components/MermaidDiagram.vue'

const router = useRouter()
const tab = ref('duplicates')
const documents = ref<DocumentOut[]>([])

const threshold = ref(0.1)
const duplicates = ref<DuplicatePair[]>([])
const dupChecked = ref(false)
const loadingDup = ref(false)

const relatedDocId = ref<string | null>(null)
const related = ref<RelatedDocument[]>([])
const relChecked = ref(false)
const loadingRel = ref(false)

const mapDocId = ref<string | null>(null)
const mindmap = ref<{ document_title: string; mermaid: string; note: string } | null>(null)
const loadingMap = ref(false)

const orgDocId = ref<string | null>(null)
const suggestion = ref<OrganizeSuggestion | null>(null)
const loadingOrg = ref(false)

// ---------------- 批量摘要 ----------------
const summaryDocIds = ref<string[]>([])
const summaries = ref<{ document_id: string; title: string; summary: string }[]>([])
const loadingSummary = ref(false)
const summaryDone = ref(false)

/** 后端单次上限 20 篇，这里同样截断，避免用户选了 30 篇却收到 422。 */
async function loadBatchSummary() {
  if (!summaryDocIds.value.length) return
  loadingSummary.value = true
  try {
    const res = await insightsApi.batchSummary(summaryDocIds.value.slice(0, 20))
    summaries.value = res.items
    summaryDone.value = true
    if (res.missing.length) {
      ElMessage.warning(`${res.missing.length} 篇文档不存在或已删除，已跳过`)
    }
    if (res.items.length) ElMessage.success(`已生成 ${res.items.length} 篇摘要`)
  } catch {
    summaries.value = []
  } finally {
    loadingSummary.value = false
  }
}

function openDoc(brief: ChunkBrief) {
  // 带片段 ID 跳转，详情页会滚动定位并高亮。
  // 注意：本项目用 createWebHistory（非 hash 路由），写 `#/documents/...` 只会
  // 给当前地址追加一个 hash，再 reload 会重新加载本页 —— 表现为「点了没反应」。
  router.push({
    path: `/documents/${brief.document_id}`,
    query: { chunk: brief.chunk_id },
  })
}

async function loadDuplicates() {
  loadingDup.value = true
  try {
    const res = await insightsApi.duplicates(threshold.value, 30)
    duplicates.value = res.items
    dupChecked.value = true
    if (!res.items.length) ElMessage.info('未发现达到阈值的相似片段')
  } finally {
    loadingDup.value = false
  }
}

async function loadRelated() {
  if (!relatedDocId.value) return
  loadingRel.value = true
  try {
    const res = await insightsApi.related(relatedDocId.value, 8)
    related.value = res.items
    relChecked.value = true
  } finally {
    loadingRel.value = false
  }
}

async function loadMindmap() {
  if (!mapDocId.value) return
  loadingMap.value = true
  try {
    mindmap.value = await insightsApi.mindmap(mapDocId.value)
  } catch {
    ElMessage.error('生成思维导图失败，请检查模型配置')
  } finally {
    loadingMap.value = false
  }
}

async function loadOrganize() {
  if (!orgDocId.value) return
  loadingOrg.value = true
  try {
    suggestion.value = await insightsApi.organize(orgDocId.value)
  } catch {
    ElMessage.error('生成归档建议失败，请检查模型配置')
  } finally {
    loadingOrg.value = false
  }
}

async function applyTags() {
  if (!suggestion.value || !orgDocId.value) return
  // 先取当前详情，合并已有标签后再写入（setDocumentTags 是覆盖语义）
  const detail = await documentsApi.get(orgDocId.value)
  const existing = (detail.tags ?? []).map((t) => t.name)
  const merged = Array.from(new Set([...existing, ...suggestion.value.tags]))
  await tagsApi.setDocumentTags(orgDocId.value, merged)
  ElMessage.success(`已写入 ${suggestion.value.tags.length} 个建议标签（原有标签保留）`)
  const list = await documentsApi.list({ page: 1, page_size: 100 })
  documents.value = list.items
}

onMounted(async () => {
  const list = await documentsApi.list({ page: 1, page_size: 100 })
  documents.value = list.items
})
</script>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.label {
  font-size: 13px;
  color: var(--kh-text-sub);
}
.hint {
  font-size: 12px;
  color: var(--kh-text-mute);
}
.mt {
  margin-top: 16px;
}
.mt-sm {
  margin-top: 10px;
}
.mb {
  margin-bottom: 12px;
}
.src-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}
.snippet {
  font-size: 12px;
  color: var(--kh-text-sub);
  line-height: 1.6;
}
.sum-item {
  padding: 10px 12px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  margin-bottom: 8px;
}

.sum-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.sum-title {
  font-size: 13px;
  font-weight: 600;
}

.sum-body {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.7;
  margin-top: 4px;
  white-space: pre-wrap;
}

.muted {  color: var(--kh-text-mute);
  font-size: 12px;
}
.empty-hint {
  color: var(--kh-text-mute);
  font-size: 13px;
}
.tag-gap {
  margin-right: 6px;
}
.inner {
  background: var(--kh-bg);
}
.code-block {
  margin: 0;
  padding: 10px 12px;
  background: var(--kh-bg-deep);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
}
</style>
