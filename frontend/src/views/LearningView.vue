<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习辅助</h1>
        <p class="page-sub">
          题目与参考答案均依据知识库资料生成并标注来源；错题本只记录你真实提交且未达标的作答，不会虚构
        </p>
      </div>
      <el-button :loading="exporting" @click="exportAnki">
        导出到 Anki
      </el-button>
    </div>

    <div class="card">
      <el-tabs v-model="tab">
        <!-- ============ 今日复习（间隔复习 SRS）============ -->
        <el-tab-pane label="今日复习" name="review">
          <div class="srs-stats">
            <div class="srs-stat">
              <span class="srs-num">{{ srs?.due ?? 0 }}</span>
              <span class="srs-label">待复习</span>
            </div>
            <div class="srs-stat">
              <span class="srs-num">{{ srs?.reviewed_today ?? 0 }}</span>
              <span class="srs-label">今日已复习</span>
            </div>
            <div class="srs-stat">
              <span class="srs-num">{{ srs?.streak_days ?? 0 }}</span>
              <span class="srs-label">连续学习天数</span>
            </div>
            <div class="srs-stat">
              <span class="srs-num">{{ srs?.total ?? 0 }}</span>
              <span class="srs-label">卡片总数</span>
            </div>
          </div>

          <!-- 近两周复习趋势 + 卡片状态分布（自绘，不引入图表库） -->
          <div class="srs-chart">
            <div class="srs-chart-head">
              <span>近两周复习量</span>
              <span class="muted">
                合计 {{ trendTotal }} 次 · 单日最高 {{ trendMax }} 次
              </span>
            </div>
            <div class="srs-bars">
              <div
                v-for="d in trend"
                :key="d.date"
                class="srs-bar-wrap"
                :title="`${d.date}：${d.count} 次`"
              >
                <div class="srs-bar" :style="{ height: barHeight(d.count) }" />
                <span class="srs-bar-label">{{ d.date.slice(5) }}</span>
              </div>
            </div>
            <div class="srs-dist">
              <span v-for="seg in distribution" :key="seg.label" class="srs-dist-item">
                <i class="srs-dist-dot" :style="{ background: seg.color }" />
                {{ seg.label }} <b>{{ seg.value }}</b>
              </span>
            </div>
          </div>

          <!-- 掌握程度分布：按复习间隔分档的卡片数（自绘横条） -->
          <div v-if="masteryTotal > 0" class="srs-chart">
            <div class="srs-chart-head">
              <span>掌握程度分布</span>
              <span class="muted">按当前复习间隔分档，共 {{ masteryTotal }} 张</span>
            </div>
            <div class="srs-rows">
              <div v-for="m in mastery" :key="m.label" class="srs-row">
                <span class="srs-row-label">{{ m.label }}</span>
                <div class="srs-row-track">
                  <div
                    class="srs-row-fill"
                    :style="{ width: masteryPct(m.count) + '%' }"
                  />
                </div>
                <span class="srs-row-num">{{ m.count }}</span>
              </div>
            </div>
          </div>

          <!-- 遗忘曲线：按间隔分档的实际回忆成功率 -->
          <div v-if="retentionHasData" class="srs-chart">
            <div class="srs-chart-head">
              <span>遗忘曲线</span>
              <span class="muted">
                按间隔统计「上次间隔这么大时还想得起来吗」，数据来自你的真实复习记录
              </span>
            </div>
            <div class="srs-rows">
              <div v-for="r in retention" :key="r.label" class="srs-row">
                <span class="srs-row-label">{{ r.label }}</span>
                <div class="srs-row-track">
                  <div
                    class="srs-row-fill is-retention"
                    :style="{ width: (r.rate ?? 0) * 100 + '%' }"
                  />
                </div>
                <span class="srs-row-num">
                  <template v-if="r.rate == null">—</template>
                  <template v-else>{{ Math.round(r.rate * 100) }}%</template>
                  <small class="muted"> ({{ r.passed }}/{{ r.attempts }})</small>
                </span>
              </div>
            </div>
            <div class="hint">
              「—」表示该间隔档位还没有复习记录，不是通过率为 0。
              曲线整体随间隔下降是正常的——它反映的是你对这套资料的真实记忆保持率。
            </div>
          </div>

          <!-- 复习卡片：正面问题 → 翻面答案 → 评分 -->
          <div v-if="currentCard" class="srs-card">
            <div class="srs-progress">
              第 {{ reviewIndex + 1 }} / {{ reviewQueue.length }} 张
              <span class="muted">
                · 连续通过 {{ currentCard.repetitions }} 次 · 当前间隔
                {{ currentCard.interval_days }} 天
              </span>
            </div>
            <div class="srs-front">{{ currentCard.front }}</div>

            <div v-if="!revealed" class="srs-actions">
              <el-button type="primary" @click="revealed = true">显示答案</el-button>
            </div>
            <template v-else>
              <div class="srs-back">{{ currentCard.back }}</div>
              <div class="srs-rate">
                <el-button @click="rate(1)">重来<small>10 分钟</small></el-button>
                <el-button @click="rate(3)">困难</el-button>
                <el-button type="primary" @click="rate(4)">一般</el-button>
                <el-button type="success" @click="rate(5)">简单</el-button>
              </div>
            </template>
          </div>
          <el-empty v-else description="今天没有待复习的卡片" />

          <div class="srs-generate">
            <div class="section-title">从笔记生成卡片</div>
            <div class="row">
              <el-select
                v-model="genDocId"
                placeholder="选择一篇笔记"
                filterable
                clearable
                style="min-width: 260px"
              >
                <el-option v-for="d in docs" :key="d.id" :label="d.title" :value="d.id" />
              </el-select>
              <el-input-number v-model="genCount" :min="1" :max="30" />
              <el-button type="primary" :loading="generating" @click="generate">生成</el-button>
            </div>
            <div class="muted-sm">
              卡片只依据原文生成并记录来源，不编造资料之外的内容；生成后可编辑或删除。
            </div>
          </div>

          <div class="section-title mt">全部卡片（{{ cards.length }}）</div>
          <div v-for="c in cards" :key="c.id" class="srs-row">
            <div class="srs-row-main">
              <div class="srs-row-front">{{ c.front }}</div>
              <div class="srs-row-back">{{ c.back }}</div>
              <div class="srs-row-meta">
                状态 {{ stateText(c.state) }} · 间隔 {{ c.interval_days }} 天 · 难度
                {{ c.ease.toFixed(2) }}
                <span v-if="c.due_at"> · 下次 {{ fmt(c.due_at) }}</span>
                <span v-if="c.suspended"> · 已暂停</span>
              </div>
            </div>
            <el-button link type="danger" size="small" @click="removeCard(c)">删除</el-button>
          </div>
        </el-tab-pane>

        <!-- ============ 练习 ============ -->
        <el-tab-pane label="模拟面试 / 练习" name="quiz">
          <div class="row">
            <el-input v-model="direction" placeholder="方向（如 docker / vue，可留空）" style="width: 240px" />
            <el-select v-model="difficulty" style="width: 130px">
              <el-option label="基础" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="进阶" value="hard" />
            </el-select>
            <el-input-number v-model="count" :min="1" :max="10" style="width: 130px" />
            <el-button type="primary" :loading="loadingQ" @click="loadQuestions">开始出题</el-button>
            <span class="hint">题目依据知识库生成，来源会标注在每题下方</span>
          </div>

          <div v-if="questions.length" class="mt">
            <el-alert type="info" :closable="false" show-icon :title="questionNote" class="mb" />

            <div v-for="(q, qi) in questions" :key="qi" class="q-card">
              <div class="q-head">
                <span class="q-index">{{ qi + 1 }}</span>
                <span class="q-text">{{ q.question }}</span>
              </div>
              <div v-if="q.source_document_title" class="q-src">
                依据：{{ q.source_document_title }}
              </div>

              <el-input
                v-model="answers[qi]"
                type="textarea"
                :rows="3"
                placeholder="写下你的回答，提交后会依据参考答案评分"
                :disabled="!!results[qi]"
              />

              <div class="row mt-sm">
                <el-button
                  type="primary"
                  size="small"
                  :loading="grading === qi"
                  :disabled="!!results[qi]"
                  @click="submit(qi)"
                >
                  提交并评分
                </el-button>
                <el-button size="small" @click="toggleReference(qi)">
                  {{ shownReference.has(qi) ? '隐藏参考答案' : '查看参考答案' }}
                </el-button>
              </div>

              <div v-if="shownReference.has(qi)" class="reference">
                <div class="ref-title">参考答案（来自知识库）</div>
                <div class="ref-body">{{ q.reference_answer || '（未提供）' }}</div>
              </div>

              <div v-if="results[qi]" class="result">
                <div class="score-line">
                  <el-tag :type="results[qi]!.passed ? 'success' : 'danger'" size="large">
                    {{ results[qi]!.score }} 分
                  </el-tag>
                  <span class="muted">{{ results[qi]!.passed ? '已通过' : '未达标，已计入错题本' }}</span>
                </div>
                <div class="feedback">{{ results[qi]!.feedback }}</div>
                <div v-if="results[qi]!.missing.length" class="missing">
                  <span class="muted">遗漏要点：</span>
                  <el-tag v-for="m in results[qi]!.missing" :key="m" size="small" type="warning" class="tag-gap">
                    {{ m }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- ============ 错题本 ============ -->
        <el-tab-pane label="错题本" name="mistakes">
          <div class="row">
            <el-switch v-model="includeMastered" active-text="含已掌握" @change="loadMistakes" />
            <el-button size="small" @click="loadMistakes">刷新</el-button>
            <span class="hint">仅显示你真实提交过、且得分低于 {{ stats?.pass_score ?? 60 }} 分的题目</span>
          </div>

          <div v-if="mistakes.length" class="mt">
            <div v-for="m in mistakes" :key="m.id" class="q-card">
              <div class="q-head">
                <span class="q-text">{{ m.question }}</span>
                <el-tag :type="m.mastered ? 'success' : 'danger'" size="small">
                  {{ m.score }} 分
                </el-tag>
              </div>
              <div class="q-src">
                {{ m.direction || '综合' }} · {{ m.difficulty || '未标注' }} ·
                {{ fmt(m.created_at) }}
              </div>
              <div class="answer-block">
                <div class="ref-title">你的作答</div>
                <div class="ref-body">{{ m.user_answer || '（未作答）' }}</div>
              </div>
              <div v-if="m.reference_answer" class="answer-block">
                <div class="ref-title">参考答案</div>
                <div class="ref-body">{{ m.reference_answer }}</div>
              </div>
              <div v-if="m.feedback" class="feedback">{{ m.feedback }}</div>
              <div class="row mt-sm">
                <el-button size="small" @click="toggleMastered(m)">
                  {{ m.mastered ? '标记为未掌握' : '标记为已掌握' }}
                </el-button>
                <el-button size="small" type="danger" @click="removeMistake(m)">删除</el-button>
              </div>
            </div>
          </div>
          <div v-else class="empty-hint mt">暂无错题 —— 去练习页做几道题吧</div>
        </el-tab-pane>

        <!-- ============ 统计 ============ -->
        <el-tab-pane label="复习统计" name="stats">
          <el-row :gutter="16" class="mt-sm">
            <el-col :span="6">
              <div class="metric">
                <div class="metric-label">累计作答</div>
                <div class="metric-value">{{ stats?.total_answered ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric">
                <div class="metric-label">待复习错题</div>
                <div class="metric-value">{{ stats?.mistakes_pending ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric">
                <div class="metric-label">已掌握</div>
                <div class="metric-value">{{ stats?.mastered ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric">
                <div class="metric-label">平均分</div>
                <div class="metric-value">{{ stats?.average_score ?? 0 }}</div>
              </div>
            </el-col>
          </el-row>
          <div class="hint mt">及格线：{{ stats?.pass_score ?? 60 }} 分；低于该分数会进入错题本</div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { documentsApi, learningApi } from '@/api'
import type {
  DocumentOut,
  Flashcard,
  GradeResult,
  QuizQuestion,
  QuizRecord,
  ReviewStats,
  SrsStats,
} from '@/api/types'

const tab = ref('review')

const direction = ref('')
const difficulty = ref('medium')
const count = ref(3)
const questions = ref<QuizQuestion[]>([])
const questionNote = ref('')
const loadingQ = ref(false)

const answers = ref<string[]>([])
const results = ref<(GradeResult | null)[]>([])
const shownReference = ref(new Set<number>())
const grading = ref(-1)

const mistakes = ref<QuizRecord[]>([])
const includeMastered = ref(false)
const stats = ref<ReviewStats | null>(null)

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

// ---------------- 今日复习（间隔复习 SRS）----------------
const srs = ref<SrsStats | null>(null)
const exporting = ref(false)

/** 导出到 Anki：拿 blob 存盘。卡片数 0 时直接提示，不下废文件。 */
async function exportAnki() {
  if (!srs.value?.total) {
    ElMessage.info('还没有卡片可导出，先在复习或知识加工里生成几张')
    return
  }
  exporting.value = true
  try {
    const blob = await learningApi.exportAnki()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'knowledgehub-cards-anki.txt'
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(
      `已导出 ${srs.value.total} 张卡片。在 Anki 里「文件 → 导入」选择该文件，勾选「允许 HTML」`,
    )
  } catch {
    /* 错误提示由拦截器统一处理 */
  } finally {
    exporting.value = false
  }
}

// ---------------- 复习趋势（自绘柱状图） ----------------
const trend = computed(() => srs.value?.daily ?? [])
const trendTotal = computed(() => trend.value.reduce((sum, d) => sum + d.count, 0))
const trendMax = computed(() => Math.max(1, ...trend.value.map((d) => d.count)))

/** 柱子高度：有记录至少 4px，没记录固定 2px——两者必须能一眼区分。 */
function barHeight(count: number) {
  if (!count) return '2px'
  return `${Math.max(4, Math.round((count / trendMax.value) * 72))}px`
}

/** 卡片状态分布（颜色只做辅助，数字本身可读）。 */
const distribution = computed(() => [
  { label: '新卡', value: srs.value?.new ?? 0, color: '#909399' },
  { label: '学习中', value: srs.value?.learning ?? 0, color: '#e6a23c' },
  { label: '复习中', value: srs.value?.review ?? 0, color: '#67c23a' },
  { label: '已暂停', value: srs.value?.suspended ?? 0, color: '#c0c4cc' },
])

// ---------------- 掌握程度分布（按复习间隔分档） ----------------
const mastery = computed(() => srs.value?.mastery ?? [])
const masteryTotal = computed(() => mastery.value.reduce((s, m) => s + m.count, 0))
const masteryMax = computed(() => Math.max(1, ...mastery.value.map((m) => m.count)))

/** 横条宽度百分比：用最大值归一，空数据时给 0 而不是 NaN。 */
function masteryPct(count: number) {
  return Math.round((count / masteryMax.value) * 100)
}

// ---------------- 遗忘曲线（按间隔的实际回忆成功率） ----------------
const retention = computed(() => srs.value?.retention ?? [])
/** 至少有一个档位有复习数据才显示整张图，否则全是「—」没有信息量。 */
const retentionHasData = computed(() => retention.value.some((r) => r.attempts > 0))
const cards = ref<Flashcard[]>([])
const reviewQueue = ref<Flashcard[]>([])
const reviewIndex = ref(0)
const revealed = ref(false)
const docs = ref<DocumentOut[]>([])
const genDocId = ref<string | null>(null)
const genCount = ref(8)
const generating = ref(false)

const currentCard = computed(() => reviewQueue.value[reviewIndex.value] ?? null)

const STATE_TEXT: Record<string, string> = {
  new: '新卡片',
  learning: '学习中',
  review: '复习中',
}
function stateText(s: string): string {
  return STATE_TEXT[s] ?? s
}

async function loadSrs() {
  try {
    srs.value = await learningApi.srsStats()
  } catch {
    srs.value = null
  }
}

async function loadCards() {
  try {
    cards.value = (await learningApi.cards({ limit: 200 })).items
  } catch {
    cards.value = []
  }
}

async function loadReviewQueue() {
  try {
    reviewQueue.value = (await learningApi.cards({ due_only: true, limit: 100 })).items
    reviewIndex.value = 0
    revealed.value = false
  } catch {
    reviewQueue.value = []
  }
}

async function loadDocs() {
  try {
    docs.value = (await documentsApi.list({ page: 1, page_size: 100 })).items
  } catch {
    docs.value = []
  }
}

/** 提交评分：1=重来 / 3=困难 / 4=一般 / 5=简单（对应 SM-2 的 0~5 口径）。 */
async function rate(rating: number) {
  const card = currentCard.value
  if (!card) return
  try {
    const res = await learningApi.reviewCard(card.id, rating)
    srs.value = res.stats
    reviewIndex.value += 1
    revealed.value = false
    if (reviewIndex.value >= reviewQueue.value.length) {
      ElMessage.success('本轮复习完成')
      await Promise.all([loadReviewQueue(), loadCards(), loadSrs()])
    }
  } catch {
    /* 错误提示由拦截器统一处理 */
  }
}

async function generate() {
  if (!genDocId.value) {
    ElMessage.warning('请先选择一篇笔记')
    return
  }
  generating.value = true
  try {
    const res = await learningApi.generateCards({
      document_id: genDocId.value,
      count: genCount.value,
    })
    ElMessage.success(`已生成 ${res.total} 张卡片`)
    await Promise.all([loadCards(), loadSrs(), loadReviewQueue()])
  } catch {
    /* 错误提示由拦截器统一处理 */
  } finally {
    generating.value = false
  }
}

async function removeCard(c: Flashcard) {
  try {
    await ElMessageBox.confirm('删除这张卡片？复习记录会一并删除。', '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  await learningApi.removeCard(c.id)
  await Promise.all([loadCards(), loadSrs(), loadReviewQueue()])
}

async function loadQuestions() {
  loadingQ.value = true
  try {
    const res = await learningApi.questions({
      count: count.value,
      direction: direction.value || undefined,
      difficulty: difficulty.value,
      mode: direction.value ? 'interview' : 'review',
    })
    questions.value = res.questions
    questionNote.value = res.note
    answers.value = res.questions.map(() => '')
    results.value = res.questions.map(() => null)
    shownReference.value = new Set()
  } catch {
    ElMessage.error('出题失败，请检查模型配置或先导入文档')
  } finally {
    loadingQ.value = false
  }
}

function toggleReference(qi: number) {
  if (shownReference.value.has(qi)) shownReference.value.delete(qi)
  else shownReference.value.add(qi)
}

async function submit(qi: number) {
  const q = questions.value[qi]
  if (!q) return
  grading.value = qi
  try {
    results.value[qi] = await learningApi.grade({
      question: q.question,
      reference_answer: q.reference_answer,
      user_answer: answers.value[qi] || '',
      direction: direction.value || undefined,
      difficulty: difficulty.value,
      source_chunk_id: q.source_chunk_id,
      source_document_id: q.source_document_id,
    })
    await loadStats()
  } catch {
    ElMessage.error('评分失败，请检查模型配置')
  } finally {
    grading.value = -1
  }
}

async function loadMistakes() {
  // 各加载器各自兜底：任何一个接口失败都不应让整页无法渲染
  try {
    const res = await learningApi.mistakes(includeMastered.value)
    mistakes.value = res.items
  } catch {
    /* 具体错误已由请求层统一提示 */
  }
}

async function toggleMastered(m: QuizRecord) {
  await learningApi.setMastered(m.id, !m.mastered)
  await Promise.all([loadMistakes(), loadStats()])
}

async function removeMistake(m: QuizRecord) {
  try {
    await ElMessageBox.confirm('删除这条记录？', '删除确认', { type: 'warning' })
  } catch {
    return // 用户取消
  }
  await learningApi.removeMistake(m.id)
  ElMessage.success('已删除')
  await Promise.all([loadMistakes(), loadStats()])
}

async function loadStats() {
  try {
    stats.value = await learningApi.stats()
  } catch {
    /* 同上 */
  }
}

onMounted(() => {
  // allSettled：单个接口失败不应让整个页面挂死
  void Promise.allSettled([
    loadMistakes(),
    loadStats(),
    loadSrs(),
    loadCards(),
    loadReviewQueue(),
    loadDocs(),
  ])
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
.q-card {
  border: 0.5px solid var(--kh-border-light);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: var(--kh-panel);
}
.q-head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
}
.q-index {
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--kh-primary-soft);
  color: var(--kh-primary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.q-text {
  font-weight: 500;
  line-height: 1.6;
  flex: 1;
}
.q-src {
  font-size: 12px;
  color: var(--kh-text-mute);
  margin-bottom: 8px;
}
.reference,
.answer-block {
  margin-top: 10px;
  padding: 8px 10px;
  background: var(--kh-bg-deep);
  border-radius: 6px;
}
.ref-title {
  font-size: 12px;
  color: var(--kh-text-mute);
  margin-bottom: 4px;
}
.ref-body {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.result {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--kh-border-light);
}
.score-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.feedback {
  font-size: 13px;
  line-height: 1.7;
  color: var(--kh-text-sub);
}
.missing {
  margin-top: 6px;
}
.tag-gap {
  margin-right: 6px;
}
.metric {
  background: var(--kh-bg);
  border-radius: 8px;
  padding: 14px 16px;
}
.metric-label {
  font-size: 12px;
  color: var(--kh-text-mute);
  margin-bottom: 6px;
}
.metric-value {
  font-size: 24px;
  font-weight: 500;
}
.empty-hint {
  color: var(--kh-text-mute);
  font-size: 13px;
}
/* ---- 今日复习（间隔复习 SRS） ---- */
.section-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
}

.srs-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

/* ---------------- 复习趋势（自绘柱状图） ---------------- */
.srs-chart {
  border: 1px solid var(--kh-border-light);
  background: var(--kh-panel);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 16px;
}

.srs-chart-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
  margin-bottom: 10px;
}

.srs-bars {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 96px;
  overflow-x: auto;
}

.srs-bar-wrap {
  flex: 1;
  min-width: 22px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  gap: 4px;
}

.srs-bar {
  width: 100%;
  max-width: 22px;
  background: var(--kh-primary);
  border-radius: 3px 3px 0 0;
  transition: height 0.2s ease;
}

.srs-bar-label {
  font-size: 10px;
  color: var(--kh-text-mute);
  white-space: nowrap;
}

.srs-dist {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--kh-border-light);
  font-size: 12px;
  color: var(--kh-text-sub);
}

.srs-dist-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.srs-dist-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

/* ---------------- 掌握度分布 / 遗忘曲线（横条） ---------------- */
.srs-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}

.srs-row {
  display: grid;
  grid-template-columns: 64px 1fr 92px;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
}

.srs-row-label {
  color: var(--kh-text-sub);
  text-align: right;
}

.srs-row-track {
  height: 10px;
  border-radius: 5px;
  background: var(--kh-border-light);
  overflow: hidden;
}

.srs-row-fill {
  height: 100%;
  border-radius: 5px;
  background: var(--kh-primary);
  /* 过渡让数据刷新时条长平滑变化，不会突然跳一下 */
  transition: width 0.3s ease;
  min-width: 0;
}

/* 遗忘曲线用另一种色相：与掌握度分布区分开，避免两张图看混 */
.srs-row-fill.is-retention {
  background: #67c23a;
}

.srs-row-num {
  font-variant-numeric: tabular-nums;
  color: var(--kh-text);
}

.srs-row-num small {
  font-size: 11px;
}

/* 窄屏：标签列收窄，数字列允许换行 */
@media (max-width: 860px) {
  .srs-row {
    grid-template-columns: 52px 1fr 84px;
    gap: 6px;
    font-size: 12px;
  }
}

.srs-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  padding: 12px 14px;
}

.srs-num {
  font-size: 20px;
  font-weight: 600;
}

.srs-label {
  font-size: 12px;
  color: var(--kh-text-sub);
}

.srs-card {
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  padding: 18px;
  margin-bottom: 18px;
}

.srs-progress {
  font-size: 12px;
  color: var(--kh-text-sub);
  margin-bottom: 12px;
}

.srs-front {
  font-size: 16px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.srs-actions {
  margin-top: 16px;
}

.srs-back {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed var(--kh-border);
  font-size: 14px;
  line-height: 1.75;
  color: var(--kh-text-sub);
  white-space: pre-wrap;
}

.srs-rate {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.srs-rate small {
  display: block;
  font-size: 10px;
  color: var(--kh-text-mute);
}

.srs-generate {
  margin-top: 8px;
}

.srs-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--kh-border-light);
}

.srs-row-main {
  min-width: 0;
}

.srs-row-front {
  font-size: 13.5px;
}

.srs-row-back {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  margin-top: 2px;
}

.srs-row-meta {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  margin-top: 3px;
}

.muted-sm {
  font-size: 12.5px;
  color: var(--kh-text-mute);
  margin-top: 8px;
}
</style>
