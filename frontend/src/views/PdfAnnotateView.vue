<template>
  <div class="kh-pdf">
    <!-- ===================== 顶栏 ===================== -->
    <header class="pdf-top">
      <el-button link class="pdf-back" @click="router.back()">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回</span>
      </el-button>

      <div class="pdf-title" :title="doc?.title">{{ doc?.title || '加载中…' }}</div>

      <div class="pdf-tools">
        <div class="pdf-pager">
          <el-input-number
            v-model="jumpPage"
            size="small"
            :min="1"
            :max="numPages || 1"
            controls-position="right"
            class="pdf-pager-input"
            @change="onJump"
          />
          <span class="pdf-muted">/ {{ numPages }} 页</span>
        </div>

        <el-button-group>
          <el-button size="small" :disabled="scale <= 0.4" @click="zoomBy(-0.2)">−</el-button>
          <el-button size="small" @click="resetZoom">{{ Math.round(scale * 100) }}%</el-button>
          <el-button size="small" :disabled="scale >= 3" @click="zoomBy(0.2)">+</el-button>
        </el-button-group>

        <el-button
          size="small"
          type="primary"
          :disabled="!total"
          :loading="exporting"
          @click="exportNote"
        >
          <el-icon><DocumentAdd /></el-icon>
          <span>导出为笔记</span>
        </el-button>
      </div>
    </header>

    <!-- ===================== 主体：页面 + 侧栏 ===================== -->
    <div class="pdf-main">
      <div ref="scrollEl" class="pdf-scroll">
        <div v-if="loadError" class="pdf-error">
          <el-icon><WarningFilled /></el-icon>
          <p>{{ loadError }}</p>
        </div>

        <div v-for="p in numPages" :key="p" class="pdf-slot">
          <div
            class="pdf-page"
            :data-page="p"
            :ref="(el) => setPageEl(p, el)"
            :style="placeholderStyle"
          >
            <canvas :ref="(el) => setCanvasEl(p, el)" />
            <!-- 高亮层夹在画布与文本层之间：
                 必须在画布之上才看得见，又必须在文本层之下，
                 否则会挡住鼠标导致划词失效 -->
            <div class="kh-hl">
              <template v-for="a in annotationsOf(p)" :key="a.id">
                <div
                  v-for="(r, i) in displayRects(a)"
                  :key="`${a.id}-${i}`"
                  class="kh-hl-rect"
                  :class="[`is-${a.color}`, { 'is-flash': flashId === a.id }]"
                  :style="rectStyle(r)"
                />
              </template>
            </div>
            <div class="textLayer" :ref="(el) => setTextEl(p, el)" />
            <div v-if="lostOn(p) > 0" class="kh-hl-lost">
              本页有 {{ lostOn(p) }} 条批注的引文未能在文本层定位
            </div>
          </div>
          <div class="pdf-page-no">{{ p }}</div>
        </div>
      </div>

      <!-- ===================== 侧栏 ===================== -->
      <aside class="pdf-side">
        <div class="side-head">
          <span class="side-title">批注</span>
          <span class="side-count">{{ total }} 条</span>
        </div>

        <el-input
          v-model="keyword"
          size="small"
          placeholder="在批注里搜索…"
          clearable
          class="side-search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <div class="side-hint">
          在正文里<strong>划选文字</strong>即可高亮。批注文字会被导出成笔记，
          于是检索、双链、闪卡全部自动可用。
        </div>

        <div v-if="!filtered.length" class="side-empty">
          {{ total ? '没有匹配的批注' : '还没有批注' }}
        </div>

        <div
          v-for="a in filtered"
          :key="a.id"
          class="side-item"
          :class="{ 'is-active': activeId === a.id }"
          @click="focusAnnotation(a)"
        >
          <div class="side-item-top">
            <span class="side-dot" :style="{ background: colorCss(a.color) }" />
            <span class="side-page">第 {{ a.page_no }} 页</span>
            <span v-if="anchorStatus[a.id] === 'relocated'" class="side-flag is-warn">
              已按引文重定位
            </span>
            <span v-else-if="anchorStatus[a.id] === 'lost'" class="side-flag is-lost">
              定位可能已失效
            </span>
            <span class="side-spacer" />
            <el-dropdown trigger="click" @command="onItemCommand($event, a)">
              <el-icon class="side-more" @click.stop><MoreFilled /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="comment">编辑批注</el-dropdown-item>
                  <el-dropdown-item command="cards">生成闪卡</el-dropdown-item>
                  <el-dropdown-item command="copy">复制引文</el-dropdown-item>
                  <el-dropdown-item divided command="remove">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <div class="side-quote">{{ a.quote }}</div>
          <div v-if="a.comment" class="side-comment">{{ a.comment }}</div>

          <div class="side-colors" @click.stop>
            <button
              v-for="c in COLORS"
              :key="c.name"
              class="side-color"
              :class="{ 'is-on': a.color === c.name }"
              :style="{ background: c.css }"
              :title="`改成${c.label}`"
              type="button"
              @click="recolor(a, c.name)"
            />
          </div>
        </div>
      </aside>
    </div>

    <!-- ===================== 划词工具条 ===================== -->
    <div
      v-if="pending"
      class="kh-sel-toolbar"
      :style="toolbarStyle"
      @mousedown.prevent
    >
      <button
        v-for="c in COLORS"
        :key="c.name"
        class="sel-color"
        :style="{ background: c.css }"
        :title="`高亮（${c.label}）`"
        type="button"
        @click="createHighlight(c.name)"
      />
      <span class="sel-divider" />
      <button class="sel-btn" type="button" @click="openCommentDialog">
        <el-icon><EditPen /></el-icon>
        <span>写批注</span>
      </button>
    </div>

    <!-- ===================== 写批注对话框 ===================== -->
    <el-dialog v-model="commentDialog.visible" title="写批注" width="520px">
      <div class="cmt-quote">{{ commentDialog.quote }}</div>
      <el-input
        v-model="commentDialog.text"
        type="textarea"
        :rows="4"
        maxlength="2000"
        show-word-limit
        placeholder="写下你的理解。这段文字会进检索、能和其它笔记双链、也能出闪卡。"
      />
      <template #footer>
        <el-button @click="commentDialog.visible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="commentDialog.saving"
          @click="saveComment"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- ===================== 闪卡结果 ===================== -->
    <el-dialog v-model="cardsDialog.visible" title="生成的闪卡" width="520px">
      <div v-if="!cardsDialog.items.length" class="cmt-quote">
        没能生成卡片（可能是 AI 服务不可用，稍后再试）。
      </div>
      <div v-for="(c, i) in cardsDialog.items" :key="i" class="card-row">
        <div class="card-front">{{ c.front }}</div>
        <div class="card-back">{{ c.back }}</div>
      </div>
      <template #footer>
        <el-button v-if="cardsDialog.items.length" type="primary" @click="goLearning">
          去复习
        </el-button>
        <el-button @click="cardsDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * PDF 阅读与批注。
 *
 * ## 坐标系契约（与 `utils/pdfAnchor.ts` 一致）
 * 所有矩形都以**渲染后的页面元素**为参照归一化到 0..1，
 * 所以与缩放、设备像素比、页面旋转都无关（阶段 0 已验证：
 * 0.5/1/2 三档缩放下归一化结果偏差为 0）。
 *
 * ## 引文是主锚，坐标是辅助
 * 每次加载时用 `quote` 在文本层里重新定位一遍存档坐标：
 * PDF 被换成同内容的新版后坐标会整体偏移，靠这一步自动纠正；
 * 定位失败**不隐藏、不丢弃**，而是在侧栏标「定位可能已失效」——
 * 静默丢失用户的高亮是不可接受的。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  DocumentAdd,
  EditPen,
  MoreFilled,
  Search,
  WarningFilled,
} from '@element-plus/icons-vue'
// worker 用 `?url` 让 Vite 处理路径与指纹。
// ⚠️ 不设 workerSrc 的话，pdf.js 会退回主线程解析——大文件直接卡死界面。
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import { annotationsApi, documentsApi } from '@/api'
// 文本层必需样式（从 pdf_viewer.css 抽取并收窄）。
// 走 script 导入而不是 <style> 里的 @import：后者要求 @import 必须是首条规则，
// 在 SFC + postcss 组合下容易被提升错位而报错。
import '@/styles/pdfTextLayer.css'
import type { AnnotationRect, DocumentDetail, PdfAnnotation } from '@/api/types'
import {
  buildTextIndex,
  locateQuoteInLayer,
  pickQuote,
  rangeToNormalizedRects,
  selectionToNormOffsets,
  type TextIndex,
} from '@/utils/pdfAnchor'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const route = useRoute()
const router = useRouter()
const docId = String(route.params.id)

const COLORS = [
  { name: 'yellow', label: '黄', css: '#f2c94c' },
  { name: 'green', label: '绿', css: '#6fcf97' },
  { name: 'blue', label: '蓝', css: '#6fa8dc' },
  { name: 'pink', label: '粉', css: '#eb94b7' },
  { name: 'purple', label: '紫', css: '#a48fe0' },
]

const colorCss = (name: string) => COLORS.find((c) => c.name === name)?.css ?? COLORS[0].css

// ---------------- 状态 ----------------
const doc = ref<DocumentDetail | null>(null)
const pdf = shallowRef<PDFDocumentProxy | null>(null)
const numPages = ref(0)
const scale = ref(1)
const jumpPage = ref(1)
const loadError = ref('')
const scrollEl = ref<HTMLElement | null>(null)

const annotations = ref<PdfAnnotation[]>([])
const total = ref(0)
const keyword = ref('')
const activeId = ref('')
const flashId = ref('')
const exporting = ref(false)

/** 引文重定位结论：ok = 存档坐标可用；relocated = 已重算；lost = 找不到引文 */
const anchorStatus = reactive<Record<string, 'ok' | 'relocated' | 'lost'>>({})
const relocatedRects = reactive<Record<string, AnnotationRect[]>>({})

const pageEls = new Map<number, HTMLElement>()
const canvasEls = new Map<number, HTMLCanvasElement>()
const textEls = new Map<number, HTMLElement>()
const rendered = new Set<number>()
const renderTasks = new Map<number, RenderTask>()
const textIndexCache = new Map<number, TextIndex>()
/** 每页的旋转角。归一化坐标本身免疫旋转，存它只为排查问题与将来按方向渲染 */
const pageRotations = new Map<number, number>()
/** 未渲染页的占位尺寸，避免容器高度塌成 0 导致虚拟滚动判定失灵 */
const baseSize = ref({ w: 595, h: 842 })

let observer: IntersectionObserver | null = null
let destroyed = false

const placeholderStyle = computed(() => ({
  minWidth: `${Math.round(baseSize.value.w * scale.value)}px`,
  minHeight: `${Math.round(baseSize.value.h * scale.value)}px`,
}))

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const list = [...annotations.value].sort((a, b) => a.page_no - b.page_no)
  if (!kw) return list
  return list.filter(
    (a) => a.quote.toLowerCase().includes(kw) || (a.comment ?? '').toLowerCase().includes(kw),
  )
})

const annotationsOf = (page: number) => annotations.value.filter((a) => a.page_no === page)
const lostOn = (page: number) =>
  annotations.value.filter((a) => a.page_no === page && anchorStatus[a.id] === 'lost').length

/** 优先用重定位后的坐标（PDF 换版时它才是对的），否则用存档坐标 */
function displayRects(a: PdfAnnotation): AnnotationRect[] {
  return relocatedRects[a.id] ?? a.rects
}

function rectStyle(r: AnnotationRect) {
  return {
    left: `${r.x * 100}%`,
    top: `${r.y * 100}%`,
    width: `${r.w * 100}%`,
    height: `${r.h * 100}%`,
  }
}

// ---------------- 模板 ref 注册 ----------------
function setPageEl(page: number, el: unknown) {
  const node = el as HTMLElement | null
  if (node) {
    pageEls.set(page, node)
    void nextTick(() => observer?.observe(node))
  } else {
    pageEls.delete(page)
  }
}

function setCanvasEl(page: number, el: unknown) {
  const node = el as HTMLCanvasElement | null
  if (node) canvasEls.set(page, node)
  else canvasEls.delete(page)
}

function setTextEl(page: number, el: unknown) {
  const node = el as HTMLElement | null
  if (node) textEls.set(page, node)
  else textEls.delete(page)
}

function getTextIndex(page: number): TextIndex | null {
  const cached = textIndexCache.get(page)
  if (cached) return cached
  const el = textEls.get(page)
  if (!el) return null
  const index = buildTextIndex(el)
  textIndexCache.set(page, index)
  return index
}

// ---------------- 加载与渲染 ----------------
async function loadDocument() {
  try {
    doc.value = await documentsApi.get(docId)
  } catch {
    /* 拦截器已提示 */
  }

  try {
    pdf.value = await pdfjsLib.getDocument({
      url: annotationsApi.fileUrl(docId),
      // 中文 PDF 必须给 cMap：缺了它 getTextContent 返回 0 个文本项，
      // 文本层整个消失、无法划词。资源由 vite.config.ts 的 pdfjsAssets 提供。
      cMapUrl: '/pdfjs/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/',
    }).promise
  } catch (e) {
    loadError.value = `PDF 打开失败：${e instanceof Error ? e.message : String(e)}`
    return
  }
  if (destroyed) return

  numPages.value = pdf.value.numPages
  const first = await pdf.value.getPage(1)
  const vp = first.getViewport({ scale: 1 })
  baseSize.value = { w: vp.width, h: vp.height }

  await nextTick()
  setupObserver()
  await loadAnnotations()
}

function setupObserver() {
  observer?.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const page = Number((entry.target as HTMLElement).dataset.page)
        if (entry.isIntersecting) void renderPage(page)
      }
    },
    // 提前一屏渲染，滚动时不会出现空白页
    { root: scrollEl.value, rootMargin: '400px 0px' },
  )
  for (const el of pageEls.values()) observer.observe(el)
}

async function renderPage(page: number) {
  const pdfDoc = pdf.value
  const canvas = canvasEls.get(page)
  const pageEl = pageEls.get(page)
  const textEl = textEls.get(page)
  if (!pdfDoc || !canvas || !pageEl || !textEl || destroyed) return

  renderTasks.get(page)?.cancel()

  const pdfPage = await pdfDoc.getPage(page)
  if (destroyed) return
  const viewport = pdfPage.getViewport({ scale: scale.value })
  pageRotations.set(page, pdfPage.rotate || 0)
  const dpr = Math.min(window.devicePixelRatio || 1, 2)

  pageEl.style.width = `${Math.round(viewport.width)}px`
  pageEl.style.height = `${Math.round(viewport.height)}px`
  pageEl.style.minWidth = ''
  pageEl.style.minHeight = ''
  // pdf.js 的文本层样式用这个变量算字号，必须跟着缩放同步
  pageEl.style.setProperty('--scale-factor', String(scale.value))

  canvas.width = Math.floor(viewport.width * dpr)
  canvas.height = Math.floor(viewport.height * dpr)
  canvas.style.width = `${Math.floor(viewport.width)}px`
  canvas.style.height = `${Math.floor(viewport.height)}px`

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const task = pdfPage.render({
    canvasContext: ctx,
    viewport,
    // 按 devicePixelRatio 放大后必须把绘制也缩放，否则高分屏上是糊的
    transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
  })
  renderTasks.set(page, task)
  try {
    await task.promise
  } catch {
    return // 缩放时被新的渲染任务取消，属正常路径
  }
  if (destroyed) return

  // 文本层：重建后必须同时失效文本索引与定位结论
  const textContent = await pdfPage.getTextContent()
  textEl.innerHTML = ''
  const layer = new pdfjsLib.TextLayer({
    textContentSource: textContent,
    container: textEl,
    viewport,
  })
  await layer.render()
  if (destroyed) return

  rendered.add(page)
  textIndexCache.delete(page)
  verifyAnchorsOn(page)
}

/**
 * 用引文重新定位该页的批注，并纠正漂移的坐标。
 *
 * 这是「坐标失效」风险的兜底：PDF 换版本后页码可能不变但排版变了，
 * 存档坐标会整体偏移。以引文重新匹配得到的坐标才是当下正确的。
 */
function verifyAnchorsOn(page: number) {
  const textEl = textEls.get(page)
  const pageEl = pageEls.get(page)
  if (!textEl || !pageEl) return

  for (const a of annotations.value) {
    if (a.page_no !== page || anchorStatus[a.id]) continue
    const hit = locateQuoteInLayer(textEl, a)
    const rects = hit ? rangeToNormalizedRects(hit.range, pageEl) : []
    if (!rects.length) {
      // 找不到引文：保留存档坐标尽力显示，但明确告知可能不准
      anchorStatus[a.id] = 'lost'
      continue
    }
    if (driftOf(a.rects, rects) > 0.01) {
      relocatedRects[a.id] = rects
      anchorStatus[a.id] = 'relocated'
    } else {
      anchorStatus[a.id] = 'ok'
    }
  }
}

/** 存档坐标与重定位坐标的最大偏差（归一化尺度）。数量不一致视为完全漂移。 */
function driftOf(a: AnnotationRect[], b: AnnotationRect[]): number {
  if (a.length !== b.length) return 1
  let max = 0
  for (let i = 0; i < a.length; i++) {
    for (const k of ['x', 'y', 'w', 'h'] as const) {
      max = Math.max(max, Math.abs((a[i][k] ?? 0) - (b[i][k] ?? 0)))
    }
  }
  return max
}

async function loadAnnotations() {
  try {
    const res = await annotationsApi.list(docId)
    annotations.value = res.items
    total.value = res.total
  } catch {
    /* 拦截器已提示 */
  }
  await nextTick()
  // 已渲染的页补做一次重定位核验
  for (const page of rendered) verifyAnchorsOn(page)
}

// ---------------- 缩放与翻页 ----------------
async function applyScale(next: number) {
  scale.value = Math.min(3, Math.max(0.4, Number(next.toFixed(2))))
  rendered.clear()
  // 重定位结论与文本索引都建立在旧缩放的 DOM 上，必须一并失效
  for (const id of Object.keys(anchorStatus)) delete anchorStatus[id]
  for (const id of Object.keys(relocatedRects)) delete relocatedRects[id]
  textIndexCache.clear()

  await nextTick()
  const visible = [...pageEls.entries()]
    .filter(([, el]) => {
      const box = el.getBoundingClientRect()
      return box.bottom > -600 && box.top < window.innerHeight + 600
    })
    .map(([page]) => page)
  for (const page of visible.length ? visible : [1]) await renderPage(page)
}

const zoomBy = (delta: number) => void applyScale(scale.value + delta)
const resetZoom = () => void applyScale(1)

function onJump(value: number | undefined) {
  const page = Math.min(Math.max(Number(value) || 1, 1), numPages.value)
  jumpPage.value = page
  pageEls.get(page)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  void renderPage(page)
}

// ---------------- 划词 ----------------
interface PendingSelection {
  pageNo: number
  quote: string
  prefix: string | null
  suffix: string | null
  rects: AnnotationRect[]
  rotation: number
}

const pending = ref<PendingSelection | null>(null)
const toolbarPos = ref({ top: 0, left: 0 })
const toolbarStyle = computed(() => ({
  top: `${toolbarPos.value.top}px`,
  left: `${toolbarPos.value.left}px`,
}))

function onSelectionEnd() {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
    pending.value = null
    return
  }
  const range = sel.getRangeAt(0)
  const startNode = range.startContainer
  const startEl =
    startNode.nodeType === Node.TEXT_NODE
      ? (startNode.parentElement as HTMLElement | null)
      : (startNode as HTMLElement)
  const pageEl = startEl?.closest('.pdf-page') as HTMLElement | null
  if (!pageEl) {
    pending.value = null
    return
  }

  const pageNo = Number(pageEl.dataset.page)
  const textEl = textEls.get(pageNo)
  if (!textEl || !textEl.contains(range.commonAncestorContainer)) {
    pending.value = null
    return
  }

  const index = getTextIndex(pageNo)
  const offsets = index ? selectionToNormOffsets(index, range) : null
  if (!index || !offsets) {
    pending.value = null
    return
  }

  const { quote, prefix, suffix } = pickQuote(index.text, offsets.start, offsets.end)
  const rects = rangeToNormalizedRects(range, pageEl)
  if (!quote || !rects.length) {
    pending.value = null
    return
  }

  pending.value = {
    pageNo,
    quote,
    prefix,
    suffix,
    rects,
    rotation: pageRotations.get(pageNo) ?? 0,
  }

  const box = range.getBoundingClientRect()
  toolbarPos.value = {
    top: Math.max(8, box.top - 46),
    left: Math.min(Math.max(box.left + box.width / 2, 130), window.innerWidth - 130),
  }
}

function clearSelection() {
  window.getSelection()?.removeAllRanges()
  pending.value = null
}

async function createHighlight(color: string, comment?: string) {
  const payload = pending.value
  if (!payload) return
  try {
    const created = await annotationsApi.create(docId, {
      page_no: payload.pageNo,
      quote: payload.quote,
      rects: payload.rects,
      prefix: payload.prefix,
      suffix: payload.suffix,
      rotation: payload.rotation,
      color,
      comment: comment ?? null,
    })
    annotations.value = [...annotations.value, created]
    total.value += 1
    anchorStatus[created.id] = 'ok'
    clearSelection()
    flash(created.id)
  } catch {
    /* 拦截器已提示；重复提交的 409 也走这里 */
  }
}

const commentDialog = reactive({ visible: false, quote: '', text: '', saving: false, targetId: '' })

function openCommentDialog() {
  if (!pending.value) return
  commentDialog.quote = pending.value.quote
  commentDialog.text = ''
  commentDialog.targetId = ''
  commentDialog.visible = true
}

async function saveComment() {
  if (commentDialog.targetId) {
    commentDialog.saving = true
    try {
      const updated = await annotationsApi.update(commentDialog.targetId, {
        comment: commentDialog.text.trim() || null,
      })
      replaceAnnotation(updated)
      commentDialog.visible = false
    } finally {
      commentDialog.saving = false
    }
    return
  }

  commentDialog.saving = true
  try {
    await createHighlight('yellow', commentDialog.text.trim() || undefined)
    commentDialog.visible = false
  } finally {
    commentDialog.saving = false
  }
}

function replaceAnnotation(updated: PdfAnnotation) {
  annotations.value = annotations.value.map((a) => (a.id === updated.id ? updated : a))
}

// ---------------- 侧栏操作 ----------------
function focusAnnotation(a: PdfAnnotation) {
  activeId.value = a.id
  jumpPage.value = a.page_no
  void renderPage(a.page_no).then(() => {
    pageEls.get(a.page_no)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    flash(a.id)
  })
}

function flash(id: string) {
  flashId.value = id
  window.setTimeout(() => {
    if (flashId.value === id) flashId.value = ''
  }, 1400)
}

async function recolor(a: PdfAnnotation, color: string) {
  if (a.color === color) return
  try {
    replaceAnnotation(await annotationsApi.update(a.id, { color }))
  } catch {
    /* 拦截器已提示 */
  }
}

async function onItemCommand(command: string | number | object, a: PdfAnnotation) {
  const cmd = String(command)
  if (cmd === 'comment') {
    commentDialog.quote = a.quote
    commentDialog.text = a.comment ?? ''
    commentDialog.targetId = a.id
    commentDialog.visible = true
  } else if (cmd === 'copy') {
    await copyText(a.quote)
  } else if (cmd === 'cards') {
    await generateCards(a)
  } else if (cmd === 'remove') {
    await removeAnnotation(a)
  }
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制引文')
  } catch {
    ElMessage.warning('浏览器不允许写剪贴板')
  }
}

async function removeAnnotation(a: PdfAnnotation) {
  try {
    await ElMessageBox.confirm('删除这条批注？', '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await annotationsApi.remove(a.id)
    annotations.value = annotations.value.filter((x) => x.id !== a.id)
    total.value = Math.max(0, total.value - 1)
    delete anchorStatus[a.id]
    delete relocatedRects[a.id]
    ElMessage.success('已删除')
  } catch {
    /* 拦截器已提示 */
  }
}

const cardsDialog = reactive({
  visible: false,
  items: [] as { front: string; back: string }[],
})

async function generateCards(a: PdfAnnotation) {
  try {
    const res = await annotationsApi.cards(a.id, 3)
    cardsDialog.items = (res.cards ?? []).map((c) => ({ front: c.front, back: c.back }))
    cardsDialog.visible = true
  } catch {
    /* 拦截器已提示（AI 不可用时会给出明确原因） */
  }
}

const goLearning = () => router.push('/learning')

// ---------------- 导出 ----------------
async function exportNote() {
  exporting.value = true
  try {
    const res = await annotationsApi.exportNote(docId)
    ElMessage.success(
      res.created
        ? `已生成笔记《${res.title}》，共 ${res.annotation_count} 条批注`
        : `已更新笔记《${res.title}》，共 ${res.annotation_count} 条批注`,
    )
  } catch {
    /* 拦截器已提示 */
  } finally {
    exporting.value = false
  }
}

// ---------------- 生命周期 ----------------
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') pending.value = null
}

onMounted(async () => {
  document.addEventListener('mouseup', onSelectionEnd)
  document.addEventListener('keydown', onKeydown)
  await loadDocument()
})

onBeforeUnmount(() => {
  destroyed = true
  document.removeEventListener('mouseup', onSelectionEnd)
  document.removeEventListener('keydown', onKeydown)
  observer?.disconnect()
  observer = null
  // 不取消渲染任务的话，销毁后回调仍会往已卸载的 canvas 上画
  for (const task of renderTasks.values()) task.cancel()
  renderTasks.clear()
  void pdf.value?.destroy()
  pdf.value = null
})
</script>

<style scoped>
.kh-pdf {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

/* ===================== 顶栏 ===================== */
.pdf-top {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--kh-border);
  background: var(--kh-panel);
  flex-shrink: 0;
}

.pdf-back {
  flex-shrink: 0;
}

.pdf-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--kh-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.pdf-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.pdf-pager {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pdf-pager-input {
  width: 92px;
}

.pdf-muted {
  font-size: 12px;
  color: var(--kh-text-mute);
  white-space: nowrap;
}

/* ===================== 主体 ===================== */
.pdf-main {
  flex: 1;
  display: flex;
  min-height: 0;
}

.pdf-scroll {
  flex: 1;
  overflow: auto;
  padding: 20px 24px 60px;
  background: var(--kh-bg-deep);
  scroll-behavior: smooth;
}

.pdf-slot {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 22px;
}

.pdf-page {
  position: relative;
  background: #fff;
  box-shadow: 0 1px 6px rgb(0 0 0 / 0.16);
  /* 旋转页的坐标由 pdf.js 烘焙进布局，这里不能加任何 transform */
}

.pdf-page canvas {
  display: block;
}

.pdf-page-no {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--kh-text-mute);
  font-variant-numeric: tabular-nums;
}

.pdf-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  color: var(--kh-text-sub);
}

/* ===================== 高亮层 ===================== */
.kh-hl {
  position: absolute;
  inset: 0;
  /* 夹在画布与文本层之间。pointer-events:none 是关键：
     高亮若拦截鼠标，被高亮覆盖的文字就再也划不中了 */
  z-index: 1;
  pointer-events: none;
}

.kh-hl-rect {
  position: absolute;
  border-radius: 2px;
  /* multiply 让高亮像荧光笔一样透出底下的字，而不是盖住 */
  mix-blend-mode: multiply;
  transition: box-shadow 0.2s;
}

.kh-hl-rect.is-yellow {
  background: rgb(242 201 76 / 0.5);
}
.kh-hl-rect.is-green {
  background: rgb(111 207 151 / 0.5);
}
.kh-hl-rect.is-blue {
  background: rgb(111 168 220 / 0.5);
}
.kh-hl-rect.is-pink {
  background: rgb(235 148 183 / 0.5);
}
.kh-hl-rect.is-purple {
  background: rgb(164 143 224 / 0.5);
}

.kh-hl-rect.is-flash {
  animation: kh-hl-flash 1.4s ease-out 2;
}

@keyframes kh-hl-flash {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgb(64 158 255 / 0);
  }
  50% {
    box-shadow: 0 0 0 3px rgb(64 158 255 / 0.85);
  }
}

.kh-hl-lost {
  position: absolute;
  left: 8px;
  bottom: 8px;
  z-index: 3;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgb(253 248 239 / 0.95);
  border: 1px solid #e8d5b0;
  color: #8a5f1a;
  font-size: 11px;
  pointer-events: none;
}

/* ===================== 侧栏 ===================== */
.pdf-side {
  width: 320px;
  flex-shrink: 0;
  border-left: 1px solid var(--kh-border);
  background: var(--kh-panel);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.side-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 12px 14px 8px;
}

.side-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--kh-text);
}

.side-count {
  font-size: 12px;
  color: var(--kh-text-mute);
}

.side-search {
  padding: 0 14px;
}

.side-hint {
  margin: 10px 14px 4px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--kh-bg-deep);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--kh-text-sub);
}

.side-empty {
  padding: 24px 14px;
  text-align: center;
  font-size: 12.5px;
  color: var(--kh-text-mute);
}

.side-item {
  margin: 6px 10px;
  padding: 9px 10px;
  border: 1px solid var(--kh-border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.side-item:hover {
  border-color: var(--kh-primary);
}

.side-item.is-active {
  border-color: var(--kh-primary);
  background: var(--kh-primary-soft);
}

.side-item-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
}

.side-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.side-page {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  font-variant-numeric: tabular-nums;
}

.side-spacer {
  flex: 1;
}

.side-flag {
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 4px;
  white-space: nowrap;
}

.side-flag.is-warn {
  background: #fdf8ef;
  border: 1px solid #e8d5b0;
  color: #8a5f1a;
}

.side-flag.is-lost {
  background: #fdeeee;
  border: 1px solid #e8b0b0;
  color: #8a1a1a;
}

.side-more {
  color: var(--kh-text-mute);
  cursor: pointer;
}

.side-more:hover {
  color: var(--kh-primary);
}

.side-quote {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--kh-text);
  /* 引文可能很长，限制行数避免侧栏被一条占满 */
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.side-comment {
  margin-top: 5px;
  padding-left: 8px;
  border-left: 2px solid var(--kh-border);
  font-size: 12px;
  line-height: 1.6;
  color: var(--kh-text-sub);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.side-colors {
  display: flex;
  gap: 5px;
  margin-top: 8px;
}

.side-color {
  width: 15px;
  height: 15px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  padding: 0;
  transition: border-color 0.15s;
}

.side-color.is-on {
  border-color: var(--kh-text);
}

/* ===================== 划词工具条 ===================== */
.kh-sel-toolbar {
  position: fixed;
  z-index: 3000;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 8px;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  box-shadow: 0 4px 16px rgb(0 0 0 / 0.16);
  transform: translateX(-50%);
}

.sel-color {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid rgb(0 0 0 / 0.12);
  cursor: pointer;
  padding: 0;
  transition: transform 0.12s;
}

.sel-color:hover {
  transform: scale(1.18);
}

.sel-divider {
  width: 1px;
  height: 18px;
  background: var(--kh-border);
  margin: 0 2px;
}

.sel-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--kh-text);
  padding: 2px 4px;
}

.sel-btn:hover {
  color: var(--kh-primary);
}

/* ===================== 对话框 ===================== */
.cmt-quote {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--kh-bg-deep);
  border-left: 3px solid var(--kh-primary);
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--kh-text-sub);
  max-height: 160px;
  overflow: auto;
}

.card-row {
  padding: 9px 0;
  border-bottom: 1px solid var(--kh-border-light);
}

.card-front {
  font-size: 13px;
  font-weight: 600;
  color: var(--kh-text);
}

.card-back {
  margin-top: 4px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--kh-text-sub);
}

/* ===================== 窄屏 ===================== */
@media (max-width: 900px) {
  .pdf-main {
    flex-direction: column;
  }

  .pdf-side {
    width: auto;
    max-height: 42vh;
    border-left: none;
    border-top: 1px solid var(--kh-border);
  }

  .pdf-top {
    flex-wrap: wrap;
    gap: 8px;
  }

  .pdf-title {
    order: -1;
    flex-basis: 100%;
  }
}
</style>
