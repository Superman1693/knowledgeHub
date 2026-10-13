<template>
  <div class="note-editor">
    <!-- 顶部工具条 -->
    <header class="ne-head">
      <div class="ne-head-left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回</span>
        </el-button>
        <el-tag size="small" effect="plain" :type="isNew ? 'success' : 'info'">
          {{ isNew ? '新建笔记' : '编辑笔记' }}
        </el-tag>
        <span v-if="dirty" class="ne-dirty">
          {{ autoSaving ? '自动保存中…' : '未保存（稍后自动保存）' }}
        </span>
      </div>
      <div class="ne-head-right">
        <el-select
          v-if="isNew"
          v-model="templateName"
          placeholder="从模板开始"
          clearable
          size="small"
          style="width: 156px"
          @change="applyTemplate"
        >
          <el-option
            v-for="t in templates"
            :key="t.filename"
            :label="t.name"
            :value="t.filename"
          />
        </el-select>
        <el-button size="small" :loading="uploading" @click="triggerUpload">
          <el-icon><Picture /></el-icon>
          <span>图片 / 附件</span>
        </el-button>
        <input
          ref="uploadInput"
          type="file"
          class="hidden-input"
          accept="image/*,.pdf,.zip,.txt,.md,.csv,.json,.xlsx,.docx,.mp3,.mp4"
          @change="onFilePicked"
        />
        <el-button v-if="!isNew" size="small" @click="linkPickerOpen = true">
          <el-icon><Link /></el-icon>
          <span>插入双链</span>
        </el-button>
        <el-radio-group v-model="layout" size="small">
          <el-radio-button value="split">分栏</el-radio-button>
          <el-radio-button value="edit">编辑</el-radio-button>
          <el-radio-button value="preview">预览</el-radio-button>
        </el-radio-group>
        <el-divider direction="vertical" />
        <el-tooltip content="Ctrl + S 保存">
          <el-button type="primary" size="small" :loading="saving" @click="save">
            <el-icon><Check /></el-icon>
            <span>保存</span>
          </el-button>
        </el-tooltip>
      </div>
    </header>

    <!-- 元信息 -->
    <div class="ne-meta">
      <el-input v-model="form.title" class="ne-title" placeholder="笔记标题" />
      <div class="ne-meta-row">
        <el-select
          v-model="form.category_id"
          placeholder="未分类"
          clearable
          size="small"
          style="width: 180px"
        >
          <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="标签（可回车新建）"
          size="small"
          style="flex: 1; min-width: 220px"
        >
          <el-option v-for="t in tagOptions" :key="t" :label="t" :value="t" />
        </el-select>

        <template v-if="!isNew">
          <el-tooltip :content="doc?.is_favorite ? '取消收藏' : '加入收藏'">
            <el-button size="small" @click="toggleFavorite">
              <el-icon :class="{ 'is-on': doc?.is_favorite }">
                <StarFilled v-if="doc?.is_favorite" />
                <Star v-else />
              </el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip :content="doc?.is_pinned ? '取消置顶' : '置顶'">
            <el-button size="small" @click="togglePinned">
              <el-icon :class="{ 'is-on': doc?.is_pinned }">
                <Top v-if="doc?.is_pinned" />
                <Top v-else />
              </el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip
            content="关闭后，该笔记不会进入 AI 检索范围（检索阶段即排除）"
            placement="bottom"
          >
            <span class="ne-ai-toggle">
              <el-icon><MagicStick /></el-icon>
              <span>允许 AI 读取</span>
              <el-switch v-model="aiEnabled" size="small" @change="toggleAi" />
            </span>
          </el-tooltip>
          <el-button size="small" @click="linksOpen = true">
            <el-icon><Link /></el-icon>
            <span>关联 {{ linkSummary.backlink_count + linkSummary.outgoing_count }}</span>
          </el-button>
          <el-button size="small" @click="historyOpen = true">
            <el-icon><Clock /></el-icon>
            <span>历史</span>
          </el-button>
        </template>
      </div>
    </div>

    <!-- 正文区 -->
    <div class="ne-body" :class="`is-${layout}`">
      <div v-show="layout !== 'preview'" class="ne-pane">
        <textarea
          ref="editorEl"
          v-model="form.content_text"
          class="ne-textarea"
          placeholder="开始记录…（支持 Markdown：标题、列表、代码块、表格；可直接粘贴截图）"
          spellcheck="false"
          @input="markDirty"
          @paste="onPaste"
          @mouseup="onSelection($event)"
          @keyup="onSelection()"
        />
      </div>
      <div v-show="layout !== 'edit'" class="ne-pane is-preview">
        <div class="ne-preview markdown-body" v-html="rendered" />
      </div>
    </div>

    <footer class="ne-foot">
      <span>{{ charCount }} 字 · {{ lineCount }} 行</span>
      <span class="ne-foot-spacer" />
      <span v-if="!isNew && doc" class="ne-foot-meta">
        {{ doc.source === 'note' ? '应用内笔记' : '导入文档' }} · {{ doc.chunk_count }} 个片段
      </span>
    </footer>

    <!-- 版本历史 -->
    <el-drawer v-model="historyOpen" title="版本历史" size="420px">
      <div v-if="!revisions.length" class="ne-empty">还没有历史版本（保存后会自动生成）</div>
      <div v-for="r in revisions" :key="r.id" class="ne-rev">
        <div class="ne-rev-main">
          <div class="ne-rev-time">{{ fmt(r.created_at) }}</div>
          <div class="ne-rev-meta">{{ r.note || '编辑保存' }} · {{ r.char_count }} 字</div>
        </div>
        <div class="ne-rev-actions">
          <el-button size="small" text @click="previewRevision(r.id)">查看</el-button>
          <el-button size="small" text @click="diffRevision(r)">对比</el-button>
          <el-button size="small" text type="primary" @click="restoreRevision(r.id)">
            回滚
          </el-button>
        </div>
      </div>
    </el-drawer>

    <!-- 历史版本全文 -->
    <el-dialog v-model="revisionPreviewOpen" :title="revisionTitle" width="760px">
      <pre class="ne-rev-content">{{ revisionContent }}</pre>
    </el-dialog>

    <!-- 版本对比：逐行标出相较当前版本的变化 -->
    <el-dialog v-model="diffOpen" :title="diffTitle" width="860px">
      <div v-if="!diffRows.length" class="ne-empty">两个版本内容一致</div>
      <div v-else class="ne-diff">
        <div v-for="(row, i) in diffRows" :key="i" class="ne-diff-row" :class="`is-${row.kind}`">
          <span class="ne-diff-sign">{{
            row.kind === 'add' ? '+' : row.kind === 'del' ? '−' : ' '
          }}</span>
          <span class="ne-diff-text">{{ row.text || ' ' }}</span>
        </div>
      </div>
      <template #footer>
        <span class="ne-diff-summary">{{ diffSummary }}</span>
        <el-button @click="diffOpen = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 编辑冲突：正文在别处被改过（乐观锁拦截） -->
    <el-dialog v-model="conflictOpen" title="这篇笔记已被其它地方修改" width="720px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="为避免覆盖对方的改动，本次保存已取消"
      >
        <div>
          库中的正文与你开始编辑时不一样了（可能是在编辑器里改了同一个
          <code>.md</code> 文件，或另一个标签页在编辑）。
          你在编辑器里的内容仍然保留，不会丢——请选择如何处理。
        </div>
      </el-alert>
      <div class="ne-conflict">
        <div class="ne-conflict-col">
          <div class="ne-conflict-title">你正在编辑的版本</div>
          <pre class="ne-rev-content">{{ form.content_text }}</pre>
        </div>
        <div class="ne-conflict-col">
          <div class="ne-conflict-title">库中最新版本</div>
          <pre class="ne-rev-content">{{ conflictRemote }}</pre>
        </div>
      </div>
      <template #footer>
        <el-button @click="conflictOpen = false">稍后处理</el-button>
        <el-button @click="takeRemote">用库中最新版覆盖编辑器</el-button>
        <el-button type="primary" @click="forceSave">保留我的修改并强制保存</el-button>
      </template>
    </el-dialog>

    <!-- 关联：反向链接 + 出链 -->
    <el-drawer v-model="linksOpen" title="关联笔记" size="420px">
      <div class="ne-links-section">
        <div class="ne-links-title">
          反向链接（谁引用了本笔记）· {{ linkSummary.backlink_count }}
        </div>
        <div v-if="!linkSummary.backlinks.length" class="ne-empty">还没有其它笔记引用本笔记</div>
        <button
          v-for="b in linkSummary.backlinks"
          :key="b.link_id"
          class="ne-link-item"
          type="button"
          @click="goDoc(b.source_document_id)"
        >
          <el-icon><Document /></el-icon>
          <span class="ne-link-text">{{ b.source_document_title }}</span>
        </button>
      </div>

      <div class="ne-links-section">
        <div class="ne-links-title">
          出链（本笔记引用了谁）· {{ linkSummary.outgoing_count }}
        </div>
        <div v-if="!linkSummary.outgoing.length" class="ne-empty">
          正文里写 <code>[[笔记标题]]</code> 即可建立双链
        </div>
        <button
          v-for="o in linkSummary.outgoing"
          :key="o.link_id"
          class="ne-link-item"
          :class="{ 'is-unresolved': !o.resolved }"
          type="button"
          @click="o.resolved && o.target_document_id && goDoc(o.target_document_id)"
        >
          <el-icon><Document /></el-icon>
          <span class="ne-link-text">{{ o.target_title }}</span>
          <span v-if="!o.resolved" class="ne-link-tag">未创建</span>
        </button>
      </div>
    </el-drawer>

    <!-- 插入双链：选择目标笔记 -->
    <el-dialog v-model="linkPickerOpen" title="插入双向链接" width="520px">
      <el-input v-model="linkKeyword" placeholder="搜索笔记标题" clearable />
      <div class="ne-picker">
        <button
          v-for="t in filteredTargets"
          :key="t"
          class="ne-picker-item"
          type="button"
          @click="insertLink(t)"
        >
          <el-icon><Document /></el-icon>
          <span>{{ t }}</span>
        </button>
        <div v-if="!filteredTargets.length" class="ne-empty">没有匹配的笔记</div>
      </div>
    </el-dialog>
    <!-- 选中文字后的浮动工具栏（页内呼出 AI） -->
    <Teleport to="body">
      <div
        v-if="selToolbar"
        class="sel-toolbar"
        :style="{ left: selToolbar.x + 'px', top: selToolbar.y + 'px' }"
      >
        <button type="button" @click="runAssist('explain')">
          <el-icon><Reading /></el-icon><span>解释</span>
        </button>
        <button type="button" @click="runAssist('summarize')">
          <el-icon><Document /></el-icon><span>总结</span>
        </button>
        <button type="button" @click="runAssist('cards')">
          <el-icon><Notebook /></el-icon><span>生成卡片</span>
        </button>
        <button type="button" @click="runAssist('related')">
          <el-icon><Link /></el-icon><span>找关联</span>
        </button>
      </div>
    </Teleport>

    <!-- AI 结果 -->
    <el-dialog
      v-model="assistOpen"
      :title="assistTitle"
      width="680px"
      :close-on-click-modal="false"
    >
      <div v-loading="assistLoading" class="assist-body">
        <div class="assist-src">
          <div class="assist-src-label">选中的内容</div>
          <div class="assist-src-text">{{ assistResult?.text || selectedText }}</div>
        </div>

        <template v-if="!assistLoading && assistResult">
          <!-- 解释 / 总结 -->
          <div v-if="assistResult.result" class="assist-result">
            <MarkdownView :content="assistResult.result" />
          </div>

          <!-- 生成卡片 -->
          <div v-else-if="assistResult.cards" class="assist-cards">
            <div v-if="!assistResult.cards.length" class="assist-empty">
              没有生成卡片（选中的内容可能不足以出题）
            </div>
            <div v-for="c in assistResult.cards" :key="c.id" class="assist-card">
              <div class="assist-card-front">{{ c.front }}</div>
              <div class="assist-card-back">{{ c.back }}</div>
            </div>
            <div v-if="assistResult.cards.length" class="assist-note">
              已加入复习队列，可在「学习辅助 → 今日复习」中复习。
            </div>
          </div>

          <!-- 找关联 -->
          <div v-else-if="assistResult.related" class="assist-related">
            <div v-if="!assistResult.related.length" class="assist-empty">
              知识库里没有找到相关内容
            </div>
            <button
              v-for="h in assistResult.related"
              :key="h.chunk_id"
              class="assist-rel-item"
              type="button"
              @click="goRelated(h)"
            >
              <div class="assist-rel-title">
                {{ h.document_title }}
                <span v-if="h.heading" class="muted">· {{ h.heading }}</span>
              </div>
              <div class="assist-rel-snippet">{{ h.snippet }}</div>
            </button>
          </div>
        </template>
      </div>

      <template #footer>
        <el-button @click="assistOpen = false">关闭</el-button>
        <el-button
          v-if="assistResult?.result"
          type="primary"
          @click="insertAssistResult"
        >
          插入到笔记
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { attachmentsApi, categoriesApi, documentsApi, insightsApi, tagsApi, workspaceApi } from '@/api'
import type {
  AssistResult,
  Category,
  DocumentDetail,
  LinkSummary,
  RevisionOut,
  SearchHit,
  TemplateOut,
} from '@/api/types'
import { renderMarkdown } from '@/utils/markdown'

const route = useRoute()
const router = useRouter()

const isNew = computed(() => route.name === 'note-new')
const docId = computed(() => (route.params.id as string | undefined) ?? '')

const doc = ref<DocumentDetail | null>(null)
const categories = ref<Category[]>([])
const tagOptions = ref<string[]>([])
const saving = ref(false)
const dirty = ref(false)
const layout = ref<'split' | 'edit' | 'preview'>('split')
const editorEl = ref<HTMLTextAreaElement | null>(null)
const aiEnabled = ref(true)

const historyOpen = ref(false)
const revisions = ref<RevisionOut[]>([])
const revisionPreviewOpen = ref(false)
const revisionContent = ref('')
const revisionTitle = ref('历史版本')

// ---------------- 自动保存 + 冲突检测 ----------------
/** 正文指纹基线：开始编辑 / 上次保存成功时的 content_hash（乐观锁依据） */
const baseHash = ref('')
const autoSaving = ref(false)
const conflictOpen = ref(false)
const conflictRemote = ref('')
const conflictRemoteHash = ref('')
const AUTOSAVE_DELAY = 1500
let autosaveTimer: number | null = null

// ---------------- 笔记页内 AI 助手 ----------------
const selectedText = ref('')
const selToolbar = ref<{ x: number; y: number } | null>(null)
const assistOpen = ref(false)
const assistLoading = ref(false)
const assistResult = ref<AssistResult | null>(null)
const assistTitle = ref('AI 助手')

function onSelection(event?: MouseEvent) {
  const el = editorEl.value
  if (!el) return
  const start = el.selectionStart ?? 0
  const end = el.selectionEnd ?? 0
  const text = form.value.content_text.slice(start, end).trim()
  if (!text) {
    selToolbar.value = null
    return
  }
  selectedText.value = text
  const rect = el.getBoundingClientRect()
  // textarea 无法得到选区的像素位置，工具栏放在编辑器顶部附近，保证可用且不遮挡选区
  selToolbar.value = {
    x: Math.max(12, Math.min(window.innerWidth - 330, rect.left + 18)),
    y: Math.max(58, rect.top + 10),
  }
}

async function runAssist(action: 'explain' | 'summarize' | 'cards' | 'related') {
  const text = selectedText.value.trim()
  if (!text) return
  const titles: Record<typeof action, string> = {
    explain: '解释选中内容',
    summarize: '总结选中内容',
    cards: '从选中内容生成卡片',
    related: '选中内容的关联资料',
  }
  selToolbar.value = null
  assistTitle.value = titles[action]
  assistOpen.value = true
  assistLoading.value = true
  assistResult.value = null
  try {
    assistResult.value = await insightsApi.assist({
      text,
      action,
      document_id: isNew.value ? null : docId.value,
      count: 5,
    })
  } catch {
    assistOpen.value = false
  } finally {
    assistLoading.value = false
  }
}

function goRelated(hit: SearchHit) {
  assistOpen.value = false
  router.push({ path: `/documents/${hit.document_id}`, query: { chunk: hit.chunk_id } })
}

function insertAssistResult() {
  const result = assistResult.value?.result
  if (!result) return
  insertTextAtCursor(`\n\n> AI 助手整理：\n${result}\n`)
  assistOpen.value = false
  ElMessage.success('已插入到笔记，记得保存')
}

// ---------------- 笔记模板 ----------------
const templates = ref<TemplateOut[]>([])
const templateName = ref<string | null>(null)

async function loadTemplates() {
  if (!isNew.value) return
  try {
    templates.value = (await workspaceApi.templates()).items
  } catch {
    templates.value = []
  }
}

/** 应用模板：填充正文；标题为空时用模板名兜底。 */
async function applyTemplate(filename: string | null) {
  if (!filename) return
  try {
    const res = await workspaceApi.template(filename)
    form.value.content_text = res.content
    if (!form.value.title.trim()) {
      form.value.title = filename.replace(/\.md$/, '')
    }
    dirty.value = true
  } catch {
    /* 错误提示由拦截器处理 */
  }
}

// ---------------- 双向链接 ----------------
const linksOpen = ref(false)
const linkPickerOpen = ref(false)
const linkKeyword = ref('')
const linkTargets = ref<string[]>([])
const linkSummary = ref<LinkSummary>({
  outgoing: [],
  backlinks: [],
  unresolved: [],
  outgoing_count: 0,
  backlink_count: 0,
  unresolved_count: 0,
})

const filteredTargets = computed(() => {
  const kw = linkKeyword.value.trim().toLowerCase()
  const list = linkTargets.value
  const hit = kw ? list.filter((t) => t.toLowerCase().includes(kw)) : list
  return hit.slice(0, 50)
})

async function loadLinks() {
  if (isNew.value) return
  try {
    linkSummary.value = await documentsApi.links(docId.value)
  } catch {
    /* 忽略 */
  }
}

async function loadLinkTargets() {
  try {
    linkTargets.value = (await documentsApi.linkTargets()).titles
  } catch {
    linkTargets.value = []
  }
}

/** 在光标处插入文本（插入双链与插入附件共用）。 */
function insertTextAtCursor(snippet: string) {
  const el = editorEl.value
  if (!el) {
    form.value.content_text += snippet
  } else {
    const text = form.value.content_text
    const start = el.selectionStart ?? text.length
    const end = el.selectionEnd ?? start
    form.value.content_text = text.slice(0, start) + snippet + text.slice(end)
    nextTick(() => {
      el.focus()
      const pos = start + snippet.length
      el.setSelectionRange(pos, pos)
    })
  }
  dirty.value = true
}

/** 在光标处插入 `[[标题]]`。 */
function insertLink(title: string) {
  insertTextAtCursor(`[[${title}]]`)
  linkPickerOpen.value = false
  linkKeyword.value = ''
}

// ---------------- 附件（图片 / 文件）----------------
const uploadInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

function triggerUpload() {
  uploadInput.value?.click()
}

async function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 清空以便再次选择同一个文件
  if (file) await uploadAndInsert(file)
}

/** 直接粘贴截图即上传并插入（技术笔记里最常用的路径）。 */
async function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of Array.from(items)) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        e.preventDefault()
        await uploadAndInsert(file)
        return
      }
    }
  }
}

async function uploadAndInsert(file: File) {
  uploading.value = true
  try {
    const res = await attachmentsApi.upload(file)
    insertTextAtCursor(`\n${res.markdown}\n`)
    ElMessage.success(res.kind === 'image' ? '图片已插入' : '附件已插入')
  } catch {
    /* 错误提示由拦截器统一处理 */
  } finally {
    uploading.value = false
  }
}

function goDoc(id: string) {
  router.push(`/documents/${id}`)
}

const form = ref<{ title: string; content_text: string; category_id: string | null; tags: string[] }>({
  title: '',
  content_text: '',
  category_id: null,
  tags: [],
})

const rendered = computed(() => renderMarkdown(form.value.content_text || ''))
const charCount = computed(() => (form.value.content_text || '').length)
const lineCount = computed(() => (form.value.content_text || '').split('\n').length)

function fmt(v: string) {
  return new Date(v).toLocaleString('zh-CN')
}

function markDirty() {
  dirty.value = true
}

async function loadOptions() {
  try {
    categories.value = await categoriesApi.list()
  } catch {
    /* 忽略 */
  }
  try {
    const tags = await tagsApi.list()
    tagOptions.value = tags.map((t) => t.name)
  } catch {
    /* 忽略 */
  }
}

async function loadNote() {
  if (isNew.value) return
  const detail = await documentsApi.get(docId.value)
  doc.value = detail
  form.value = {
    title: detail.title,
    content_text: detail.content_text || '',
    category_id: detail.category_id ?? null,
    tags: (detail.tags || []).map((t) => t.name),
  }
  aiEnabled.value = detail.ai_enabled !== false
  baseHash.value = detail.content_hash || ''
  dirty.value = false
}

async function loadRevisions() {
  if (isNew.value) return
  try {
    revisions.value = await documentsApi.revisions(docId.value)
  } catch {
    revisions.value = []
  }
}

/**
 * 保存笔记。
 *
 * - `silent`：自动保存调用——不转按钮 loading、不弹成功提示
 * - `force` ：冲突后用户选择「保留我的修改」，此时不带乐观锁基线
 */
async function save(opts: { silent?: boolean; force?: boolean } = {}) {
  const title = form.value.title.trim()
  if (!title) {
    if (!opts.silent) ElMessage.warning('请先填写笔记标题')
    return
  }
  if (opts.silent) autoSaving.value = true
  else saving.value = true
  try {
    if (isNew.value) {
      if (opts.silent) return // 新笔记还没有 id，交给用户手动创建
      const created = await documentsApi.createNote({
        title,
        content_text: form.value.content_text,
        category_id: form.value.category_id,
        tags: form.value.tags,
        // 新建时就能定私密：避免「先建后改」的窗口期内被 AI 检索读到
        ai_enabled: aiEnabled.value,
      })
      dirty.value = false
      ElMessage.success('笔记已创建')
      await router.replace({ name: 'note-edit', params: { id: created.id } })
      doc.value = created
      aiEnabled.value = created.ai_enabled !== false
      baseHash.value = created.content_hash || ''
      await loadRevisions()
      await loadLinks()
      return
    }

    const updated = await documentsApi.update(
      docId.value,
      {
        title,
        category_id: form.value.category_id,
        content_text: form.value.content_text,
        // 乐观锁：带上「开始编辑时的正文指纹」；force 时省略（用户已确认覆盖）
        ...(opts.force ? {} : { base_content_hash: baseHash.value || undefined }),
      },
      { silent: opts.silent },
    )
    doc.value = updated
    baseHash.value = updated.content_hash || ''
    // 标签单独保存（覆盖式）
    await tagsApi.setDocumentTags(docId.value, form.value.tags)
    dirty.value = false
    if (!opts.silent) ElMessage.success('已保存（正文已写回文件并重建索引）')
    await loadRevisions()
    await loadLinks()
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 409) {
      // 保持 dirty=true，让「离开守卫」继续生效——否则用户会以为已经保存好了
      await openConflict()
    }
    // 其它错误：请求层已提示（silent 时同样静默，由冲突流程兜底）
  } finally {
    if (!opts.silent) saving.value = false
    autoSaving.value = false
  }
}

/** 打开冲突对话框：拉取库中最新正文，与编辑器里的内容并排展示。 */
async function openConflict() {
  try {
    const latest = await documentsApi.get(docId.value)
    conflictRemote.value = latest.content_text || ''
    conflictRemoteHash.value = latest.content_hash || ''
  } catch {
    conflictRemote.value = ''
    conflictRemoteHash.value = ''
  }
  conflictOpen.value = true
}

/** 用库中最新版覆盖编辑器（放弃自己的改动）。 */
function takeRemote() {
  form.value.content_text = conflictRemote.value
  baseHash.value = conflictRemoteHash.value
  dirty.value = false
  conflictOpen.value = false
  ElMessage.info('已载入库中最新版本')
}

/** 保留自己的修改，强制覆盖库中内容。 */
async function forceSave() {
  conflictOpen.value = false
  await save({ force: true })
}

/** 内容被改动后调度一次自动保存（1.5s 防抖，避免每敲一个字都发请求）。 */
function scheduleAutosave() {
  if (isNew.value || conflictOpen.value) return
  if (autosaveTimer !== null) window.clearTimeout(autosaveTimer)
  autosaveTimer = window.setTimeout(() => {
    autosaveTimer = null
    if (dirty.value && !saving.value && !conflictOpen.value) void save({ silent: true })
  }, AUTOSAVE_DELAY)
}

// dirty 由编辑器/表单的输入处理器置位，因此监听它即可覆盖所有修改入口
watch(dirty, (v) => {
  if (v) scheduleAutosave()
})

async function toggleFavorite() {
  if (!doc.value) return
  const next = !doc.value.is_favorite
  const updated = await documentsApi.setFavorite(docId.value, next)
  doc.value = { ...doc.value, is_favorite: updated.is_favorite }
  ElMessage.success(next ? '已加入收藏' : '已取消收藏')
}

async function togglePinned() {
  if (!doc.value) return
  const next = !doc.value.is_pinned
  const updated = await documentsApi.setPinned(docId.value, next)
  doc.value = { ...doc.value, is_pinned: updated.is_pinned }
  ElMessage.success(next ? '已置顶' : '已取消置顶')
}

async function toggleAi(value: string | number | boolean) {
  const enabled = Boolean(value)
  // 新建中：还没有文档可更新，只记住选择，保存建笔记时一起提交。
  // 此前这里直接 return，开关在新建页点了没反应——而私密笔记最需要
  // 「建出来就是私密」，事后再改有一个被检索/问答读到的窗口期。
  if (!doc.value) return
  try {
    const updated = await documentsApi.update(docId.value, { ai_enabled: enabled })
    doc.value = { ...doc.value, ai_enabled: updated.ai_enabled }
    ElMessage.success(enabled ? '已允许 AI 读取该笔记' : '已设为私密：AI 检索将排除该笔记')
  } catch {
    aiEnabled.value = !enabled
  }
}

async function previewRevision(id: string) {
  try {
    const rev = await documentsApi.revision(docId.value, id)
    revisionContent.value = rev.content_text || '（空）'
    revisionTitle.value = `历史版本 · ${fmt(rev.created_at)}`
    revisionPreviewOpen.value = true
  } catch {
    /* 忽略 */
  }
}

// ---------------- 版本对比（逐行 diff） ----------------
const diffOpen = ref(false)
const diffTitle = ref('版本对比')
const diffRows = ref<{ kind: 'same' | 'add' | 'del'; text: string }[]>([])
const diffSummary = ref('')

/**
 * 行级差异（LCS 动态规划）。
 *
 * 刻意不引入 diff 库：笔记通常只有几百行，O(n·m) 的表格完全够用，
 * 而少一个依赖就少一处供应链与体积负担。
 */
function diffLines(oldText: string, newText: string) {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  const n = a.length
  const m = b.length
  // dp[i][j] = a[i..] 与 b[j..] 的最长公共子序列长度
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const rows: { kind: 'same' | 'add' | 'del'; text: string }[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ kind: 'same', text: a[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ kind: 'del', text: a[i] })
      i++
    } else {
      rows.push({ kind: 'add', text: b[j] })
      j++
    }
  }
  while (i < n) rows.push({ kind: 'del', text: a[i++] })
  while (j < m) rows.push({ kind: 'add', text: b[j++] })
  return rows
}

/** 对比某个历史版本与「当前编辑器里的内容」。 */
async function diffRevision(r: RevisionOut) {
  try {
    const rev = await documentsApi.revision(docId.value, r.id)
    const oldText = rev.content_text || ''
    const newText = form.value.content_text || ''
    diffRows.value = diffLines(oldText, newText)
    const add = diffRows.value.filter((x) => x.kind === 'add').length
    const del = diffRows.value.filter((x) => x.kind === 'del').length
    diffSummary.value = `相比 ${fmt(r.created_at)} 的版本：新增 ${add} 行、删除 ${del} 行`
    diffTitle.value = `对比历史版本 · ${fmt(r.created_at)} → 当前编辑内容`
    diffOpen.value = true
  } catch {
    /* 忽略 */
  }
}

async function restoreRevision(id: string) {
  try {
    await ElMessageBox.confirm(
      '将把正文回滚到该版本（当前版本会自动备份为一条新的历史记录）。是否继续？',
      '回滚确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  const restored = await documentsApi.restoreRevision(docId.value, id)
  doc.value = restored
  form.value.content_text = restored.content_text || ''
  form.value.title = restored.title
  dirty.value = false
  ElMessage.success('已回滚')
  await loadRevisions()
}

function goBack() {
  if (dirty.value) {
    ElMessageBox.confirm('有未保存的修改，确定离开？', '提示', { type: 'warning' })
      .then(() => router.back())
      .catch(() => {})
    return
  }
  router.back()
}

function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    save()
  }
}

onMounted(async () => {
  await loadOptions()
  await loadTemplates()
  await loadNote()
  await loadRevisions()
  await loadLinks()
  await loadLinkTargets()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
  editorEl.value?.focus()
})

/**
 * 关闭 / 刷新浏览器窗口时的兜底提示。
 * 应用内的路由跳转由下面的 onBeforeRouteLeave 拦截。
 */
function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!dirty.value) return
  e.preventDefault()
  // 部分浏览器仍要求设置 returnValue 才会弹出确认框
  e.returnValue = ''
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
  // 取消排队中的自动保存，避免组件卸载后仍发起请求
  if (autosaveTimer !== null) window.clearTimeout(autosaveTimer)
  autosaveTimer = null
})

/**
 * 离开编辑器前拦截未保存的修改。
 *
 * 此前只有「返回」按钮做了确认，点侧边栏、Ctrl+K 跳转、浏览器后退都会
 * **静默丢弃**正在写的内容——这是最不可接受的数据丢失路径。
 */
onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的修改，确定离开？', '提示', { type: 'warning' })
    return true
  } catch {
    return false
  }
})
</script>

<style scoped>
.note-editor {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--kh-bg);
}

.ne-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 18px;
  background: var(--kh-panel);
  border-bottom: 1px solid var(--kh-border);
}

.ne-head-left,
.ne-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ne-dirty {  font-size: 12px;
  color: var(--kh-warning, #b88230);
}

.ne-meta {
  padding: 12px 18px 10px;
  background: var(--kh-panel);
  border-bottom: 1px solid var(--kh-border-light);
}

.ne-title :deep(input) {
  font-size: 19px;
  font-weight: 600;
}

.ne-meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.ne-ai-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--kh-text-sub);
}

.ne-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.ne-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.ne-body.is-split .ne-pane.is-preview {
  border-left: 1px solid var(--kh-border-light);
}

.ne-textarea {
  flex: 1;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  padding: 18px 20px;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 14px;
  line-height: 1.8;
  color: var(--kh-text);
  background: var(--kh-panel);
}

.ne-preview {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
  background: var(--kh-bg);
}

.ne-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 18px;
  font-size: 11.5px;
  color: var(--kh-text-mute);
  background: var(--kh-panel);
  border-top: 1px solid var(--kh-border-light);
}

.ne-foot-spacer {
  flex: 1;
}

.is-on {
  color: var(--kh-primary);
}

.ne-empty {
  color: var(--kh-text-mute);
  font-size: 13px;
  padding: 20px 0;
  text-align: center;
}

.hidden-input {
  display: none;
}

/* ---- 选中文字后的页内 AI 工具栏 ---- */
.sel-toolbar {
  position: fixed;
  z-index: 4000;
  display: flex;
  gap: 2px;
  padding: 4px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: 8px;
  box-shadow: var(--kh-shadow-lg);
}

.sel-toolbar button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--kh-text-sub);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.sel-toolbar button:hover {
  background: var(--kh-primary-soft);
  color: var(--kh-primary);
}

/* ---- 页内 AI 结果 ---- */
.assist-body {
  min-height: 120px;
}

.assist-src {
  padding: 9px 11px;
  border-left: 3px solid var(--kh-primary-border);
  border-radius: 4px;
  background: var(--kh-bg-deep);
  margin-bottom: 14px;
}

.assist-src-label {
  font-size: 11px;
  color: var(--kh-text-mute);
  margin-bottom: 3px;
}

.assist-src-text {
  max-height: 100px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--kh-text-sub);
  font-size: 12.5px;
  line-height: 1.6;
}

.assist-result {
  line-height: 1.75;
}

.assist-card {
  padding: 10px 12px;
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  margin-bottom: 8px;
}

.assist-card-front {
  font-size: 13.5px;
}

.assist-card-back {
  margin-top: 5px;
  padding-top: 5px;
  border-top: 1px dashed var(--kh-border-light);
  color: var(--kh-text-sub);
  font-size: 12.5px;
}

.assist-note,
.assist-empty {
  color: var(--kh-text-mute);
  font-size: 12.5px;
  padding: 8px 0;
}

.assist-rel-item {
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  background: var(--kh-panel);
  text-align: left;
  cursor: pointer;
  font-family: inherit;
  margin-bottom: 8px;
}

.assist-rel-item:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.assist-rel-title {
  font-size: 13px;
  color: var(--kh-primary);
}

.assist-rel-snippet {
  margin-top: 3px;
  color: var(--kh-text-sub);
  font-size: 12px;
  line-height: 1.6;
}


.ne-rev {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 4px;
  border-bottom: 1px dashed var(--kh-border-light);
}

.ne-rev-time {
  font-size: 13px;
}

.ne-rev-meta {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  margin-top: 2px;
}

.ne-rev-content {
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12.5px;
  line-height: 1.7;
  margin: 0;
}

/* ---- 关联（双向链接） ---- */
.ne-links-section {
  margin-bottom: 20px;
}

.ne-links-title {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  margin-bottom: 8px;
}

.ne-link-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 1px solid var(--kh-border-light);
  background: var(--kh-panel);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  color: var(--kh-text);
  text-align: left;
}

.ne-link-item:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.ne-link-item.is-unresolved {
  border-style: dashed;
  color: var(--kh-text-sub);
  cursor: default;
}

.ne-link-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ne-link-tag {
  font-size: 10.5px;
  color: var(--kh-text-mute);
  border: 1px solid var(--kh-border);
  border-radius: 4px;
  padding: 0 4px;
}

.ne-picker {
  margin-top: 10px;
  max-height: 46vh;
  overflow-y: auto;
}

.ne-picker-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: none;
  background: transparent;
  border-radius: 7px;
  padding: 8px 10px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  color: var(--kh-text);
  text-align: left;
}

.ne-picker-item:hover {
  background: var(--kh-primary-soft);
}

@media (max-width: 900px) {
  .ne-body.is-split .ne-pane.is-preview {
    display: none;
  }

  /* 冲突对比两栏并排在手机上每栏只剩 150px 左右，长内容会挤成一团 → 改上下堆叠 */
  .ne-conflict {
    grid-template-columns: 1fr;
  }
}

/* ---------------- 编辑冲突（乐观锁） ---------------- */
.ne-conflict {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
}

.ne-conflict-col {
  min-width: 0;
}

.ne-conflict-title {
  font-size: 12px;
  color: var(--kh-text-sub);
  margin-bottom: 6px;
}

.ne-conflict .ne-rev-content {
  max-height: 260px;
}

/* ---------------- 版本对比 ---------------- */
.ne-diff {
  max-height: 480px;
  overflow: auto;
  border: 1px solid var(--kh-border-light);
  border-radius: 8px;
  font-family: var(--kh-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 12px;
  line-height: 1.7;
}

.ne-diff-row {
  display: flex;
  gap: 8px;
  padding: 0 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

.ne-diff-row.is-add {
  background: rgba(103, 194, 58, 0.14);
}

.ne-diff-row.is-del {
  background: rgba(245, 108, 108, 0.14);
  text-decoration: line-through;
  opacity: 0.85;
}

.ne-diff-sign {
  width: 12px;
  flex-shrink: 0;
  color: var(--kh-text-mute);
  user-select: none;
}

.ne-diff-text {
  flex: 1;
  min-width: 0;
}

.ne-diff-summary {
  float: left;
  font-size: 12px;
  color: var(--kh-text-sub);
  line-height: 32px;
}
</style>
