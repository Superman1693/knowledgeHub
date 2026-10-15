/**
 * PDF 批注锚定：坐标归一化、引文抓取与重定位。
 *
 * ## 坐标系契约（全项目唯一口径）
 *
 * 所有矩形都**归一化到页面可视区（CropBox 旋转后的外接框）的左上角**，
 * x 向右、y 向下，取值 0..1，与 Canvas / CSS 一致。
 *
 * 三个刻意的选择：
 *
 * 1. **用「视觉坐标」而不是 PDF 用户坐标**。PDF 用户坐标是 y 向上的，
 *    且随页面 rotation 变化，换算要过 `Util.transform` 的仿射矩阵——
 *    旋转页的矩阵形如 `[0,1,1,0,...]`，缩放因子在 `b/c` 而不是 `a/d`，
 *    只按 `a/d` 缩放会让宽高全部变成 0（阶段 0 实测踩到过）。
 *    而「DOM 矩形 ÷ 页面框」这条路径**天然免疫旋转与缩放**：
 *    浏览器已经把旋转烘焙进了布局，我们只做一次线性归一化。
 * 2. **归一化分母是渲染后的页面元素尺寸**，所以结果与 `devicePixelRatio`、
 *    缩放级别、缩放方向都无关（阶段 0 验证：0.5/1/2 三档偏差为 0）。
 * 3. **引文是主锚，坐标是辅助**。坐标只负责「画在哪」；
 *    当 PDF 被换成同内容的新版本、坐标整体失效时，靠 `quote` 重新定位。
 */

export interface NormRect {
  x: number
  y: number
  w: number
  h: number
}

/** 一条批注的锚点信息（与后端 `pdf_annotations` 表字段一一对应）。 */
export interface PdfAnchor {
  page_no: number
  quote: string
  prefix: string | null
  suffix: string | null
  rects: NormRect[]
  rotation: number
}

/** 引文前后各保留多少字符用于消歧。 */
export const QUOTE_CONTEXT = 32

/** 小于这个像素尺寸的矩形视为噪声（拖选时常见 0 宽/0 高的碎片）。 */
const MIN_RECT_PX = 1

/** 同一行内、水平间距小于「行高 × 该系数」的矩形合并（空格宽度远小于行高）。 */
const SAME_LINE_GAP_FACTOR = 0.6

/** 判定两个矩形在同一行：纵向重叠比例超过该阈值。 */
const SAME_LINE_OVERLAP = 0.5

interface Box {
  left: number
  top: number
  width: number
  height: number
}

/**
 * DOM 矩形 → 归一化矩形。
 *
 * @param rects 选区的 `Range.getClientRects()`（或任意视口坐标矩形）
 * @param page  页面容器的 `getBoundingClientRect()`
 */
export function normalizeRects(rects: Box[], page: Box): NormRect[] {
  if (!page.width || !page.height) return []

  const out: NormRect[] = []
  for (const r of rects) {
    // 1) 裁到页面框内：选区可能拖到页外，或跨页选择（跨页的那部分不属于本页）
    const left = Math.max(r.left, page.left)
    const top = Math.max(r.top, page.top)
    const right = Math.min(r.left + r.width, page.left + page.width)
    const bottom = Math.min(r.top + r.height, page.top + page.height)
    const w = right - left
    const h = bottom - top
    if (w < MIN_RECT_PX || h < MIN_RECT_PX) continue

    out.push({
      x: (left - page.left) / page.width,
      y: (top - page.top) / page.height,
      w: w / page.width,
      h: h / page.height,
    })
  }
  return mergeLineRects(out)
}

/** 归一化矩形 → 页面框内的像素矩形（导出/测试用；渲染时直接用 CSS 百分比）。 */
export function denormalizeRects(rects: NormRect[], page: Box): Box[] {
  return rects.map((r) => ({
    left: page.left + r.x * page.width,
    top: page.top + r.y * page.height,
    width: r.w * page.width,
    height: r.h * page.height,
  }))
}

/**
 * 合并同一行内相邻的矩形。
 *
 * PDF.js 的文本层把一行拆成多个 `<span>`（每个文本项一个），
 * 选区因此会拿到一堆小矩形；不合并的话高亮看起来像断续的碎片。
 * 只在**同一行内且间距很小**时合并，跨栏的大间距不会被合进来。
 */
export function mergeLineRects(rects: NormRect[]): NormRect[] {
  if (rects.length < 2) return [...rects]

  const sorted = [...rects].sort((a, b) => (Math.abs(a.y - b.y) < 1e-9 ? a.x - b.x : a.y - b.y))
  const lines: NormRect[][] = []

  for (const r of sorted) {
    const line = lines[lines.length - 1]
    const last = line?.[line.length - 1]
    if (last && sameLine(last, r)) {
      line.push(r)
      continue
    }
    lines.push([r])
  }

  return lines.map((line) => {
    const merged: NormRect[] = []
    for (const r of line) {
      const prev = merged[merged.length - 1]
      if (prev && r.x - (prev.x + prev.w) <= SAME_LINE_GAP_FACTOR * Math.max(prev.h, r.h)) {
        const right = Math.max(prev.x + prev.w, r.x + r.w)
        const bottom = Math.max(prev.y + prev.h, r.y + r.h)
        prev.x = Math.min(prev.x, r.x)
        prev.y = Math.min(prev.y, r.y)
        prev.w = right - prev.x
        prev.h = bottom - prev.y
      } else {
        merged.push({ ...r })
      }
    }
    return merged
  }).flat()
}

function sameLine(a: NormRect, b: NormRect): boolean {
  const overlap = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)
  return overlap > SAME_LINE_OVERLAP * Math.min(a.h, b.h)
}

/** 选区 → 归一化矩形（生产路径：捕获高亮时的入口）。 */
export function rangeToNormalizedRects(range: Range, pageEl: HTMLElement): NormRect[] {
  const page = pageEl.getBoundingClientRect()
  const rects: Box[] = []
  const list = range.getClientRects()
  for (let i = 0; i < list.length; i++) {
    const r = list[i]
    rects.push({ left: r.left, top: r.top, width: r.width, height: r.height })
  }
  return normalizeRects(rects, page)
}

// ---------------------------------------------------------------------------
// 引文：抓取与归一化
// ---------------------------------------------------------------------------

/**
 * 引文文本归一化。**存与查必须走同一个函数**，否则会两边不一致。
 *
 * - 去掉软连字符（U+00AD）：PDF 里断词常插入它，肉眼不可见但会让匹配失败
 * - 去掉**行尾**硬连字符：`state-of-\nthe-art` → `state-ofthe-art`
 *   只在连字符后跟空白时剥离，所以 `e-mail` 这类词内连字符不受影响
 * - 折叠所有空白为单个空格
 */
export function normalizeQuoteText(s: string | null | undefined): string {
  return (s ?? '')
    .replace(/\u00ad/g, '')
    .replace(/-\s+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 从页面文本里截取引文，以及前后用于消歧的上下文。 */
export function pickQuote(
  pageText: string,
  start: number,
  end: number,
  ctx: number = QUOTE_CONTEXT,
): { quote: string; prefix: string | null; suffix: string | null } {
  const quote = normalizeQuoteText(pageText.slice(start, end))
  const before = normalizeQuoteText(pageText.slice(Math.max(0, start - ctx * 2), start))
  const after = normalizeQuoteText(pageText.slice(end, end + ctx * 2))
  return {
    quote,
    prefix: before ? before.slice(-ctx) : null,
    suffix: after ? after.slice(0, ctx) : null,
  }
}

// ---------------------------------------------------------------------------
// 文本层索引：DOM 文本节点 ↔ 归一化字符串坐标
// ---------------------------------------------------------------------------

interface NodeRecord {
  node: Text
  /** 该节点在归一化串中的起始下标（含） */
  start: number
  /** 该节点在归一化串中的结束下标（不含） */
  end: number
  /** `src[i]` = 归一化串中第 `start + i` 个字符在 `node.data` 里的原始下标 */
  src: number[]
}

export interface TextIndex {
  /** 该页文本层所有文本按 DOM 顺序拼接、并归一化后的结果 */
  text: string
  records: NodeRecord[]
}

/**
 * 归一化单段文本，同时给出「归一化字符 → 原始下标」的映射。
 *
 * 之所以要映射：前端拿到的选区边界是**原始**文本偏移，
 * 而跨节点搜索必须在**归一化**串上做，两者必须能互相换算。
 */
function normalizeWithSource(src: string): { text: string; map: number[] } {
  let text = ''
  const map: number[] = []
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (ch === '\u00ad') {
      i++
      continue
    }
    if (ch === '-') {
      // 行尾硬连字符：后面只跟空白时整体丢弃
      let j = i + 1
      while (j < src.length && /\s/.test(src[j])) j++
      if (j > i + 1 && j < src.length) {
        i = j
        continue
      }
    }
    if (/\s/.test(ch)) {
      // 折叠连续空白为单个空格
      let j = i
      while (j < src.length && /\s/.test(src[j])) j++
      text += ' '
      map.push(i)
      i = j
      continue
    }
    text += ch
    map.push(i)
    i++
  }
  return { text, map }
}

/** 按 DOM 顺序收集页面文本层里的文本节点，构建索引。 */
export function buildTextIndex(root: HTMLElement): TextIndex {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const records: NodeRecord[] = []
  let text = ''
  let n: Node | null = walker.nextNode()
  while (n) {
    const node = n as Text
    const data = node.data
    if (data) {
      const { text: ntext, map } = normalizeWithSource(data)
      if (ntext) {
        records.push({ node, start: text.length, end: text.length + ntext.length, src: map })
        text += ntext
      }
    }
    n = walker.nextNode()
  }
  return { text, records }
}

/**
 * 原始「节点 + 节点内偏移」→ 归一化串下标。
 *
 * 语义是「该偏移之前有多少个归一化字符」，所以取**第一个 `src[i] >= offset`**
 * 的下标（字符计数），而不是「最后一个 <= offset」——
 * 后者在 `offset == 节点文本长度` 时会少算 1，表现为选区末尾少一个字符。
 */
function rawToNorm(index: TextIndex, node: Node, offset: number): number | null {
  for (const rec of index.records) {
    if (rec.node !== node) continue
    // src 单调不减，二分找第一个 >= offset 的位置
    let lo = 0
    let hi = rec.src.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (rec.src[mid] < offset) lo = mid + 1
      else hi = mid
    }
    return rec.start + lo
  }
  return null
}

/** 归一化串下标 → 「节点 + 节点内原始偏移」，供创建 Range 用。 */
function normToRaw(index: TextIndex, norm: number, preferEnd = false): { node: Text; offset: number } | null {
  for (const rec of index.records) {
    if (norm < rec.start || norm > rec.end) continue
    const local = norm - rec.start
    if (local >= rec.src.length) {
      // 落在节点末尾：等价于「节点原始文本的末尾」
      if (norm <= rec.end && preferEnd) return { node: rec.node, offset: rec.node.data.length }
      continue
    }
    return { node: rec.node, offset: rec.src[local] }
  }
  // 落在整体末尾
  const last = index.records[index.records.length - 1]
  return last ? { node: last.node, offset: last.node.data.length } : null
}

/** 选区 → 归一化串上的 [start, end)。 */
export function selectionToNormOffsets(
  index: TextIndex,
  range: Range,
): { start: number; end: number } | null {
  const start = rawToNorm(index, range.startContainer, range.startOffset)
  const end = rawToNorm(index, range.endContainer, range.endOffset)
  if (start === null || end === null) return null
  if (end <= start) return null
  return { start, end }
}

// ---------------------------------------------------------------------------
// 引文重定位：PDF 换版后靠它找回位置
// ---------------------------------------------------------------------------

export interface LocateResult {
  start: number
  end: number
  /** 命中方式：exact = 唯一命中；context = 多处命中按上下文选出；fuzzy = 去空白后命中 */
  mode: 'exact' | 'context' | 'fuzzy'
  /** 命中的是第几处（0 起）——用于提示「同页有多处相同文字」 */
  occurrence: number
}

/**
 * 在页面文本里定位引文。**这是「坐标失效后的兜底」，必须尽力而为。**
 *
 * 策略（由强到弱）：
 * 1. 全串唯一命中 → 直接用
 * 2. 多处命中 → 用 prefix/suffix 的公共长度打分，取最高分
 * 3. 完全找不到 → 去掉所有空白后再找（PDF 文本层的空格位置常与视觉不一致）
 */
export function locateQuote(
  pageText: string,
  anchor: Pick<PdfAnchor, 'quote' | 'prefix' | 'suffix'>,
): LocateResult | null {
  const quote = normalizeQuoteText(anchor.quote)
  if (!quote) return null

  const raw = findAll(pageText, quote)
  if (raw.length === 1) return { ...raw[0], mode: 'exact', occurrence: 0 }
  if (raw.length > 1) {
    const scored = raw.map((hit, i) => ({
      hit,
      score: contextScore(pageText, hit, anchor),
      occurrence: i,
    }))
    scored.sort((a, b) => b.score - a.score)
    const best = scored[0]
    // 上下文完全无信息（分数相同）时，取第一处并在 UI 提示
    return { ...best.hit, mode: 'context', occurrence: best.occurrence }
  }

  const squeezed = squeezeWhitespace(pageText)
  const sQuote = squeezeWhitespace(quote)
  // ⚠️ 注意传 `.text`：squeezeWhitespace 返回的是 {text, map}，
  // 直接把对象交给 indexOf 会被转成 "[object Object]"，永远找不到。
  const hits = findAll(squeezed.text, sQuote.text)
  if (hits.length) {
    const hit = hits[0]
    return {
      start: squeezed.map[hit.start],
      end: squeezed.map[hit.end - 1] + 1,
      mode: 'fuzzy',
      occurrence: 0,
    }
  }
  return null
}

function findAll(haystack: string, needle: string): Array<{ start: number; end: number }> {
  const out: Array<{ start: number; end: number }> = []
  let i = haystack.indexOf(needle)
  while (i >= 0) {
    out.push({ start: i, end: i + needle.length })
    i = haystack.indexOf(needle, i + 1)
  }
  return out
}

/**
 * prefix 的尾部与 suffix 的头部能对上多长，越长越可信。
 *
 * ⚠️ 取窗口时**要比 prefix 本身宽一倍，并在比较前归一化**：
 * 真实 PDF 文本层里引文与上下文之间常夹着空格/换行，
 * 若窗口宽度正好等于 `prefix.length`，前导空白会把真正的上下文挤出窗口，
 * 导致几处候选得分同为 0、退化成「总是取第一处」——
 * 而这恰恰是同页出现多次相同句子时最需要消歧的场景。
 */
function contextScore(
  pageText: string,
  hit: { start: number; end: number },
  anchor: Pick<PdfAnchor, 'prefix' | 'suffix'>,
): number {
  let score = 0
  const prefix = normalizeQuoteText(anchor.prefix)
  if (prefix) {
    const from = Math.max(0, hit.start - prefix.length * 2)
    const before = normalizeQuoteText(pageText.slice(from, hit.start))
    score += commonSuffixLen(before, prefix)
  }
  const suffix = normalizeQuoteText(anchor.suffix)
  if (suffix) {
    const to = Math.min(pageText.length, hit.end + suffix.length * 2)
    const after = normalizeQuoteText(pageText.slice(hit.end, to))
    score += commonPrefixLen(after, suffix)
  }
  return score
}

function commonPrefixLen(a: string, b: string): number {
  let i = 0
  while (i < a.length && i < b.length && a[i] === b[i]) i++
  return i
}

function commonSuffixLen(a: string, b: string): number {
  let i = 0
  while (i < a.length && i < b.length && a[a.length - 1 - i] === b[b.length - 1 - i]) i++
  return i
}

/** 去掉全部空白，并保留「压缩后下标 → 原下标」的映射。 */
function squeezeWhitespace(s: string): { text: string; map: number[] } {
  let text = ''
  const map: number[] = []
  for (let i = 0; i < s.length; i++) {
    if (/\s/.test(s[i])) continue
    text += s[i]
    map.push(i)
  }
  return { text, map }
}

/**
 * 用引文在文本层里重建 Range（坐标丢失时重新定位高亮）。
 *
 * @returns 命中的 Range 与命中方式；找不到返回 `null`
 *          —— 调用方**必须显式提示「定位可能已失效」而不是静默丢弃**。
 */
export function locateQuoteInLayer(
  root: HTMLElement,
  anchor: Pick<PdfAnchor, 'quote' | 'prefix' | 'suffix'>,
): { range: Range; mode: LocateResult['mode'] } | null {
  const index = buildTextIndex(root)
  const hit = locateQuote(index.text, anchor)
  if (!hit) return null

  const startPos = normToRaw(index, hit.start)
  const endPos = normToRaw(index, hit.end, true)
  if (!startPos || !endPos) return null

  const range = root.ownerDocument.createRange()
  try {
    range.setStart(startPos.node, startPos.offset)
    range.setEnd(endPos.node, endPos.offset)
  } catch {
    return null
  }
  return range.toString().trim() ? { range, mode: hit.mode } : null
}
