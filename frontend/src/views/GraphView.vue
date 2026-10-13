<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">知识图谱</h1>
        <p class="page-sub">
          笔记之间的关系网络：实线是 <b>双向链接</b>，虚线是<b>共享标签</b>。点节点可打开笔记
        </p>
      </div>
      <div class="page-actions">
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>
    </div>

    <div class="card">
      <div class="row">
        <el-switch
          v-model="includeTags"
          active-text="包含共享标签连线"
          @change="load"
        />
        <el-switch
          v-model="hideIsolated"
          active-text="隐藏孤立节点"
          @change="applyFilter"
        />
        <el-select
          v-model="categoryFilter"
          placeholder="全部分类"
          clearable
          style="width: 170px"
          @change="applyFilter"
        >
          <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button size="small" @click="restart">
          <el-icon><Refresh /></el-icon>
          <span>重新布局</span>
        </el-button>
        <el-button size="small" title="清除已保存的节点位置并重新排布" @click="resetLayout">
          重置布局
        </el-button>
        <el-button v-if="focusId" size="small" @click="clearFocus">
          取消聚焦
        </el-button>
        <span class="muted">
          显示 {{ visibleCount }} / {{ stats?.node_count ?? 0 }} 节点 ·
          连线 {{ stats?.edge_count ?? 0 }}
          （链接 {{ stats?.link_edges ?? 0 }} / 标签 {{ stats?.tag_edges ?? 0 }}）
          · 孤立 {{ stats?.isolated ?? 0 }}
        </span>
      </div>

      <div class="graph-wrap">
        <canvas
          ref="canvasEl"
          class="graph-canvas"
          @mousedown="onDown"
          @mousemove="onMove"
          @mouseup="onUp"
          @mouseleave="onUp"
          @wheel.prevent="onWheel"
          @dblclick="onDblClick"
        />
        <div v-if="!loading && !(data?.nodes.length ?? 0)" class="graph-empty">
          <el-icon><Share /></el-icon>
          <div>还没有可展示的关系</div>
          <div class="hint">
            在笔记正文里写 <code>[[另一篇笔记标题]]</code> 即可建立双向链接；
            也可以打开「包含共享标签连线」看主题相近的笔记。
          </div>
        </div>
        <div v-if="tip" class="graph-tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
          <div class="tip-title">{{ tip.title }}</div>
          <div class="tip-meta">
            {{ tip.category || '未分类' }} · {{ tip.chunk }} 片段 · {{ tip.degree }} 条连线
            <span v-if="!tip.aiEnabled"> · 私密</span>
          </div>
          <div class="tip-hint">单击打开 · 拖拽移动 · 滚轮缩放</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { graphApi } from '@/api'
import type { GraphNode, GraphOut } from '@/api/types'

const route = useRoute()
const router = useRouter()

const canvasEl = ref<HTMLCanvasElement | null>(null)
const data = ref<GraphOut | null>(null)
const loading = ref(false)
const includeTags = ref(false)
const focusId = ref<string | null>(null)

// ---- 筛选 ----
const hideIsolated = ref(false)
const categoryFilter = ref<string | null>(null)
/** 通过筛选后实际绘制的节点数 */
const visibleCount = ref(0)

/** 分类选项（从当前节点去重，忽略未分类）。 */
const categoryOptions = computed(() => {
  const names = (data.value?.nodes ?? [])
    .map((n) => n.category_name)
    .filter((v): v is string => Boolean(v))
  return Array.from(new Set(names)).sort()
})

/** 应用筛选：重新基于当前筛选条件构建布局。 */
function applyFilter() {
  buildSim()
}

const stats = ref<GraphOut['stats'] | null>(null)

/** 提示气泡（悬停节点时显示） */
const tip = ref<{ x: number; y: number; title: string; category: string; chunk: number; degree: number; aiEnabled: boolean } | null>(null)

interface Sim {
  node: GraphNode
  x: number
  y: number
  vx: number
  vy: number
  r: number
  color: string
}

interface SimLink {
  a: Sim
  b: Sim
  kind: 'link' | 'tag'
  weight: number
}

let sims: Sim[] = []
let links: SimLink[] = []
let raf = 0
let alpha = 1
let hover: Sim | null = null
let dragging: Sim | null = null
let scale = 1
let offsetX = 0
let offsetY = 0
let dragMoved = false
let downAt = { x: 0, y: 0 }
/** 本轮布局是否已保存（避免每帧写 localStorage） */
let layoutSaved = false

/** 调色板：按分类哈希取色，同一分类颜色一致。 */
const PALETTE = [
  '#4a5fd6', '#2f9e6e', '#c98a1f', '#cf5b56', '#8b5cf6',
  '#0ea5e9', '#db2777', '#65a30d', '#f97316', '#14b8a6',
]

function colorOf(node: GraphNode): string {
  const key = node.category_name || node.source || ''
  let hash = 0
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) % 997
  return PALETTE[hash % PALETTE.length]
}

async function load() {
  loading.value = true
  try {
    data.value = await graphApi.get({
      focus_id: focusId.value,
      include_tags: includeTags.value,
      limit: 300,
    })
    stats.value = data.value.stats
    buildSim()
  } catch {
    data.value = null
  } finally {
    loading.value = false
  }
}

// ---------------- 布局持久化 ----------------
// 每次进入页面都重新力导向会让节点「乱跳」。把稳定后的位置存到 localStorage，
// 下次进入直接复用（签名变化 = 节点集合变了，才重新布局）。
const LAYOUT_KEY_PREFIX = 'kh-graph-layout-'

/** 用节点 id 集合生成签名：节点增删改时布局自动失效。 */
function layoutKey(ids: string[]): string {
  const sorted = [...ids].sort().join(',')
  let hash = 0
  for (let i = 0; i < sorted.length; i++) {
    hash = (hash * 31 + sorted.charCodeAt(i)) | 0
  }
  return LAYOUT_KEY_PREFIX + (hash >>> 0).toString(36)
}

function saveLayout() {
  try {
    const key = layoutKey(sims.map((s) => s.node.id))
    const payload = Object.fromEntries(sims.map((s) => [s.node.id, [s.x, s.y]]))
    localStorage.setItem(key, JSON.stringify(payload))
  } catch {
    /* 隐私模式下不可用，忽略 */
  }
}

/** 返回节点 id → [x, y] 的已保存位置；无则空对象。 */
function loadLayout(): Record<string, [number, number]> {
  try {
    const key = layoutKey(sims.map((s) => s.node.id))
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

/** 清除已保存布局并重新排布。 */
function resetLayout() {
  try {
    localStorage.removeItem(layoutKey(sims.map((s) => s.node.id)))
  } catch {
    /* 忽略 */
  }
  restart()
}

function canvasSize() {
  const el = canvasEl.value
  if (!el) return { w: 800, h: 520 }
  const rect = el.getBoundingClientRect()
  return { w: Math.max(320, rect.width), h: Math.max(320, rect.height) }
}

function buildSim() {
  const g = data.value
  const el = canvasEl.value
  if (!g || !el) return

  const { w, h } = canvasSize()
  const dpr = window.devicePixelRatio || 1
  el.width = w * dpr
  el.height = h * dpr
  const ctx = el.getContext('2d')
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  // ---- 筛选：只保留通过筛选条件的节点 ----
  const visible = g.nodes.filter((n) => {
    if (hideIsolated.value && n.degree === 0) return false
    if (categoryFilter.value && n.category_name !== categoryFilter.value) return false
    return true
  })
  const maxDeg = Math.max(1, ...visible.map((n) => n.degree))
  visibleCount.value = visible.length

  // 恢复上次保存的位置（有则用，没有则圆形分布）
  const saved = loadLayout()

  // 初始按圆形分布，避免全部堆在中心导致斥力爆炸
  sims = visible.map((node, i) => {
    const angle = (i / Math.max(1, visible.length)) * Math.PI * 2
    const radius = Math.min(w, h) * 0.32
    const pos = saved[node.id]
    return {
      node,
      x: pos ? pos[0] : w / 2 + Math.cos(angle) * radius,
      y: pos ? pos[1] : h / 2 + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      r: 4 + (node.degree / maxDeg) * 12,
      color: colorOf(node),
    }
  })

  const byId = new Map(sims.map((s) => [s.node.id, s]))
  links = g.edges
    .map((e) => ({
      a: byId.get(e.source),
      b: byId.get(e.target),
      kind: e.kind,
      weight: e.weight || 1,
    }))
    .filter((l): l is SimLink => Boolean(l.a && l.b))

  // 有已保存布局时不再大力重排（alpha 设低），避免节点「乱跳」
  const hasSaved = Object.keys(saved).length > 0
  scale = 1
  offsetX = 0
  offsetY = 0
  alpha = hasSaved ? 0.15 : 1
  layoutSaved = false
  startLoop()
}

/** 一次力迭代：斥力 + 弹簧 + 向心。 */
function step() {
  const { w, h } = canvasSize()
  const cx = w / 2
  const cy = h / 2
  const repulsion = 2200

  for (let i = 0; i < sims.length; i++) {
    const a = sims[i]
    for (let j = i + 1; j < sims.length; j++) {
      const b = sims[j]
      let dx = b.x - a.x
      let dy = b.y - a.y
      let d2 = dx * dx + dy * dy
      if (d2 < 1) {
        // 完全重合时给一个随机微扰，避免除零
        dx = Math.random() - 0.5
        dy = Math.random() - 0.5
        d2 = 1
      }
      const d = Math.sqrt(d2)
      const f = (repulsion / d2) * alpha
      const fx = (dx / d) * f
      const fy = (dy / d) * f
      a.vx -= fx
      a.vy -= fy
      b.vx += fx
      b.vy += fy
    }
  }

  for (const l of links) {
    const dx = l.b.x - l.a.x
    const dy = l.b.y - l.a.y
    const d = Math.max(1, Math.sqrt(dx * dx + dy * dy))
    const rest = l.kind === 'link' ? 95 : 140
    const strength = (l.kind === 'link' ? 0.035 : 0.012) * Math.min(3, l.weight)
    const f = (d - rest) * strength * alpha
    const fx = (dx / d) * f
    const fy = (dy / d) * f
    l.a.vx += fx
    l.a.vy += fy
    l.b.vx -= fx
    l.b.vy -= fy
  }

  for (const s of sims) {
    s.vx += (cx - s.x) * 0.006 * alpha
    s.vy += (cy - s.y) * 0.006 * alpha
    s.vx *= 0.86
    s.vy *= 0.86
    s.x += s.vx
    s.y += s.vy
  }

  alpha *= 0.985
}

function draw() {
  const el = canvasEl.value
  const ctx = el?.getContext('2d')
  if (!el || !ctx) return
  const { w, h } = canvasSize()

  ctx.clearRect(0, 0, w, h)
  ctx.save()
  ctx.translate(offsetX, offsetY)
  ctx.scale(scale, scale)

  // 边
  for (const l of links) {
    const dim = hover && hover !== l.a && hover !== l.b
    ctx.beginPath()
    ctx.setLineDash(l.kind === 'link' ? [] : [4, 4])
    ctx.lineWidth = (l.kind === 'link' ? 1.2 : 0.8) / scale
    ctx.strokeStyle = dim
      ? 'rgba(150,150,160,0.12)'
      : l.kind === 'link'
        ? 'rgba(90,110,220,0.55)'
        : 'rgba(150,150,160,0.35)'
    ctx.moveTo(l.a.x, l.a.y)
    ctx.lineTo(l.b.x, l.b.y)
    ctx.stroke()
  }
  ctx.setLineDash([])

  // 节点
  for (const s of sims) {
    const isHover = hover === s
    ctx.beginPath()
    ctx.arc(s.x, s.y, s.r / scale, 0, Math.PI * 2)
    ctx.fillStyle = s.node.ai_enabled ? s.color : 'rgba(140,140,150,0.65)'
    ctx.globalAlpha = hover && !isHover ? 0.35 : 1
    ctx.fill()
    if (isHover) {
      ctx.lineWidth = 2 / scale
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
    }
    ctx.globalAlpha = 1
  }

  // 标签：只画度数较高的节点，避免糊成一片
  ctx.font = `${12 / scale}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  for (const s of sims) {
    if (s.node.degree < 1 && sims.length > 60) continue
    ctx.fillStyle = 'rgba(120,128,140,0.95)'
    const label = s.node.title.length > 14 ? s.node.title.slice(0, 14) + '…' : s.node.title
    ctx.fillText(label, s.x, s.y + s.r / scale + 3)
  }

  ctx.restore()
}

function loop() {
  if (alpha > 0.02) {
    step()
    layoutSaved = false
  } else if (!layoutSaved && sims.length) {
    // 布局稳定后保存一次（避免每帧都写 localStorage）
    saveLayout()
    layoutSaved = true
  }
  draw()
  raf = requestAnimationFrame(loop)
}

function startLoop() {
  if (raf) cancelAnimationFrame(raf)
  raf = requestAnimationFrame(loop)
}

function restart() {
  alpha = 1
  buildSim()
}

function clearFocus() {
  focusId.value = null
  load()
}

// ---------------- 交互 ----------------
function toWorld(e: MouseEvent) {
  const el = canvasEl.value
  if (!el) return { x: 0, y: 0 }
  const rect = el.getBoundingClientRect()
  const sx = e.clientX - rect.left
  const sy = e.clientY - rect.top
  return { x: (sx - offsetX) / scale, y: (sy - offsetY) / scale }
}

function pick(x: number, y: number): Sim | null {
  for (let i = sims.length - 1; i >= 0; i--) {
    const s = sims[i]
    const dx = s.x - x
    const dy = s.y - y
    const r = s.r / scale + 6
    if (dx * dx + dy * dy <= r * r) return s
  }
  return null
}

function onDown(e: MouseEvent) {
  const p = toWorld(e)
  downAt = { x: e.clientX, y: e.clientY }
  dragMoved = false
  const hit = pick(p.x, p.y)
  if (hit) {
    dragging = hit
    alpha = Math.max(alpha, 0.35)
    startLoop()
  }
}

function onMove(e: MouseEvent) {
  const p = toWorld(e)
  if (dragging) {
    dragMoved = true
    dragging.x = p.x
    dragging.y = p.y
    dragging.vx = 0
    dragging.vy = 0
    return
  }
  const hit = pick(p.x, p.y)
  hover = hit
  if (hit) {
    const el = canvasEl.value
    const rect = el?.getBoundingClientRect()
    tip.value = {
      x: (e.clientX - (rect?.left ?? 0)) + 14,
      y: (e.clientY - (rect?.top ?? 0)) + 10,
      title: hit.node.title,
      category: hit.node.category_name || '',
      chunk: hit.node.chunk_count,
      degree: hit.node.degree,
      aiEnabled: hit.node.ai_enabled,
    }
    canvasEl.value!.style.cursor = 'pointer'
  } else {
    tip.value = null
    if (canvasEl.value) canvasEl.value.style.cursor = 'default'
  }
}

function onUp(e: MouseEvent) {
  const moved = Math.abs(e.clientX - downAt.x) + Math.abs(e.clientY - downAt.y) > 4
  if (dragging && !moved && !dragMoved) {
    openNode(dragging.node)
  }
  if (dragging) saveLayout() // 拖拽结束立即保存位置
  dragging = null
}

function onDblClick(e: MouseEvent) {
  const p = toWorld(e)
  const hit = pick(p.x, p.y)
  if (hit) {
    focusId.value = hit.node.id
    load()
    ElMessage.success(`已聚焦到《${hit.node.title}》的二度关系`)
  }
}

function onWheel(e: WheelEvent) {
  const el = canvasEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const sx = e.clientX - rect.left
  const sy = e.clientY - rect.top
  const before = (sx - offsetX) / scale
  const beforeY = (sy - offsetY) / scale
  const next = Math.min(3, Math.max(0.3, scale * (e.deltaY > 0 ? 0.9 : 1.1)))
  scale = next
  offsetX = sx - before * scale
  offsetY = sy - beforeY * scale
}

function openNode(node: GraphNode) {
  if (node.source === 'note') router.push(`/notes/${node.id}/edit`)
  else router.push(`/documents/${node.id}`)
}

onMounted(() => {
  const q = route.query.focus
  if (q) focusId.value = String(q)
  const tags = route.query.tags
  if (tags === '1') includeTags.value = true
  load()
})

onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
})
</script>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.muted {
  font-size: 12px;
  color: var(--kh-text-sub);
}
.graph-wrap {
  position: relative;
  width: 100%;
  height: 620px;
  border: 1px solid var(--kh-border-light);
  border-radius: var(--kh-radius);
  background: var(--kh-bg);
  overflow: hidden;
}
.graph-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
.graph-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--kh-text-mute);
  font-size: 13px;
  text-align: center;
  padding: 0 40px;
}
.graph-empty .el-icon {
  font-size: 30px;
}
.graph-empty .hint {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--kh-text-mute);
}
.graph-empty code {
  background: var(--kh-bg-deep);
  border-radius: 4px;
  padding: 1px 5px;
}
.graph-tip {
  position: absolute;
  pointer-events: none;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: 8px;
  box-shadow: var(--kh-shadow);
  padding: 8px 10px;
  max-width: 260px;
  z-index: 5;
}
.tip-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--kh-text);
}
.tip-meta {
  font-size: 11.5px;
  color: var(--kh-text-sub);
  margin-top: 2px;
}
.tip-hint {
  font-size: 11px;
  color: var(--kh-text-mute);
  margin-top: 4px;
}
</style>
