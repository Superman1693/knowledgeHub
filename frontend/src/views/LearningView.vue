<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习辅助</h1>
        <p class="page-sub">
          题目与参考答案均依据知识库资料生成并标注来源；错题本只记录你真实提交且未达标的作答，不会虚构
        </p>
      </div>
    </div>

    <div class="card">
      <el-tabs v-model="tab">
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
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { learningApi } from '@/api'
import type { GradeResult, QuizQuestion, QuizRecord, ReviewStats } from '@/api/types'

const tab = ref('quiz')

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
  const res = await learningApi.mistakes(includeMastered.value)
  mistakes.value = res.items
}

async function toggleMastered(m: QuizRecord) {
  await learningApi.setMastered(m.id, !m.mastered)
  await Promise.all([loadMistakes(), loadStats()])
}

async function removeMistake(m: QuizRecord) {
  await ElMessageBox.confirm('删除这条记录？', '删除确认', { type: 'warning' })
  await learningApi.removeMistake(m.id)
  ElMessage.success('已删除')
  await Promise.all([loadMistakes(), loadStats()])
}

async function loadStats() {
  stats.value = await learningApi.stats()
}

onMounted(async () => {
  await Promise.all([loadMistakes(), loadStats()])
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
</style>
