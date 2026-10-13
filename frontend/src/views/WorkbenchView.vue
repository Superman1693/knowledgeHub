<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">工作台</h1>
        <p class="page-sub">
          你的私人知识库总览 · 所有数据都保存在本机，不会上传到任何第三方
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <!-- ================= 知识库概览（PKM：打开即用） ================= -->
    <section class="pkm">
      <div class="pkm-top">
        <div class="pkm-daily">
          <div>
            <div class="pkm-daily-label">今日笔记</div>
            <div class="pkm-daily-title">{{ wb.daily_title }}</div>
          </div>
          <el-button type="primary" @click="openDaily">
            <el-icon><EditPen /></el-icon>
            <span>{{ wb.daily_note ? '继续记录' : '开始记录' }}</span>
          </el-button>
        </div>
        <div class="pkm-quick">
          <el-button @click="$router.push('/notes/new')">
            <el-icon><Plus /></el-icon><span>新建笔记</span>
          </el-button>
          <el-button @click="$router.push('/trash')">
            <el-icon><Delete /></el-icon><span>回收站 {{ wb.counts.trash }}</span>
          </el-button>
          <el-button :loading="scanning" @click="scan">
            <el-icon><Refresh /></el-icon><span>扫描同步</span>
          </el-button>
        </div>
      </div>

      <!-- 启动时的**只读**扫描结果：只提示，不自动改动任何内容 -->
      <el-alert
        v-if="startupAlert"
        class="pkm-alert"
        type="warning"
        show-icon
        :closable="true"
        :title="startupAlert"
      >
        <div class="pkm-alert-body">
          可能是你在编辑器里直接改了 <code>.md</code>，或往 <code>data/documents</code>
          放了文件。点右上角「扫描同步」可让库与磁盘重新一致（会先列出差异再让你确认）。
        </div>
      </el-alert>

      <div class="pkm-stats">
        <button class="pkm-stat" type="button" @click="$router.push('/documents')">
          <span class="pkm-stat-num">{{ wb.counts.documents }}</span>
          <span class="pkm-stat-label">全部文档</span>
        </button>
        <button class="pkm-stat" type="button" @click="$router.push('/documents?view=note')">
          <span class="pkm-stat-num">{{ wb.counts.notes }}</span>
          <span class="pkm-stat-label">我的笔记</span>
        </button>
        <button class="pkm-stat" type="button" @click="$router.push('/documents?view=favorite')">
          <span class="pkm-stat-num">{{ wb.counts.favorites }}</span>
          <span class="pkm-stat-label">收藏</span>
        </button>
        <button class="pkm-stat" type="button" @click="$router.push('/documents')">
          <span class="pkm-stat-num">{{ wb.counts.inbox }}</span>
          <span class="pkm-stat-label">待整理</span>
        </button>
        <button class="pkm-stat" type="button" @click="$router.push('/search')">
          <span class="pkm-stat-num">{{ wb.chunk_total }}</span>
          <span class="pkm-stat-label">知识片段</span>
        </button>
        <button class="pkm-stat" type="button" @click="$router.push('/learning')">
          <span class="pkm-stat-num">{{ srsDue }}</span>
          <span class="pkm-stat-label">待复习</span>
        </button>
      </div>

      <div class="pkm-grid">
        <div v-for="card in pkmCards" :key="card.key" class="pkm-card">
          <div class="pkm-card-head">
            <span>{{ card.title }}</span>
            <span class="pkm-card-hint">{{ card.hint }}</span>
          </div>
          <div v-if="!card.items.length" class="pkm-empty">{{ card.empty }}</div>
          <button
            v-for="n in card.items"
            :key="n.id"
            class="pkm-item"
            type="button"
            @click="openNote(n)"
          >
            <el-icon class="pkm-item-icon"><Document /></el-icon>
            <span class="pkm-item-title">{{ n.title }}</span>
            <span v-if="n.ai_enabled === false" class="pkm-item-lock">私密</span>
            <span class="pkm-item-time">{{ short(n.updated_at) }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- ================= 新手引导 ================= -->
    <section v-if="isFirstRun" class="hero">
      <div class="hero-main">
        <div class="hero-badge">首次使用</div>
        <h2 class="hero-title">三步把资料变成可问答的知识库</h2>
        <p class="hero-desc">
          KnowledgeHub 会把你导入的文档切分、向量化并建立索引，
          之后你可以用自然语言提问，回答会标注引用来源。
        </p>

        <div class="steps">
          <div
            v-for="(s, i) in steps"
            :key="s.key"
            class="step"
            :class="{ done: s.done }"
          >
            <div class="step-index">
              <el-icon v-if="s.done"><Check /></el-icon>
              <span v-else>{{ i + 1 }}</span>
            </div>
            <div class="step-body">
              <div class="step-title">
                {{ s.title }}
                <span v-if="s.done" class="step-done-tag">已完成</span>
              </div>
              <div class="step-desc">{{ s.desc }}</div>
            </div>
            <el-button
              :type="s.done ? 'default' : 'primary'"
              size="small"
              class="step-btn"
              @click="$router.push(s.to)"
            >
              {{ s.done ? '查看' : s.action }}
            </el-button>
          </div>
        </div>
      </div>

      <div class="hero-side">
        <div class="hero-side-title">它能做什么</div>
        <ul class="feature-list">
          <li><el-icon><Search /></el-icon><span>关键词 + 语义混合检索，找得到同义表达</span></li>
          <li><el-icon><ChatDotRound /></el-icon><span>基于原文问答，每条结论标注来源</span></li>
          <li><el-icon><Notebook /></el-icon><span>自定义术语词典，优先采用你的定义</span></li>
          <li><el-icon><Lock /></el-icon><span>本地运行，数据不出本机</span></li>
        </ul>
      </div>
    </section>

    <!-- ================= 统计 ================= -->
    <section class="stat-grid mt">
      <div v-for="s in statCards" :key="s.label" class="stat-card">
        <div class="stat-icon" :class="s.tone"><el-icon><component :is="s.icon" /></el-icon></div>
        <div>
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </section>

    <!-- ================= 提示 ================= -->
    <el-alert
      v-if="status.failed > 0"
      class="mt"
      type="warning"
      :closable="false"
      show-icon
    >
      <template #title>
        有 {{ status.failed }} 个文档处理失败
      </template>
      <div class="alert-body">
        通常是嵌入模型不可用导致。可在「文档管理」中查看原因，修复模型后点「重建索引」。
        <el-button link type="primary" @click="$router.push('/documents')">去处理</el-button>
      </div>
    </el-alert>

    <el-alert
      v-if="status.partial > 0 && status.failed === 0"
      class="mt"
      type="info"
      :closable="false"
      show-icon
    >
      <template #title>
        {{ status.partial }} 个文档仅完成分块（未向量化）
      </template>
      <div class="alert-body">
        关键词检索可用，语义检索暂不可用。配置嵌入模型后重建索引即可补齐。
      </div>
    </el-alert>

    <!-- ================= 主体两栏 ================= -->
    <div class="grid-2 mt">
      <div class="card">
        <div class="card-title">
          <el-icon><Aim /></el-icon>快捷入口
        </div>
        <div class="quick-grid">
          <button class="quick" type="button" @click="$router.push('/upload')">
            <el-icon><UploadFilled /></el-icon>
            <span class="quick-title">导入文档</span>
            <span class="quick-desc">支持 md / txt / pdf / docx / 代码</span>
          </button>
          <button class="quick" type="button" @click="$router.push('/chat')">
            <el-icon><ChatDotRound /></el-icon>
            <span class="quick-title">AI 问答</span>
            <span class="quick-desc">基于知识库提问并标注来源</span>
          </button>
          <button class="quick" type="button" @click="$router.push('/search')">
            <el-icon><Search /></el-icon>
            <span class="quick-title">知识检索</span>
            <span class="quick-desc">关键词 / 语义 / 混合三种模式</span>
          </button>
          <button class="quick" type="button" @click="$router.push('/glossary')">
            <el-icon><Notebook /></el-icon>
            <span class="quick-title">术语词典</span>
            <span class="quick-desc">自定义缩写与项目名词</span>
          </button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <el-icon><TrendCharts /></el-icon>索引状态
        </div>
        <div class="index-rows">
          <div class="index-row">
            <span class="index-label">文档总数</span>
            <span class="index-value">{{ status.document_total }}</span>
          </div>
          <div class="index-row">
            <span class="index-label">已索引（含向量）</span>
            <span class="index-value is-success">{{ status.indexed }}</span>
          </div>
          <div class="index-row">
            <span class="index-label">仅分块（无向量）</span>
            <span class="index-value" :class="{ 'is-warning': status.partial > 0 }">
              {{ status.partial }}
            </span>
          </div>
          <div class="index-row">
            <span class="index-label">处理中 / 等待</span>
            <span class="index-value">{{ status.processing + status.pending }}</span>
          </div>
          <div class="index-row">
            <span class="index-label">知识片段总数</span>
            <span class="index-value">{{ status.chunk_total }}</span>
          </div>
          <div class="index-row">
            <span class="index-label">已向量化片段</span>
            <span class="index-value">{{ status.embedded_chunks }}</span>
          </div>
        </div>
        <div class="index-bar">
          <div class="index-bar-fill" :style="{ width: embedRatio + '%' }" />
        </div>
        <div class="index-bar-label">
          向量化覆盖率 {{ embedRatio }}%
          <el-button link type="primary" size="small" @click="$router.push('/settings')">
            模型设置
          </el-button>
        </div>
      </div>
    </div>

    <!-- ================= 最近文档 ================= -->
    <div class="card mt">
      <div class="card-title">
        <el-icon><Clock /></el-icon>最近更新的文档
        <span class="spacer" />
        <el-button link type="primary" size="small" @click="$router.push('/documents')">
          查看全部
        </el-button>
      </div>
      <el-table :data="recent" size="default" v-loading="loading">
        <el-table-column prop="title" label="标题" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" @click="$router.push(`/documents/${row.id}`)">
              {{ row.title }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="92" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small" effect="light">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="片段" width="80" />
        <el-table-column prop="updated_at" label="更新时间" width="180">
          <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <div class="empty-icon"><el-icon><DocumentAdd /></el-icon></div>
            <div class="empty-title">还没有文档</div>
            <div class="empty-desc">
              导入第一份资料，就能开始检索和问答了。支持 Markdown、TXT、PDF、Word 与常见代码文件。
            </div>
            <el-button type="primary" @click="$router.push('/upload')">
              <el-icon><UploadFilled /></el-icon> 导入文档
            </el-button>
          </div>
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Aim,
  ChatDotRound,
  Check,
  Clock,
  DocumentAdd,
  Lock,
  Notebook,
  Refresh,
  Search,
  TrendCharts,
  UploadFilled,
} from '@element-plus/icons-vue'
import { chatApi, documentsApi, learningApi, settingsApi, workspaceApi } from '@/api'
import type {
  DocumentOut,
  IndexStatus,
  NoteBrief,
  SettingsOut,
  WorkbenchOut,
} from '@/api/types'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const router = useRouter()
const loading = ref(false)
const recent = ref<DocumentOut[]>([])
const settings = ref<SettingsOut | null>(null)
const conversationCount = ref(0)
const scanning = ref(false)

/** 启动只读扫描的提示文案；三项都为 0 时不显示。 */
const startupAlert = computed(() => {
  const s = wb.value.startup_scan
  if (!s) return ''
  const parts: string[] = []
  if (s.changed_count) parts.push(`${s.changed_count} 个文件被外部修改`)
  if (s.missing_count) parts.push(`${s.missing_count} 个记录找不到对应文件`)
  if (s.orphan_count) parts.push(`${s.orphan_count} 个未收录文件`)
  return parts.length ? `启动检查发现：${parts.join('、')}` : ''
})

/** 工作台汇总（PKM 概览区数据）。 */
const wb = ref<WorkbenchOut>({
  recent_edited: [],
  recent_viewed: [],
  inbox: [],
  favorites: [],
  counts: { documents: 0, notes: 0, favorites: 0, inbox: 0, trash: 0, failed: 0, private: 0 },
  chunk_total: 0,
  daily_note: null,
  daily_title: '',
})

/** 四张卡片：最近编辑 / 最近访问 / 待整理 / 收藏 */
const pkmCards = computed(() => [
  {
    key: 'edited',
    title: '最近编辑',
    hint: '按更新时间',
    empty: '还没有内容，点上方「新建笔记」开始',
    items: wb.value.recent_edited as NoteBrief[],
  },
  {
    key: 'viewed',
    title: '最近访问',
    hint: '按访问时间',
    empty: '还没有访问记录',
    items: wb.value.recent_viewed as NoteBrief[],
  },
  {
    key: 'inbox',
    title: '待整理（收集箱）',
    hint: '尚未归类的文档',
    empty: '收集箱是空的，很好',
    items: wb.value.inbox as NoteBrief[],
  },
  {
    key: 'fav',
    title: '收藏',
    hint: '常用笔记',
    empty: '在文档列表点星标即可收藏',
    items: wb.value.favorites as NoteBrief[],
  },
])

function short(v?: string | null): string {
  if (!v) return ''
  const d = new Date(v)
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  if (d.getTime() >= start) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

/** 打开笔记：应用内笔记进编辑器，导入文档进详情页。 */
function openNote(n: NoteBrief) {
  if (n.source === 'note') router.push(`/notes/${n.id}/edit`)
  else router.push(`/documents/${n.id}`)
}

/** 今日笔记：不存在则创建后进入编辑器。 */
async function openDaily() {
  try {
    const doc = await workspaceApi.daily()
    router.push(`/notes/${doc.id}/edit`)
  } catch {
    /* 错误提示由拦截器处理 */
  }
}

/** 扫描磁盘与库的差异并同步（外部改过 .md 时用）。 */
async function scan() {
  scanning.value = true
  try {
    // 先只读扫描：把「未收录文件」交给用户决定，不静默导入
    const preview = await workspaceApi.scan(false, false)
    let registerOrphans = false
    if (preview.orphan_count > 0) {
      try {
        await ElMessageBox.confirm(
          `发现 ${preview.orphan_count} 个未收录文件（直接放在 data/documents 目录里的）。` +
            '收录后会作为知识库文档参与检索与问答，是否一并收录？',
          '发现未收录文件',
          { type: 'info', confirmButtonText: '一并收录', cancelButtonText: '仅重建索引' },
        )
        registerOrphans = true
      } catch {
        registerOrphans = false
      }
    }

    const res = await workspaceApi.scan(true, registerOrphans)
    if (!res.changed_count && !res.orphan_count && !res.missing_count) {
      ElMessage.success('磁盘与知识库一致，无需同步')
    } else {
      const parts: string[] = []
      if (res.applied.reindexed) parts.push(`重建索引 ${res.applied.reindexed} 篇`)
      if (res.applied.registered.length) parts.push(`收录 ${res.applied.registered.length} 个文件`)
      if (res.missing_count) parts.push(`${res.missing_count} 个文件已丢失`)
      if (res.orphan_count) parts.push(`${res.orphan_count} 个未收录文件未处理`)
      ElMessage.success(parts.length ? `同步完成：${parts.join('，')}` : '同步完成')
    }
    await refreshAll()
  } catch {
    /* 错误提示由拦截器处理 */
  } finally {
    scanning.value = false
  }
}

async function loadWorkbench() {
  try {
    wb.value = await workspaceApi.workbench()
  } catch {
    /* 概览失败不阻塞页面 */
  }
}

/** 待复习卡片数（间隔复习队列）。 */
const srsDue = ref(0)

async function loadSrsDue() {
  try {
    srsDue.value = (await learningApi.srsStats()).due
  } catch {
    srsDue.value = 0
  }
}

const status = ref<IndexStatus>({
  document_total: 0,
  indexed: 0,
  partial: 0,
  pending: 0,
  processing: 0,
  failed: 0,
  chunk_total: 0,
  embedded_chunks: 0,
})

/** 首次使用：知识库中还没有任何文档 */
const isFirstRun = computed(() => status.value.document_total === 0)

/** AI 是否已配置（有对话模型，且外部模式已填密钥） */
const aiConfigured = computed(() => {
  const s = settings.value
  if (!s) return false
  if (!s.chat_model) return false
  if (s.ai_mode === 'external') return s.has_external_key
  return true
})

const steps = computed(() => [
  {
    key: 'import',
    title: '导入你的文档',
    desc: '支持 Markdown、TXT、PDF、Word 和常见代码文件，导入后自动建立索引。',
    done: status.value.document_total > 0,
    to: '/upload',
    action: '去导入',
  },
  {
    key: 'model',
    title: '确认 AI 模型可用',
    desc: '配置对话模型与嵌入模型，点「检测模型服务」确认连通。',
    done: aiConfigured.value,
    to: '/settings',
    action: '去设置',
  },
  {
    key: 'chat',
    title: '开始提问',
    desc: '用自然语言提问，回答只基于你的文档，并标注每条信息的来源。',
    done: conversationCount.value > 0,
    to: '/chat',
    action: '开始问答',
  },
])

const statCards = computed(() => [
  {
    label: '文档总数',
    value: status.value.document_total,
    icon: 'Document',
    tone: '',
  },
  {
    label: '已索引文档',
    value: status.value.indexed,
    icon: 'CircleCheck',
    tone: 'is-success',
  },
  {
    label: '知识片段',
    value: status.value.chunk_total,
    icon: 'Files',
    tone: '',
  },
  {
    label: '处理失败',
    value: status.value.failed,
    icon: 'WarningFilled',
    tone: status.value.failed > 0 ? 'is-danger' : '',
  },
])

/** 向量化覆盖率 */
const embedRatio = computed(() => {
  const total = status.value.chunk_total
  if (!total) return 0
  return Math.round((status.value.embedded_chunks / total) * 100)
})

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function loadStatus() {
  status.value = await settingsApi.indexStatus()
}

async function loadRecent() {
  loading.value = true
  try {
    const data = await documentsApi.list({ page: 1, page_size: 8 })
    recent.value = data.items
  } finally {
    loading.value = false
  }
}

async function loadSettings() {
  try {
    settings.value = await settingsApi.get()
  } catch {
    /* 忽略 */
  }
}

async function loadConversations() {
  try {
    const list = await chatApi.list()
    conversationCount.value = list.length
  } catch {
    /* 忽略 */
  }
}

async function refreshAll() {
  await Promise.all([
    loadStatus(),
    loadRecent(),
    loadSettings(),
    loadConversations(),
    loadWorkbench(),
    loadSrsDue(),
  ])
}

onMounted(refreshAll)
</script>

<style scoped>
/* ================= 知识库概览（PKM） ================= */
.pkm {
  margin-bottom: 18px;
}

.pkm-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.pkm-daily {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  padding: 12px 16px;
}

.pkm-daily-label {
  font-size: 11.5px;
  color: var(--kh-text-mute);
}

.pkm-daily-title {
  font-size: 16px;
  font-weight: 600;
  margin-top: 2px;
}

.pkm-quick {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pkm-alert {
  margin-top: 14px;
}

.pkm-alert-body {
  font-size: 12.5px;
  line-height: 1.7;
}

.pkm-alert-body code {
  padding: 1px 4px;
  border-radius: 4px;
  background: var(--kh-bg);
  font-size: 11.5px;
}

.pkm-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.pkm-stat {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  border: 1px solid var(--kh-border);
  background: var(--kh-panel);
  border-radius: var(--kh-radius);
  padding: 12px 14px;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.pkm-stat:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.pkm-stat-num {
  font-size: 20px;
  font-weight: 600;
  color: var(--kh-text);
}

.pkm-stat-label {
  font-size: 12px;
  color: var(--kh-text-sub);
}

.pkm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}

.pkm-card {
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  padding: 12px 14px;
}

.pkm-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: 8px;
}

.pkm-card-hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--kh-text-mute);
}

.pkm-empty {
  font-size: 12.5px;
  color: var(--kh-text-mute);
  padding: 10px 0;
}

.pkm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: transparent;
  border-radius: 7px;
  padding: 7px 8px;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: background 0.15s ease;
}

.pkm-item:hover {
  background: var(--kh-bg);
}

.pkm-item-icon {
  color: var(--kh-text-mute);
  font-size: 14px;
  flex-shrink: 0;
}

.pkm-item-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--kh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pkm-item-lock {
  font-size: 10.5px;
  color: var(--kh-text-mute);
  border: 1px solid var(--kh-border);
  border-radius: 4px;
  padding: 0 4px;
  flex-shrink: 0;
}

.pkm-item-time {
  font-size: 11px;
  color: var(--kh-text-mute);
  flex-shrink: 0;
}

/* ================= 新手引导 ================= */
.hero {
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 20px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius-lg);
  padding: 26px 28px;
  box-shadow: var(--kh-shadow-sm);
  position: relative;
  overflow: hidden;
}

.hero::after {
  content: '';
  position: absolute;
  right: -80px;
  top: -80px;
  width: 260px;
  height: 260px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--kh-primary-soft) 0%, transparent 68%);
  pointer-events: none;
}

.hero-badge {
  display: inline-block;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--kh-primary);
  background: var(--kh-primary-soft);
  border-radius: 20px;
  padding: 3px 11px;
  margin-bottom: 12px;
}

.hero-title {
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -0.01em;
  margin: 0 0 9px;
}

.hero-desc {
  color: var(--kh-text-sub);
  font-size: 13.5px;
  line-height: 1.75;
  margin: 0 0 22px;
  max-width: 560px;
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 12px 14px;
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  background: var(--kh-panel);
  transition: border-color 0.16s ease, background 0.16s ease;
}

.step:hover {
  border-color: var(--kh-primary-border);
}

.step.done {
  background: var(--kh-success-soft);
  border-color: transparent;
}

.step-index {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12.5px;
  font-weight: 600;
  background: var(--kh-primary-soft);
  color: var(--kh-primary);
  flex-shrink: 0;
}

.step.done .step-index {
  background: var(--kh-success);
  color: #fff;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-title {
  font-size: 13.5px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-done-tag {
  font-size: 11px;
  font-weight: 500;
  color: var(--kh-success);
  background: rgba(47, 158, 110, 0.12);
  border-radius: 4px;
  padding: 1px 6px;
}

.step-desc {
  color: var(--kh-text-sub);
  font-size: 12.5px;
  margin-top: 2px;
  line-height: 1.55;
}

.step-btn {
  flex-shrink: 0;
}

/* ---- 右侧能力清单 ---- */
.hero-side {
  background: var(--kh-bg);
  border-radius: var(--kh-radius);
  padding: 18px 20px;
  align-self: start;
  position: relative;
  z-index: 1;
}

.hero-side-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--kh-text-mute);
  letter-spacing: 0.06em;
  margin-bottom: 13px;
}

.feature-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.feature-list li {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.6;
}

.feature-list .el-icon {
  color: var(--kh-primary);
  font-size: 15px;
  margin-top: 2px;
  flex-shrink: 0;
}

/* ================= 两栏 ================= */
.grid-2 {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 16px;
}

/* ---- 快捷入口 ---- */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.quick {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  text-align: left;
  padding: 14px 15px;
  border: 1px solid var(--kh-border);
  border-radius: var(--kh-radius);
  background: var(--kh-panel);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.16s ease;
}

.quick:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
  transform: translateY(-1px);
  box-shadow: var(--kh-shadow);
}

.quick .el-icon {
  font-size: 19px;
  color: var(--kh-primary);
  margin-bottom: 5px;
}

.quick-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--kh-text);
}

.quick-desc {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  line-height: 1.5;
}

/* ---- 索引状态 ---- */
.index-rows {
  display: flex;
  flex-direction: column;
}

.index-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--kh-border-light);
  font-size: 13px;
}

.index-row:last-child {
  border-bottom: none;
}

.index-label {
  color: var(--kh-text-sub);
}

.index-value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.index-value.is-success {
  color: var(--kh-success);
}
.index-value.is-warning {
  color: var(--kh-warning);
}

.index-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--kh-bg-deep);
  margin-top: 14px;
  overflow: hidden;
}

.index-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--kh-primary) 0%, #6b7ce8 100%);
  transition: width 0.4s ease;
}

.index-bar-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--kh-text-mute);
  margin-top: 7px;
}

.alert-body {
  font-size: 12.5px;
  line-height: 1.65;
}

@media (max-width: 1080px) {
  .hero {
    grid-template-columns: 1fr;
  }
  .grid-2 {
    grid-template-columns: 1fr;
  }
}
</style>
