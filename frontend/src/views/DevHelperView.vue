<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">项目开发辅助</h1>
        <p class="page-sub">
          代码评审区分「知识库已记录规范」与「AI 新建议」；故障排查区分「已确认」与「待验证」；
          时间线无法确认日期的一律标注为未知
        </p>
      </div>
    </div>

    <div class="card">
      <el-tabs v-model="tab">
        <!-- ============ 代码评审 ============ -->
        <el-tab-pane label="代码评审" name="review">
          <div class="row">
            <el-input v-model="language" placeholder="语言（如 java / python）" style="width: 180px" />
            <el-input v-model="focus" placeholder="关注点（如 命名规范 / 异常处理）" style="width: 240px" />
          </div>
          <el-input
            v-model="code"
            type="textarea"
            :rows="10"
            class="mt-sm"
            placeholder="粘贴需要评审的代码"
          />
          <div class="row mt-sm">
            <el-button type="primary" :loading="loadingReview" @click="doReview">开始评审</el-button>
            <span class="hint">会先检索知识库作为依据，再给出意见</span>
          </div>

          <div v-if="review" class="mt">
            <el-alert type="info" :closable="false" show-icon :title="review.note" class="mb" />
            <div v-if="review.summary" class="summary">总评：{{ review.summary }}</div>

            <el-row :gutter="16" class="mt-sm">
              <el-col :span="12">
                <div class="panel-title">
                  <el-tag type="success" size="small">知识库依据</el-tag>
                  <span class="muted">来自你的知识库记录</span>
                </div>
                <div v-if="review.from_knowledge.length">
                  <div v-for="(p, i) in review.from_knowledge" :key="i" class="point">
                    <div class="point-text">{{ p.point }}</div>
                    <div v-if="p.basis" class="point-basis">依据 {{ p.basis }}</div>
                  </div>
                </div>
                <div v-else class="empty-hint">知识库中没有可对照的规范</div>
              </el-col>
              <el-col :span="12">
                <div class="panel-title">
                  <el-tag type="warning" size="small">AI 新建议</el-tag>
                  <span class="muted">非知识库记录，来自通用工程经验</span>
                </div>
                <div v-if="review.suggestions.length">
                  <div v-for="(p, i) in review.suggestions" :key="i" class="point">
                    <div class="point-text">{{ p.point }}</div>
                    <div v-if="p.reason" class="point-basis">{{ p.reason }}</div>
                  </div>
                </div>
                <div v-else class="empty-hint">无额外建议</div>
              </el-col>
            </el-row>
          </div>
        </el-tab-pane>

        <!-- ============ 故障排查 ============ -->
        <el-tab-pane label="故障排查" name="troubleshoot">
          <el-input v-model="symptom" placeholder="描述故障现象（如：容器启动后立刻退出）" />
          <el-input
            v-model="contextHint"
            class="mt-sm"
            placeholder="环境 / 上下文（可选）"
          />
          <div class="row mt-sm">
            <el-button type="primary" :loading="loadingTs" @click="doTroubleshoot">开始排查</el-button>
          </div>

          <div v-if="trouble" class="mt">
            <el-alert type="warning" :closable="false" show-icon :title="trouble.note" class="mb" />

            <div class="panel-title">
              <el-tag type="success" size="small">已确认（知识库有记录）</el-tag>
            </div>
            <div v-if="trouble.confirmed.length">
              <div v-for="(c, i) in trouble.confirmed" :key="i" class="point">
                <div class="point-text">{{ c.cause }}</div>
                <div v-if="c.basis" class="point-basis">依据 {{ c.basis }}</div>
                <div v-if="c.action" class="point-action">处理：{{ c.action }}</div>
              </div>
            </div>
            <div v-else class="empty-hint">知识库中没有记录该现象的确定原因</div>

            <div class="panel-title mt">
              <el-tag type="warning" size="small">待验证（推测）</el-tag>
              <span class="muted">必须先验证再据此处理</span>
            </div>
            <div v-if="trouble.possible.length">
              <div v-for="(c, i) in trouble.possible" :key="i" class="point">
                <div class="point-text">{{ c.cause }}</div>
                <div v-if="c.verify" class="point-action">验证方式：{{ c.verify }}</div>
                <div v-if="c.action" class="point-action">验证后处理：{{ c.action }}</div>
              </div>
            </div>
            <div v-else class="empty-hint">无推测项</div>

            <div v-if="trouble.need_more_info.length" class="mt">
              <div class="panel-title">需要补充的信息</div>
              <ul class="plain-list">
                <li v-for="(n, i) in trouble.need_more_info" :key="i">{{ n }}</li>
              </ul>
            </div>
          </div>
        </el-tab-pane>

        <!-- ============ 需求拆解 ============ -->
        <el-tab-pane label="需求拆解" name="breakdown">
          <el-input
            v-model="requirement"
            type="textarea"
            :rows="4"
            placeholder="粘贴需求描述"
          />
          <div class="row mt-sm">
            <el-button type="primary" :loading="loadingBd" @click="doBreakdown">拆解为任务</el-button>
          </div>

          <div v-if="breakdown" class="mt">
            <el-alert type="info" :closable="false" show-icon :title="breakdown.note" class="mb" />
            <div v-if="breakdown.goal" class="summary">目标：{{ breakdown.goal }}</div>

            <el-table :data="breakdown.tasks" class="mt-sm" size="small">
              <el-table-column type="index" width="50" />
              <el-table-column prop="title" label="任务" min-width="180" />
              <el-table-column prop="detail" label="具体内容" min-width="240" show-overflow-tooltip />
              <el-table-column prop="acceptance" label="验收标准" min-width="180" show-overflow-tooltip />
              <el-table-column label="依据" width="100">
                <template #default="{ row }">
                  <el-tag v-if="row.basis" size="small" type="success">{{ row.basis }}</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain">AI 推断</el-tag>
                </template>
              </el-table-column>
            </el-table>

            <el-row v-if="breakdown.risks.length || breakdown.assumptions.length" :gutter="16" class="mt">
              <el-col :span="12">
                <div class="panel-title">风险与不确定点</div>
                <ul class="plain-list">
                  <li v-for="(r, i) in breakdown.risks" :key="i">{{ r }}</li>
                </ul>
              </el-col>
              <el-col :span="12">
                <div class="panel-title">
                  AI 做的假设
                  <span class="muted">（非你的原话）</span>
                </div>
                <ul class="plain-list">
                  <li v-for="(a, i) in breakdown.assumptions" :key="i">{{ a }}</li>
                </ul>
              </el-col>
            </el-row>
          </div>
        </el-tab-pane>

        <!-- ============ 项目时间线 ============ -->
        <el-tab-pane label="项目时间线" name="timeline">
          <div class="row">
            <el-select v-model="timelineDocId" placeholder="选择文档（留空则取最近 5 篇）" clearable style="width: 320px" filterable>
              <el-option v-for="d in documents" :key="d.id" :label="d.title" :value="d.id" />
            </el-select>
            <el-button type="primary" :loading="loadingTl" @click="doTimeline">生成时间线</el-button>
            <span class="hint">无法从原文确认日期的事件会标记为「日期未知」</span>
          </div>

          <div v-if="timeline" class="mt">
            <el-alert type="info" :closable="false" show-icon :title="timeline.note" class="mb" />
            <div class="hint mb">
              来源：{{ timeline.documents.join('、') }} ｜ 共 {{ timeline.total }} 个事件，
              其中 {{ timeline.undated }} 个日期未知
            </div>
            <div v-for="(e, i) in timeline.events" :key="i" class="tl-item">
              <div class="tl-date">
                <el-tag v-if="e.date_known" size="small" type="success">{{ e.date }}</el-tag>
                <el-tag v-else size="small" type="info" effect="plain">日期未知</el-tag>
              </div>
              <div class="tl-body">
                <div class="tl-event">{{ e.event }}</div>
                <div v-if="e.source" class="muted">来源：{{ e.source }}</div>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { devhelperApi, documentsApi } from '@/api'
import type {
  BreakdownResult,
  CodeReviewResult,
  DocumentOut,
  TimelineResult,
  TroubleshootResult,
} from '@/api/types'

const tab = ref('review')
const documents = ref<DocumentOut[]>([])

const language = ref('')
const focus = ref('')
const code = ref('')
const review = ref<CodeReviewResult | null>(null)
const loadingReview = ref(false)

const symptom = ref('')
const contextHint = ref('')
const trouble = ref<TroubleshootResult | null>(null)
const loadingTs = ref(false)

const requirement = ref('')
const breakdown = ref<BreakdownResult | null>(null)
const loadingBd = ref(false)

const timelineDocId = ref<string | null>(null)
const timeline = ref<TimelineResult | null>(null)
const loadingTl = ref(false)

async function doReview() {
  if (!code.value.trim()) {
    ElMessage.warning('请先粘贴代码')
    return
  }
  loadingReview.value = true
  try {
    review.value = await devhelperApi.review({
      code: code.value,
      language: language.value || undefined,
      focus: focus.value || undefined,
    })
  } catch {
    ElMessage.error('评审失败，请检查模型配置')
  } finally {
    loadingReview.value = false
  }
}

async function doTroubleshoot() {
  if (!symptom.value.trim()) {
    ElMessage.warning('请描述故障现象')
    return
  }
  loadingTs.value = true
  try {
    trouble.value = await devhelperApi.troubleshoot({
      symptom: symptom.value,
      context: contextHint.value || undefined,
    })
  } catch {
    ElMessage.error('排查失败，请检查模型配置')
  } finally {
    loadingTs.value = false
  }
}

async function doBreakdown() {
  if (!requirement.value.trim()) {
    ElMessage.warning('请填写需求描述')
    return
  }
  loadingBd.value = true
  try {
    breakdown.value = await devhelperApi.breakdown({ requirement: requirement.value })
  } catch {
    ElMessage.error('拆解失败，请检查模型配置')
  } finally {
    loadingBd.value = false
  }
}

async function doTimeline() {
  loadingTl.value = true
  try {
    timeline.value = await devhelperApi.timeline({
      document_id: timelineDocId.value || undefined,
    })
  } catch {
    ElMessage.error('生成时间线失败，请检查模型配置')
  } finally {
    loadingTl.value = false
  }
}

onMounted(async () => {
  // 文档列表拉取失败不应让整个页面挂死（错误提示由请求层统一弹出）
  try {
    const list = await documentsApi.list({ page: 1, page_size: 100 })
    documents.value = list.items
  } catch {
    documents.value = []
  }
})
</script>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.hint {
  font-size: 12px;
  color: var(--kh-text-mute);
}
.muted {
  color: var(--kh-text-mute);
  font-size: 12px;
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
.summary {
  font-size: 13px;
  line-height: 1.7;
  padding: 8px 12px;
  background: var(--kh-bg-deep);
  border-radius: 6px;
}
.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  margin: 12px 0 8px;
}
.point {
  border-left: 2px solid var(--kh-primary-border);
  padding: 6px 0 6px 10px;
  margin-bottom: 8px;
}
.point-text {
  font-size: 13px;
  line-height: 1.65;
}
.point-basis,
.point-action {
  font-size: 12px;
  color: var(--kh-text-mute);
  margin-top: 3px;
}
.plain-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.9;
  color: var(--kh-text-sub);
}
.empty-hint {
  color: var(--kh-text-mute);
  font-size: 13px;
  padding: 6px 0;
}
.tl-item {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--kh-border-light);
}
.tl-date {
  flex: none;
  width: 110px;
}
.tl-body {
  flex: 1;
}
.tl-event {
  font-size: 13px;
  line-height: 1.65;
}
</style>
