<template>
  <div class="chat-layout">
    <!-- ============ 会话列表 ============ -->
    <aside class="conv-pane">
      <div class="conv-head">
        <el-button type="primary" class="new-btn" @click="newConversation">
          <el-icon><Plus /></el-icon>
          <span>新建会话</span>
        </el-button>
      </div>

      <div class="conv-scroll">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === currentId }"
          @click="selectConversation(c.id)"
        >
          <el-icon class="conv-icon"><ChatLineSquare /></el-icon>
          <div class="conv-body">
            <div class="conv-title">{{ c.title }}</div>
            <div class="conv-meta">{{ c.message_count }} 条消息 · {{ shortDate(c.updated_at) }}</div>
          </div>
          <el-icon class="conv-edit" @click.stop="renameConversation(c)"><EditPen /></el-icon>
          <el-icon class="conv-del" @click.stop="removeConversation(c.id)"><Delete /></el-icon>
        </div>

        <div v-if="!conversations.length" class="conv-empty">
          <el-icon><ChatDotRound /></el-icon>
          <span>还没有会话</span>
        </div>
      </div>
    </aside>

    <!-- ============ 对话区 ============ -->
    <section class="chat-main">
      <!-- 顶部工具条 -->
      <header class="chat-top">
        <div class="chat-top-left">
          <div class="chat-top-title">
            {{ currentConversation?.title || '新的对话' }}
          </div>
          <div class="chat-top-sub">回答只依据你的知识库，并标注引用来源</div>
        </div>
        <div class="chat-top-right">
          <el-tooltip
            :content="
              webAllowed
                ? '联网检索补充信息，回答会标注 🌐 并附真实链接'
                : '未在「系统设置」中开启联网搜索'
            "
            placement="bottom"
          >
            <span class="web-toggle" :class="{ 'is-off': !webAllowed }">
              <el-icon><Connection /></el-icon>
              <span>联网</span>
              <el-switch v-model="useWeb" size="small" :disabled="!webAllowed" />
            </span>
          </el-tooltip>
          <el-divider direction="vertical" />
          <span class="mode-label">回答风格</span>
          <el-radio-group v-model="mode" size="small" @change="onModeChange">
            <el-radio-button value="detail">详细</el-radio-button>
            <el-radio-button value="brief">要点</el-radio-button>
            <el-radio-button value="example">举例</el-radio-button>
          </el-radio-group>
        </div>
      </header>

      <!-- 消息流 -->
      <div ref="scrollEl" class="messages" @scroll.passive="onMessagesScroll">
        <!-- 空态：欢迎与示例问题 -->
        <div v-if="!messages.length && !streaming" class="welcome">
          <div class="welcome-icon"><el-icon><Reading /></el-icon></div>
          <h3 class="welcome-title">向你的知识库提问</h3>
          <p class="welcome-desc">
            我会先检索你导入的文档，再基于原文回答，并标出每条信息的来源。
            知识库里没有的内容，我会直接说明，不会编造。
          </p>
          <div class="welcome-tips">
            <div class="welcome-tip">
              <el-icon><Document /></el-icon>
              <span>还没导入文档？先去<router-link to="/upload">导入文档</router-link></span>
            </div>
            <div class="welcome-tip">
              <el-icon><Notebook /></el-icon>
              <span>专业术语可在<router-link to="/glossary">术语词典</router-link>中自定义</span>
            </div>
          </div>
          <div class="examples">
            <div class="examples-label">试试这样问：</div>
            <button
              v-for="q in examples"
              :key="q"
              class="example-chip"
              type="button"
              @click="input = q"
            >
              {{ q }}
            </button>
          </div>
        </div>

        <template v-for="(m, i) in messages" :key="m.id">
          <div v-if="showDivider(i)" class="date-divider">
            <span>{{ dayLabel(m.created_at) }}</span>
          </div>

          <!-- 用户消息：靠右 -->
          <div v-if="m.role === 'user'" class="msg-row is-user">
            <div class="bubble is-user">{{ m.content }}</div>
            <div class="avatar is-user"><el-icon><User /></el-icon></div>
          </div>

          <!-- AI 消息：靠左 -->
          <div v-else class="msg-row is-ai">
            <div class="avatar is-ai"><el-icon><MagicStick /></el-icon></div>
            <div class="bubble is-ai">
              <!-- 历史消息的思考过程（默认折叠，点击展开） -->
              <div v-if="m.reasoning" class="thinking-box">
                <button class="thinking-head" type="button" @click="toggleThinking(m.id)">
                  <el-icon class="thinking-icon"><Cpu /></el-icon>
                  <span>已深度思考（{{ m.reasoning.length }} 字）</span>
                  <el-icon class="thinking-arrow" :class="{ open: thinkingExpanded.has(m.id) }">
                    <ArrowDown />
                  </el-icon>
                </button>
                <div v-show="thinkingExpanded.has(m.id)" class="thinking-body">
                  {{ m.reasoning }}
                </div>
              </div>

              <!-- 来源类型标注（📄原文 / 📑归纳 / 🌐联网，见需求 14） -->
              <div v-if="m.source_type" class="source-badge">
                <el-tag size="small" effect="plain" :type="badgeType(m.source_type)">
                  {{ badgeIcon(m.source_type) }} {{ m.source_type }}
                </el-tag>
              </div>

              <MarkdownView :content="m.content" />

              <!-- 引用来源 -->
              <div v-if="m.sources && m.sources.length" class="sources">
                <button class="sources-head" type="button" @click="toggleSources(m.id)">
                  <el-icon><Link /></el-icon>
                  <span>引用来源 {{ m.sources.length }} 处</span>
                  <el-icon class="sources-arrow" :class="{ open: expanded.has(m.id) }">
                    <ArrowDown />
                  </el-icon>
                </button>
                <div v-show="expanded.has(m.id)" class="sources-body">
                  <div v-for="(s, si) in m.sources" :key="s.chunk_id" class="source-item">
                    <span class="source-index">{{ si + 1 }}</span>
                    <div class="source-main">
                      <div class="source-line">
                        <el-link type="primary" @click="openSource(s)">
                          {{ s.document_title }}
                        </el-link>
                        <span v-if="s.heading" class="muted">· {{ s.heading }}</span>
                        <span v-if="s.page_no" class="muted">· 第 {{ s.page_no }} 页</span>
                        <el-link
                          v-if="s.parent_content"
                          class="muted"
                          @click="toggleParent(s.chunk_id)"
                        >
                          {{ parentExpanded.has(s.chunk_id) ? '收起上下文' : '展开上下文' }}
                        </el-link>
                      </div>
                      <div class="source-snippet">{{ s.snippet }}</div>
                      <div
                        v-if="s.parent_content && parentExpanded.has(s.chunk_id)"
                        class="source-parent"
                      >
                        {{ s.parent_content }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 联网补充来源：真实链接，仅随本次流式响应返回（不落库） -->
              <div v-if="m.web_results && m.web_results.length" class="sources">
                <div class="sources-head is-static">
                  <el-icon><Connection /></el-icon>
                  <span>联网补充 {{ m.web_results.length }} 条</span>
                </div>
                <div class="sources-body">
                  <a
                    v-for="(w, wi) in m.web_results"
                    :key="w.url"
                    class="source-item web-item"
                    :href="w.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span class="source-index">{{ wi + 1 }}</span>
                    <div class="source-main">
                      <div class="source-line">
                        <span class="web-title">{{ w.title || w.url }}</span>
                        <span class="muted">· {{ hostOf(w.url) }}</span>
                      </div>
                      <div class="source-snippet">{{ w.snippet }}</div>
                    </div>
                  </a>
                </div>
              </div>

              <!-- 操作 -->
              <div v-if="!streaming" class="msg-actions">
                <button class="act" type="button" @click="copyMessage(m)">
                  <el-icon><CopyDocument /></el-icon><span>复制</span>
                </button>
                <button
                  v-if="isServerMessage(m.id)"
                  class="act"
                  type="button"
                  @click="regenerate(m)"
                >
                  <el-icon><RefreshRight /></el-icon><span>重新生成</span>
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- 流式输出中 -->
        <div v-if="streaming" class="msg-row is-ai">
          <div class="avatar is-ai"><el-icon><MagicStick /></el-icon></div>
          <div class="bubble is-ai">
            <div v-if="glossaryTerms.length" class="glossary-note">
              <el-icon><Notebook /></el-icon>
              <span>命中术语词典：{{ glossaryTerms.map((t) => t.term).join('、') }}</span>
            </div>

            <!-- 模型思考过程（类似 DeepSeek 的思考区，可折叠） -->
            <div v-if="thinkingText" class="thinking-box">
              <button class="thinking-head" type="button" @click="thinkingOpen = !thinkingOpen">
                <el-icon class="thinking-icon" :class="{ spinning: !streamText }">
                  <Loading />
                </el-icon>
                <span>
                  {{
                    streamText
                      ? `已深度思考（${thinkingText.length} 字）`
                      : `正在思考…（${thinkingText.length} 字）`
                  }}
                </span>
                <el-icon class="thinking-arrow" :class="{ open: thinkingOpen }">
                  <ArrowDown />
                </el-icon>
              </button>
              <div v-show="thinkingOpen" class="thinking-body">{{ thinkingText }}</div>
            </div>

            <div v-if="!streamText" class="typing">
              <span class="typing-dot" />
              <span class="typing-dot" />
              <span class="typing-dot" />
              <span class="typing-text">{{ thinkingText ? '正在组织回答…' : '正在检索知识库' }}</span>
            </div>

            <template v-else>
              <MarkdownView :content="streamText" />
              <span class="caret" />
            </template>
          </div>
        </div>
      </div>

      <!-- 用户上滑查看历史时，提供一键回到底部 -->
      <button v-if="!stickToBottom" class="to-bottom" type="button" @click="jumpToBottom">
        <el-icon><ArrowDown /></el-icon>
        <span>{{ streaming ? '回到最新（生成中）' : '回到最新' }}</span>
      </button>

      <!-- 输入区 -->
      <footer class="composer">
        <div class="composer-box" :class="{ 'is-busy': streaming }">
          <textarea
            v-model="input"
            class="composer-input"
            rows="1"
            placeholder="输入你的问题…（Enter 发送，Shift + Enter 换行）"
            @keydown.enter.exact.prevent="send"
            @input="autoGrow"
            ref="inputEl"
          />
          <div class="composer-side">
            <el-button v-if="streaming" size="small" @click="abort">中止</el-button>
            <el-button
              type="primary"
              class="send-btn"
              :loading="streaming"
              :disabled="!input.trim()"
              @click="send"
            >
              <el-icon v-if="!streaming"><Promotion /></el-icon>
              <span>发送</span>
            </el-button>
          </div>
        </div>
        <div class="composer-foot">
          <span>回答基于知识库内容，可能不完整，请以引用原文为准</span>
          <span class="spacer" />
          <span v-if="currentConversation" class="mono">{{ currentConversation.message_count }} 条消息</span>
        </div>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { askStream, chatApi, regenerateStream, settingsApi } from '@/api'
import type {
  AnswerMode,
  ConversationOut,
  MessageOut,
  SearchHit,
  WebResult,
} from '@/api/types'
import MarkdownView from '@/components/MarkdownView.vue'

const router = useRouter()
const conversations = ref<ConversationOut[]>([])
const currentId = ref<string | null>(null)
const messages = ref<MessageOut[]>([])
const mode = ref<AnswerMode>('detail')
const input = ref('')
const streaming = ref(false)
const streamText = ref('')
// 模型思考过程：流式期间累积展示，完成后写入消息以便回看。
// 默认折叠——推理模型（qwen3.7 / deepseek-v4 等）的思考过程往往很长且为英文，
// 且不受提示词控制，默认展开会淹没正文。
const thinkingText = ref('')
const thinkingOpen = ref(false)
const glossaryTerms = ref<{ term: string; definition: string; category?: string | null }[]>([])
// 联网补充：webAllowed 来自系统设置总开关；useWeb 为本次会话的临时开关
const webAllowed = ref(false)
const useWeb = ref(false)
const expanded = reactive(new Set<string>())
// 历史消息思考区的展开状态
const thinkingExpanded = reactive(new Set<string>())
// 引用条目的「展开上下文」状态（父子检索：显示父块完整内容）
const parentExpanded = reactive(new Set<string>())
const scrollEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)
// 是否吸附在底部：用户手动上滑后置 false，避免生成过程把用户拽回底部
const stickToBottom = ref(true)
let aborter: AbortController | null = null
// 会话切换的请求序号：快速点击多个会话时，只允许最后一次请求写入 messages，
// 否则先发出的慢响应会覆盖后选中的会话内容。
let convSeq = 0

const examples = [
  '总结一下我最近导入的文档讲了什么',
  '这个项目里 XX 是怎么实现的？',
  '文档里提到的注意事项有哪些？',
]

const currentConversation = computed(
  () => conversations.value.find((c) => c.id === currentId.value) ?? null,
)

/** 来源类型徽章图标（与后端 rag/source_type.py 的标签保持一致）。 */
function badgeIcon(type: string): string {
  if (type.includes('联网')) return '🌐'
  if (type.includes('归纳')) return '📑'
  if (type.includes('词典')) return '📖'
  return '📄'
}

function badgeType(type: string): 'success' | 'primary' | 'warning' | 'info' {
  if (type.includes('联网')) return 'warning'
  if (type.includes('归纳')) return 'primary'
  if (type.includes('词典')) return 'info'
  return 'success'
}

/** 从 URL 提取主机名，用于联网结果展示。 */
function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** 打开引用来源所在文档，并定位到对应片段（需求 13.3 / 17.2）。 */
function openSource(s: SearchHit) {
  router.push({
    path: `/documents/${s.document_id}`,
    query: { chunk: s.chunk_id },
  })
}

/** 重命名会话（需求 16.1）。 */
async function renameConversation(c: ConversationOut) {
  let value: string
  try {
    const res = await ElMessageBox.prompt('输入新的会话标题', '重命名会话', {
      inputValue: c.title,
      inputPattern: /\S/,
      inputErrorMessage: '标题不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    value = (res.value || '').trim()
  } catch {
    return // 用户取消
  }
  if (!value || value === c.title) return
  await chatApi.update(c.id, { title: value })
  await loadConversations()
  ElMessage.success('已重命名')
}

function toggleSources(id: string) {
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
}

/** 展开 / 折叠某条历史消息的思考过程。 */
function toggleThinking(id: string) {
  if (thinkingExpanded.has(id)) thinkingExpanded.delete(id)
  else thinkingExpanded.add(id)
}

/** 展开 / 折叠引用的父块上下文（父子检索）。 */
function toggleParent(id: string) {
  if (parentExpanded.has(id)) parentExpanded.delete(id)
  else parentExpanded.add(id)
}

function dayLabel(v: string): string {
  const d = new Date(v)
  const today = new Date()
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const day = 86400000
  const t = d.getTime()
  if (t >= startOfToday) return '今天'
  if (t >= startOfToday - day) return '昨天'
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
}

function showDivider(i: number): boolean {
  if (i === 0) return true
  return dayLabel(messages.value[i].created_at) !== dayLabel(messages.value[i - 1].created_at)
}

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

const shortDate = (v: string) => {
  const d = new Date(v)
  const today = new Date()
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  if (d.getTime() >= startOfToday) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

async function loadConversations() {
  conversations.value = await chatApi.list()
}

async function newConversation() {
  const conv = await chatApi.create({ title: '新会话', mode: mode.value })
  await loadConversations()
  await selectConversation(conv.id)
}

async function selectConversation(id: string) {
  const mySeq = ++convSeq
  currentId.value = id
  const detail = await chatApi.get(id)
  // 期间又切到了别的会话 → 丢弃这次结果，避免「地址栏/高亮是 B，内容却是 A」
  if (mySeq !== convSeq) return
  messages.value = detail.messages
  mode.value = detail.mode
  scrollToBottom()
}

async function removeConversation(id: string) {
  await ElMessageBox.confirm('删除该会话及其全部消息？', '删除确认', { type: 'warning' })
  await chatApi.remove(id)
  if (currentId.value === id) {
    currentId.value = null
    messages.value = []
  }
  loadConversations()
}

async function onModeChange() {
  if (currentId.value) await chatApi.update(currentId.value, { mode: mode.value })
}

/** 距底部多少像素内仍视为「在底部」。 */
const BOTTOM_THRESHOLD = 60

function onMessagesScroll() {
  const el = scrollEl.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  stickToBottom.value = distance <= BOTTOM_THRESHOLD
}

/**
 * 滚动到底部。
 * force=true：用户主动发问或点击「回到最新」时强制滚动；
 * 默认：仅当用户仍在底部时才跟随，否则保持其当前阅读位置
 * （否则流式生成时每来一个 token 都会把用户拽回底部，无法查看历史消息）。
 */
function scrollToBottom(force = false) {
  if (!force && !stickToBottom.value) return
  nextTick(() => {
    const el = scrollEl.value
    if (!el) return
    el.scrollTop = el.scrollHeight
    stickToBottom.value = true
  })
}

function jumpToBottom() {
  scrollToBottom(true)
}

async function send() {
  const question = input.value.trim()
  if (!question || streaming.value) return

  if (!currentId.value) {
    const conv = await chatApi.create({ title: question.slice(0, 30), mode: mode.value })
    currentId.value = conv.id
    await loadConversations()
  }

  messages.value.push({
    id: `local-${Date.now()}`,
    role: 'user',
    content: question,
    created_at: new Date().toISOString(),
  })
  input.value = ''
  nextTick(autoGrow)
  streaming.value = true
  streamText.value = ''
  thinkingText.value = ''
  thinkingOpen.value = false
  glossaryTerms.value = []
  let sources: SearchHit[] = []
  let webResults: WebResult[] = []
  let sourceType: string | null = null
  scrollToBottom(true) // 用户主动发问：强制滚到底部

  aborter = new AbortController()

  const finalize = async (text: string, aborted: boolean, serverId?: string) => {
    streaming.value = false
    streamText.value = ''
    aborter = null
    const id = serverId ?? `local-a-${Date.now()}`
    messages.value.push({
      id,
      role: 'assistant',
      content: aborted ? `${text}\n\n> （已中止生成）` : text,
      sources,
      source_type: sourceType,
      web_results: webResults,
      reasoning: thinkingText.value || null,
      created_at: new Date().toISOString(),
    })
    if (sources.length) expanded.add(id)
    thinkingText.value = ''
    await loadConversations()
    scrollToBottom()
  }

  await askStream(
    currentId.value,
    { question, mode: mode.value, use_web: useWeb.value },
    {
      onSources: (s) => {
        sources = s as SearchHit[]
      },
      onGlossary: (terms) => {
        glossaryTerms.value = terms
      },
      onWeb: (data) => {
        webResults = data.results
        // 启用了联网却没拿到结果：明确告知，不静默
        if (!data.ok) ElMessage.warning(data.message)
      },
      onThinking: (data) => {
        thinkingText.value += data.text
        scrollToBottom()
      },
      onDelta: (t) => {
        // 正文开始输出：自动折叠思考区（与 DeepSeek 行为一致）
        if (thinkingOpen.value && thinkingText.value) thinkingOpen.value = false
        streamText.value += t
        scrollToBottom()
      },
      onDone: async (data) => {
        sourceType = data.source_type ?? null
        if (data.web_results) webResults = data.web_results
        await finalize(streamText.value, false, data.message_id)
      },
      onAbort: async () => {
        await finalize(streamText.value, true)
      },
      onError: (msg) => {
        ElMessage.error(msg)
        // 已经生成了一部分内容：保留它并标记为中断，不要静默丢弃用户的等待
        if (streamText.value.trim()) {
          void finalize(streamText.value, true)
        } else {
          streaming.value = false
          aborter = null
        }
      },
    },
    aborter.signal,
  )
}

function abort() {
  aborter?.abort()
}

/** 是否服务端消息（带真实 UUID，可执行重新生成）。 */
function isServerMessage(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
}

async function copyMessage(m: MessageOut) {
  try {
    await navigator.clipboard.writeText(m.content)
    ElMessage.success('已复制回答')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

/** 重新生成某条回答：后端删除原回答后按同一提问重新检索与生成。 */
async function regenerate(m: MessageOut) {
  if (streaming.value) return
  const idx = messages.value.findIndex((x) => x.id === m.id)
  if (idx < 0) return

  streaming.value = true
  streamText.value = ''
  thinkingText.value = ''
  thinkingOpen.value = false
  glossaryTerms.value = []
  let sources: SearchHit[] = []
  let webResults: WebResult[] = []
  let sourceType: string | null = null
  messages.value.splice(idx, 1)
  scrollToBottom(true) // 用户主动重新生成：强制滚到底部

  aborter = new AbortController()

  const finish = async (text: string, aborted: boolean, serverId?: string) => {
    streaming.value = false
    streamText.value = ''
    aborter = null
    const id = serverId ?? `local-a-${Date.now()}`
    messages.value.push({
      id,
      role: 'assistant',
      content: aborted ? `${text}\n\n> （已中止生成）` : text,
      sources,
      source_type: sourceType,
      web_results: webResults,
      reasoning: thinkingText.value || null,
      created_at: new Date().toISOString(),
    })
    if (sources.length) expanded.add(id)
    thinkingText.value = ''
    await loadConversations()
    scrollToBottom()
  }

  await regenerateStream(
    m.id,
    {
      onSources: (s) => {
        sources = s as SearchHit[]
      },
      onGlossary: (terms) => {
        glossaryTerms.value = terms
      },
      onWeb: (data) => {
        webResults = data.results
        if (!data.ok) ElMessage.warning(data.message)
      },
      onThinking: (data) => {
        thinkingText.value += data.text
        scrollToBottom()
      },
      onDelta: (t) => {
        // 正文开始输出：自动折叠思考区（与 DeepSeek 行为一致）
        if (thinkingOpen.value && thinkingText.value) thinkingOpen.value = false
        streamText.value += t
        scrollToBottom()
      },
      onDone: async (data) => {
        sourceType = data.source_type ?? null
        if (data.web_results) webResults = data.web_results
        await finish(streamText.value, false, data.message_id)
      },
      onAbort: async () => {
        await finish(streamText.value, true)
      },
      onError: (msg) => {
        streaming.value = false
        streamText.value = ''
        aborter = null
        ElMessage.error(msg)
        if (currentId.value) selectConversation(currentId.value)
      },
    },
    aborter.signal,
    useWeb.value,
  )
}

/** 读取系统设置中的联网总开关；未开启时前端不允许启用联网（需求 14.5）。 */
async function loadWebSetting() {
  try {
    const s = await settingsApi.get()
    webAllowed.value = s.web_search_enabled
    useWeb.value = s.web_search_enabled
  } catch {
    webAllowed.value = false
    useWeb.value = false
  }
}

onMounted(async () => {
  await loadWebSetting()
  await loadConversations()
  if (conversations.value.length) await selectConversation(conversations.value[0].id)
})

onBeforeUnmount(() => {
  // 生成中离开页面：中止在途的 SSE 请求，避免响应回来后写入已卸载组件的状态
  aborter?.abort()
  aborter = null
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ================= 会话列表 ================= */
.conv-pane {
  width: 244px;
  flex-shrink: 0;
  border-right: 1px solid var(--kh-border);
  background: var(--kh-panel);
  display: flex;
  flex-direction: column;
}

.conv-head {
  padding: 14px 14px 10px;
}

.new-btn {
  width: 100%;
}

.conv-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px 14px;
}

.conv-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 11px;
  border-radius: 9px;
  cursor: pointer;
  margin-bottom: 3px;
  transition: background 0.15s ease;
}

.conv-item:hover {
  background: var(--kh-bg);
}

.conv-item.active {
  background: var(--kh-primary-soft);
}

.conv-icon {
  font-size: 15px;
  color: var(--kh-text-mute);
  margin-top: 2px;
  flex-shrink: 0;
}

.conv-item.active .conv-icon {
  color: var(--kh-primary);
}

.conv-body {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 14px;
}

.conv-item.active .conv-title {
  font-weight: 600;
  color: var(--kh-primary);
}

.conv-meta {
  color: var(--kh-text-mute);
  font-size: 11.5px;
  margin-top: 2px;
}

.conv-edit,
.conv-del {
  position: absolute;
  top: 10px;
  font-size: 14px;
  color: var(--kh-text-mute);
  opacity: 0;
  transition: opacity 0.15s ease;
}

.conv-edit {
  right: 28px;
}

.conv-del {
  right: 9px;
}

.conv-item:hover .conv-edit,
.conv-item:hover .conv-del {
  opacity: 1;
}

.conv-edit:hover {
  color: var(--kh-primary);
}

.conv-del:hover {
  color: var(--kh-danger);
}

.conv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--kh-text-mute);
  font-size: 12.5px;
}

.conv-empty .el-icon {
  font-size: 24px;
}

/* ================= 对话主区 ================= */
.chat-main {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--kh-bg);
}

.chat-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 22px;
  background: var(--kh-panel);
  border-bottom: 1px solid var(--kh-border);
  flex-shrink: 0;
}

.chat-top-title {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

.chat-top-sub {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  margin-top: 1px;
}

.chat-top-right {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-shrink: 0;
}

.mode-label {
  font-size: 12.5px;
  color: var(--kh-text-sub);
}

/* 联网开关 */
.web-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--kh-text-sub);
}

.web-toggle.is-off {
  opacity: 0.55;
}

/* ================= 消息流 ================= */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 22px 22px 8px;
}

/* 用户上滑查看历史时的一键回底按钮 */
.to-bottom {
  position: absolute;
  right: 28px;
  bottom: 138px;
  z-index: 5;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 13px;
  border-radius: 16px;
  border: 1px solid var(--kh-primary-border);
  background: var(--kh-panel);
  color: var(--kh-primary);
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
  box-shadow: var(--kh-shadow-sm);
  transition: background 0.15s ease, transform 0.15s ease;
}

.to-bottom:hover {
  background: var(--kh-primary-soft);
  transform: translateY(-1px);
}

.date-divider {
  display: flex;
  justify-content: center;
  margin: 16px 0 18px;
}

.date-divider span {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  background: rgba(31, 35, 40, 0.05);
  padding: 2px 10px;
  border-radius: 10px;
}

.msg-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 16px;
}

.msg-row.is-user {
  justify-content: flex-end;
}

.msg-row.is-ai {
  justify-content: flex-start;
}

/* ---- 头像 ---- */
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 16px;
  flex-shrink: 0;
  margin-top: 2px;
}

.avatar.is-ai {
  background: linear-gradient(135deg, var(--kh-primary) 0%, #6b7ce8 100%);
  color: #fff;
  box-shadow: 0 2px 8px rgba(74, 95, 214, 0.25);
}

.avatar.is-user {
  background: var(--kh-bg-deep);
  color: var(--kh-text-sub);
  border: 1px solid var(--kh-border);
}

/* ---- 气泡 ---- */
.bubble {
  position: relative;
  max-width: min(680px, 76%);
  padding: 11px 15px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.bubble::before {
  content: '';
  position: absolute;
  top: 13px;
  width: 9px;
  height: 9px;
  transform: rotate(45deg);
}

.bubble.is-user {
  background: var(--kh-primary);
  color: #fff;
  white-space: pre-wrap;
  border-top-right-radius: 4px;
}

.bubble.is-user::before {
  right: -4px;
  background: var(--kh-primary);
}

.bubble.is-ai {
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  color: var(--kh-text);
  border-top-left-radius: 4px;
  box-shadow: var(--kh-shadow-sm);
}

.bubble.is-ai::before {
  left: -4.5px;
  background: var(--kh-panel);
  border-left: 1px solid var(--kh-border);
  border-bottom: 1px solid var(--kh-border);
}

/* ---- 模型思考过程（类似 DeepSeek 的思考区） ---- */
.thinking-box {
  margin-bottom: 10px;
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  background: var(--kh-bg);
  overflow: hidden;
}

.thinking-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--kh-text-sub);
  text-align: left;
}

.thinking-head:hover {
  background: var(--kh-bg-deep);
}

.thinking-icon {
  font-size: 13px;
  color: var(--kh-text-mute);
}

.thinking-icon.spinning {
  animation: kh-spin 1s linear infinite;
}

@keyframes kh-spin {
  to {
    transform: rotate(360deg);
  }
}

.thinking-arrow {
  margin-left: auto;
  font-size: 12px;
  transition: transform 0.2s ease;
}

.thinking-arrow.open {
  transform: rotate(180deg);
}

.thinking-body {
  padding: 6px 12px 10px;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--kh-text-sub);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow-y: auto;
  border-top: 1px dashed var(--kh-border-light);
}

/* ---- 来源类型徽章 ---- */
.source-badge {
  margin-bottom: 8px;
}

/* ---- 术语命中 ---- */
.glossary-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--kh-success);
  background: var(--kh-success-soft);
  border-radius: 6px;
  padding: 5px 9px;
  margin-bottom: 10px;
}

/* ---- 打字动画 ---- */
.typing {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 0;
}

.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--kh-primary);
  opacity: 0.4;
  animation: kh-typing 1.3s infinite ease-in-out;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.18s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.36s;
}

.typing-text {
  margin-left: 8px;
  font-size: 12.5px;
  color: var(--kh-text-sub);
}

@keyframes kh-typing {
  0%,
  70%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  35% {
    opacity: 1;
    transform: translateY(-3px);
  }
}

.caret {
  display: inline-block;
  width: 2px;
  height: 15px;
  background: var(--kh-primary);
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: kh-caret 1s step-end infinite;
}

@keyframes kh-caret {
  50% {
    opacity: 0;
  }
}

/* ---- 引用来源 ---- */
.sources {
  margin-top: 12px;
  border-top: 1px dashed var(--kh-border);
  padding-top: 10px;
}

.sources-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 2px 0;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--kh-primary);
  font-weight: 500;
}

.sources-head:hover {
  opacity: 0.8;
}

/* 联网来源标题不可折叠，仅为说明行 */
.sources-head.is-static {
  cursor: default;
}

.sources-arrow {
  margin-left: auto;
  font-size: 12px;
  transition: transform 0.2s ease;
}

.sources-arrow.open {
  transform: rotate(180deg);
}

.sources-body {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-item {
  display: flex;
  gap: 9px;
  background: var(--kh-bg);
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  padding: 9px 11px;
}

.source-index {
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: var(--kh-primary-soft);
  color: var(--kh-primary);
  font-size: 11px;
  font-weight: 600;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.source-main {
  min-width: 0;
  flex: 1;
}

.source-line {
  font-size: 12.5px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: baseline;
}

.source-snippet {
  color: var(--kh-text-sub);
  font-size: 12px;
  line-height: 1.62;
  margin-top: 3px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 父子检索：展开后的父块完整内容 */
.source-parent {
  margin-top: 6px;
  padding: 8px 10px;
  border-left: 2px solid var(--kh-primary-border);
  background: var(--kh-bg-deep);
  border-radius: 4px;
  color: var(--kh-text-sub);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
}

/* 联网结果条目：整条可点击，指向真实外链 */
.web-item {
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.web-item:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.web-title {
  font-weight: 500;
  color: var(--kh-text);
  word-break: break-word;
}

/* ---- 操作 ---- */
.msg-actions {
  display: flex;
  gap: 4px;
  margin-top: 10px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.bubble:hover .msg-actions {
  opacity: 1;
}

.act {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  color: var(--kh-text-sub);
  padding: 3px 7px;
  border-radius: 5px;
  transition: background 0.15s ease, color 0.15s ease;
}

.act:hover {
  background: var(--kh-primary-soft);
  color: var(--kh-primary);
}

/* ================= 欢迎空态 ================= */
.welcome {
  max-width: 620px;
  margin: 6vh auto 0;
  text-align: center;
  padding: 0 20px;
}

.welcome-icon {
  width: 62px;
  height: 62px;
  border-radius: 18px;
  margin: 0 auto 18px;
  display: grid;
  place-items: center;
  font-size: 27px;
  color: #fff;
  background: linear-gradient(135deg, var(--kh-primary) 0%, #6b7ce8 100%);
  box-shadow: 0 8px 22px rgba(74, 95, 214, 0.25);
}

.welcome-title {
  font-size: 19px;
  font-weight: 650;
  margin: 0 0 10px;
}

.welcome-desc {
  color: var(--kh-text-sub);
  font-size: 13.5px;
  line-height: 1.75;
  margin: 0 0 22px;
}

.welcome-tips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 24px;
}

.welcome-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  font-size: 12.5px;
  color: var(--kh-text-sub);
}

.welcome-tip .el-icon {
  color: var(--kh-primary);
}

.welcome-tip a {
  color: var(--kh-primary);
  text-decoration: none;
  font-weight: 500;
}

.welcome-tip a:hover {
  text-decoration: underline;
}

.examples {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.examples-label {
  font-size: 12px;
  color: var(--kh-text-mute);
}

.example-chip {
  border: 1px solid var(--kh-border);
  background: var(--kh-panel);
  border-radius: 20px;
  padding: 7px 15px;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--kh-text-sub);
  cursor: pointer;
  transition: all 0.15s ease;
}

.example-chip:hover {
  border-color: var(--kh-primary-border);
  color: var(--kh-primary);
  background: var(--kh-primary-soft);
}

/* ================= 输入区 ================= */
.composer {
  flex-shrink: 0;
  padding: 12px 22px 16px;
  background: var(--kh-panel);
  border-top: 1px solid var(--kh-border);
}

.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  border: 1px solid var(--kh-border);
  border-radius: 12px;
  padding: 9px 10px 9px 14px;
  background: var(--kh-panel);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer-box:focus-within {
  border-color: var(--kh-primary);
  box-shadow: 0 0 0 3px var(--kh-primary-soft);
}

.composer-box.is-busy {
  opacity: 0.75;
}

.composer-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  color: var(--kh-text);
  background: transparent;
  max-height: 160px;
  padding: 5px 0;
}

.composer-input::placeholder {
  color: var(--kh-text-mute);
}

.composer-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.send-btn {
  padding: 8px 18px;
}

.composer-foot {
  display: flex;
  align-items: center;
  font-size: 11.5px;
  color: var(--kh-text-mute);
  margin-top: 8px;
  padding: 0 2px;
}

@media (max-width: 900px) {
  .conv-pane {
    display: none;
  }
  .bubble {
    max-width: 86%;
  }
}
</style>
