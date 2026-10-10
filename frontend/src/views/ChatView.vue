<template>
  <div class="chat-wrap">
    <!-- 会话列表 -->
    <aside class="conv-list">
      <div class="conv-head">
        <el-button type="primary" size="small" @click="newConversation">
          <el-icon><Plus /></el-icon> 新建会话
        </el-button>
      </div>
      <div class="conv-items">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === currentId }"
          @click="selectConversation(c.id)"
        >
          <div class="conv-title">{{ c.title }}</div>
          <div class="conv-meta">{{ c.message_count }} 条 · {{ shortDate(c.updated_at) }}</div>
          <el-icon class="conv-del" @click.stop="removeConversation(c.id)"><Delete /></el-icon>
        </div>
        <div v-if="!conversations.length" class="empty-hint">还没有会话</div>
      </div>
    </aside>

    <!-- 对话区 -->
    <section class="chat-main">
      <div class="chat-toolbar">
        <span class="mode-label">回答模式：</span>
        <el-radio-group v-model="mode" size="small" @change="onModeChange">
          <el-radio-button value="detail">详细解释</el-radio-button>
          <el-radio-button value="brief">极简要点</el-radio-button>
          <el-radio-button value="example">通俗举例</el-radio-button>
        </el-radio-group>
        <span class="spacer" />
        <el-tag size="small" effect="plain" type="info">回答会标注知识库来源</el-tag>
      </div>

      <div ref="scrollEl" class="messages">
        <div v-if="!messages.length" class="empty-hint">
          向你的知识库提问吧。回答只基于已导入并完成索引的文档。
        </div>

        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <div class="msg-role">{{ m.role === 'user' ? '我' : 'AI' }}</div>
          <div class="msg-body">
            <MarkdownView v-if="m.role === 'assistant'" :content="m.content" />
            <div v-else class="user-text">{{ m.content }}</div>

            <div v-if="m.role === 'assistant' && !streaming" class="msg-actions">
              <el-button link size="small" @click="copyMessage(m)">复制</el-button>
              <el-button
                v-if="isServerMessage(m.id)"
                link
                size="small"
                @click="regenerate(m)"
              >
                重新生成
              </el-button>
            </div>

            <div v-if="m.sources && m.sources.length" class="sources">
              <div class="sources-title">引用来源</div>
              <div v-for="(s, i) in m.sources" :key="s.chunk_id" class="source">
                <span class="src-index">[{{ i + 1 }}]</span>
                <el-link type="primary" @click="$router.push(`/documents/${s.document_id}`)">
                  {{ s.document_title }}
                </el-link>
                <span v-if="s.heading" class="muted">· {{ s.heading }}</span>
                <span v-if="s.page_no" class="muted">· 第 {{ s.page_no }} 页</span>
                <div class="src-snippet">{{ s.snippet }}</div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="streaming" class="msg assistant">
          <div class="msg-role">AI</div>
          <div class="msg-body">
            <div v-if="glossaryTerms.length" class="glossary-hint">
              术语词典命中：{{ glossaryTerms.map((t) => t.term).join('、') }}
            </div>
            <div v-if="!streamText" class="thinking-hint">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>
                {{
                  thinkingChars > 0
                    ? `模型思考中…（已思考 ${thinkingChars} 字）`
                    : '正在检索知识库…'
                }}
              </span>
            </div>
            <MarkdownView v-else :content="streamText" />
          </div>
        </div>
      </div>

      <div class="composer">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="send"
        />
        <div class="composer-actions">
          <el-button v-if="streaming" @click="abort">中止</el-button>
          <el-button type="primary" :loading="streaming" :disabled="!input.trim()" @click="send">
            发送
          </el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
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
const scrollEl = ref<HTMLElement | null>(null)
let aborter: AbortController | null = null

const shortDate = (v: string) => new Date(v).toLocaleDateString('zh-CN')

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
    messages.value.push({
      // 使用服务端返回的真实消息 ID，以便支持「重新生成」
      id: serverId ?? `local-a-${Date.now()}`,
      role: 'assistant',
      content: aborted ? `${text}\n\n> （已中止生成）` : text,
      sources,
      created_at: new Date().toISOString(),
    })
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
  // 先移除旧回答，生成完成后替换
  messages.value.splice(idx, 1)
  scrollToBottom()

  aborter = new AbortController()

  const finish = async (text: string, aborted: boolean, serverId?: string) => {
    streaming.value = false
    streamText.value = ''
    aborter = null
    messages.value.push({
      id: serverId ?? `local-a-${Date.now()}`,
      role: 'assistant',
      content: aborted ? `${text}\n\n> （已中止生成）` : text,
      sources,
      created_at: new Date().toISOString(),
    })
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
        // 失败时从服务端重新拉取，恢复被移除的消息
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
.chat-wrap {
  display: flex;
  height: calc(100vh - 60px);
}
.conv-list {
  width: 240px;
  border-right: 1px solid var(--kh-border);
  background: #fff;
  display: flex;
  flex-direction: column;
}
.conv-head {
  padding: 12px;
  border-bottom: 1px solid var(--kh-border);
}
.conv-items {
  flex: 1;
  overflow: auto;
  padding: 6px;
}
.conv-item {
  position: relative;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
}
.conv-item:hover {
  background: #f5f7fa;
}
.conv-item.active {
  background: #ecf5ff;
}
.conv-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 18px;
}
.conv-meta {
  color: var(--kh-text-sub);
  font-size: 12px;
  margin-top: 2px;
}
.conv-del {
  position: absolute;
  right: 8px;
  top: 10px;
  color: #c0c4cc;
  display: none;
}
.conv-item:hover .conv-del {
  display: block;
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--kh-border);
  background: #fff;
}
.mode-label {
  color: var(--kh-text-sub);
  font-size: 13px;
}
.spacer {
  flex: 1;
}
.messages {
  flex: 1;
  overflow: auto;
  padding: 18px 22px;
}
.msg {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
}
.msg-role {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 13px;
  font-weight: 600;
  background: #f0f2f5;
  color: #606266;
  flex-shrink: 0;
}
.msg.assistant .msg-role {
  background: #409eff;
  color: #fff;
}
.msg-body {
  flex: 1;
  min-width: 0;
}
.user-text {
  white-space: pre-wrap;
  background: #f5f7fa;
  padding: 10px 12px;
  border-radius: 8px;
}
.thinking-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--kh-text-sub);
  font-size: 13px;
}
.glossary-hint {
  font-size: 12px;
  color: #67c23a;
  margin-bottom: 6px;
}
.msg-actions {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  opacity: 0.5;
}
.msg-actions:hover {
  opacity: 1;
}
.sources {
  margin-top: 10px;
  border-top: 1px dashed var(--kh-border);
  padding-top: 8px;
}
.sources-title {
  font-size: 12px;
  color: var(--kh-text-sub);
  margin-bottom: 6px;
}
.source {
  font-size: 13px;
  margin-bottom: 6px;
}
.src-index {
  color: #409eff;
  margin-right: 4px;
}
.src-snippet {
  color: #909399;
  font-size: 12px;
  margin: 2px 0 6px 18px;
  line-height: 1.6;
}
.muted {
  color: var(--kh-text-sub);
  font-size: 12px;
}
.composer {
  border-top: 1px solid var(--kh-border);
  padding: 12px 16px;
  background: #fff;
}
.composer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
</style>
