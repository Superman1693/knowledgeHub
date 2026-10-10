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
          <span class="mode-label">回答风格</span>
          <el-radio-group v-model="mode" size="small" @change="onModeChange">
            <el-radio-button value="detail">详细</el-radio-button>
            <el-radio-button value="brief">要点</el-radio-button>
            <el-radio-button value="example">举例</el-radio-button>
          </el-radio-group>
        </div>
      </header>

      <!-- 消息流 -->
      <div ref="scrollEl" class="messages">
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
                  <div
                    v-for="(s, si) in m.sources"
                    :key="s.chunk_id"
                    class="source-item"
                  >
                    <span class="source-index">{{ si + 1 }}</span>
                    <div class="source-main">
                      <div class="source-line">
                        <el-link type="primary" @click="$router.push(`/documents/${s.document_id}`)">
                          {{ s.document_title }}
                        </el-link>
                        <span v-if="s.heading" class="muted">· {{ s.heading }}</span>
                        <span v-if="s.page_no" class="muted">· 第 {{ s.page_no }} 页</span>
                      </div>
                      <div class="source-snippet">{{ s.snippet }}</div>
                    </div>
                  </div>
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

            <div v-if="!streamText" class="typing">
              <span class="typing-dot" />
              <span class="typing-dot" />
              <span class="typing-dot" />
              <span class="typing-text">
                {{
                  thinkingChars > 0
                    ? `模型思考中（已思考 ${thinkingChars} 字）`
                    : '正在检索知识库'
                }}
              </span>
            </div>

            <template v-else>
              <MarkdownView :content="streamText" />
              <span class="caret" />
            </template>
          </div>
        </div>
      </div>

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
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { askStream, chatApi, regenerateStream } from '@/api'
import type { AnswerMode, ConversationOut, MessageOut, SearchHit } from '@/api/types'
import MarkdownView from '@/components/MarkdownView.vue'

const conversations = ref<ConversationOut[]>([])
const currentId = ref<string | null>(null)
const messages = ref<MessageOut[]>([])
const mode = ref<AnswerMode>('detail')
const input = ref('')
const streaming = ref(false)
const streamText = ref('')
const thinkingChars = ref(0)
const glossaryTerms = ref<{ term: string; definition: string; category?: string | null }[]>([])
const expanded = reactive(new Set<string>())
const scrollEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)
let aborter: AbortController | null = null

const examples = [
  '总结一下我最近导入的文档讲了什么',
  '这个项目里 XX 是怎么实现的？',
  '文档里提到的注意事项有哪些？',
]

const currentConversation = computed(
  () => conversations.value.find((c) => c.id === currentId.value) ?? null,
)

function toggleSources(id: string) {
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
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
  currentId.value = id
  const detail = await chatApi.get(id)
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

function scrollToBottom() {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
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
  thinkingChars.value = 0
  glossaryTerms.value = []
  let sources: SearchHit[] = []
  scrollToBottom()

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
      created_at: new Date().toISOString(),
    })
    if (sources.length) expanded.add(id)
    await loadConversations()
    scrollToBottom()
  }

  await askStream(
    currentId.value,
    { question, mode: mode.value },
    {
      onSources: (s) => {
        sources = s as SearchHit[]
      },
      onGlossary: (terms) => {
        glossaryTerms.value = terms
      },
      onThinking: (chars) => {
        thinkingChars.value = chars
        scrollToBottom()
      },
      onDelta: (t) => {
        streamText.value += t
        scrollToBottom()
      },
      onDone: async (data) => {
        await finalize(streamText.value, false, data.message_id)
      },
      onAbort: async () => {
        await finalize(streamText.value, true)
      },
      onError: (msg) => {
        streaming.value = false
        streamText.value = ''
        aborter = null
        ElMessage.error(msg)
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
  thinkingChars.value = 0
  glossaryTerms.value = []
  let sources: SearchHit[] = []
  messages.value.splice(idx, 1)
  scrollToBottom()

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
      created_at: new Date().toISOString(),
    })
    if (sources.length) expanded.add(id)
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
      onThinking: (chars) => {
        thinkingChars.value = chars
        scrollToBottom()
      },
      onDelta: (t) => {
        streamText.value += t
        scrollToBottom()
      },
      onDone: async (data) => {
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
  )
}

onMounted(async () => {
  await loadConversations()
  if (conversations.value.length) await selectConversation(conversations.value[0].id)
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

.conv-del {
  position: absolute;
  right: 9px;
  top: 10px;
  font-size: 14px;
  color: var(--kh-text-mute);
  opacity: 0;
  transition: opacity 0.15s ease;
}

.conv-item:hover .conv-del {
  opacity: 1;
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

/* ================= 消息流 ================= */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 22px 22px 8px;
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
