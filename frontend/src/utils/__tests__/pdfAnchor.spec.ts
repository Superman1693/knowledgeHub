/**
 * PDF 批注锚定的几何与引文定位测试。
 *
 * 这里检验的是整个方案唯一「做了才发现不对」的部分：坐标系。
 * 阶段 0 的结论先固化成断言，后面改渲染代码时不会悄悄退化。
 *
 * ⚠️ jsdom 没有布局引擎，`getClientRects()` 恒为空 ——
 * 所以 `normalizeRects` 用**构造出的矩形**测（那正是它唯一的输入契约），
 * 而不去假装能测真实排版。
 */
import { describe, expect, it } from 'vitest'
import {
  QUOTE_CONTEXT,
  buildTextIndex,
  denormalizeRects,
  locateQuote,
  locateQuoteInLayer,
  mergeLineRects,
  normalizeQuoteText,
  normalizeRects,
  pickQuote,
  selectionToNormOffsets,
  type NormRect,
} from '@/utils/pdfAnchor'

const box = (left: number, top: number, width: number, height: number) => ({
  left,
  top,
  width,
  height,
})

describe('normalizeRects', () => {
  it('按页面框归一化到 0..1', () => {
    const page = box(100, 50, 400, 800)
    const [r] = normalizeRects([box(200, 250, 100, 16)], page)
    expect(r.x).toBeCloseTo(0.25, 6) // (200-100)/400
    expect(r.y).toBeCloseTo(0.25, 6) // (250-50)/800
    expect(r.w).toBeCloseTo(0.25, 6)
    expect(r.h).toBeCloseTo(0.02, 6)
  })

  it('裁掉页面外的部分（跨页选择/拖出页外）', () => {
    const page = box(0, 0, 100, 100)
    // 一半在页外
    const [r] = normalizeRects([box(-50, 10, 100, 10)], page)
    expect(r.x).toBeCloseTo(0, 6)
    expect(r.w).toBeCloseTo(0.5, 6)
  })

  it('丢弃完全在页外的矩形', () => {
    const page = box(0, 0, 100, 100)
    expect(normalizeRects([box(200, 200, 50, 50)], page)).toEqual([])
  })

  it('丢弃过小的碎片（拖选常见 0 宽/0 高）', () => {
    const page = box(0, 0, 100, 100)
    expect(normalizeRects([box(10, 10, 0.2, 5), box(10, 20, 5, 0.2)], page)).toEqual([])
  })

  it('页面框尺寸为 0 时返回空（不能做除零）', () => {
    expect(normalizeRects([box(1, 1, 10, 10)], box(0, 0, 0, 0))).toEqual([])
  })

  it('⭐ 与缩放无关：同一页在 0.5x / 1x / 2x 下归一化结果一致', () => {
    // 阶段 0 在真实 pdfjs 上验证过这条；这里固化成不依赖浏览器布局的断言
    const at = (scale: number) => {
      const page = box(0, 0, 595 * scale, 842 * scale)
      return normalizeRects([box(72 * scale, 72 * scale, 451 * scale, 14 * scale)], page)
    }
    const [a] = at(0.5)
    const [b] = at(1)
    const [c] = at(2)
    for (const r of [b, c]) {
      expect(r.x).toBeCloseTo(a.x, 9)
      expect(r.y).toBeCloseTo(a.y, 9)
      expect(r.w).toBeCloseTo(a.w, 9)
      expect(r.h).toBeCloseTo(a.h, 9)
    }
  })

  it('⭐ 旋转页：归一化按「渲染后的页面框」，横排文字在 rot90 页上自然变纵向', () => {
    // rot=0：A4 竖版，一行文字 → 扁矩形
    const portrait = normalizeRects([box(72, 72, 451, 14)], box(0, 0, 595, 842))[0]
    expect(portrait.w).toBeGreaterThan(portrait.h)

    // rot=90：页面框变横向 842x595，同一行文字在视觉上变成竖条 → 高瘦矩形
    const rotated = normalizeRects([box(500, 72, 14, 451)], box(0, 0, 842, 595))[0]
    expect(rotated.h).toBeGreaterThan(rotated.w)
    expect(rotated.x).toBeGreaterThan(0)
    expect(rotated.y).toBeGreaterThan(0)
    expect(rotated.x + rotated.w).toBeLessThanOrEqual(1.000001)
    expect(rotated.y + rotated.h).toBeLessThanOrEqual(1.000001)
  })

  it('归一化 → 反归一化 往返还原（渲染层与应用层用同一对函数）', () => {
    const rects: NormRect[] = [
      { x: 0.12, y: 0.33, w: 0.71, h: 0.02 },
      { x: 0.12, y: 0.36, w: 0.41, h: 0.02 },
    ]
    const page = box(20, 30, 400, 800)
    const back = denormalizeRects(rects, page)
    const again = normalizeRects(back, page)
    again.forEach((r, i) => {
      expect(r.x).toBeCloseTo(rects[i].x, 6)
      expect(r.y).toBeCloseTo(rects[i].y, 6)
      expect(r.w).toBeCloseTo(rects[i].w, 6)
      expect(r.h).toBeCloseTo(rects[i].h, 6)
    })
  })
})

describe('mergeLineRects', () => {
  it('同一行内相邻矩形合并成一个（空格宽度远小于行高）', () => {
    const merged = mergeLineRects([
      { x: 0.1, y: 0.2, w: 0.2, h: 0.02 },
      { x: 0.305, y: 0.2, w: 0.15, h: 0.02 },
      { x: 0.46, y: 0.2, w: 0.1, h: 0.02 },
    ])
    expect(merged).toHaveLength(1)
    expect(merged[0].x).toBeCloseTo(0.1, 6)
    expect(merged[0].w).toBeCloseTo(0.46, 6)
  })

  it('不同行不合并（跨行选择保留多个矩形）', () => {
    const merged = mergeLineRects([
      { x: 0.1, y: 0.2, w: 0.5, h: 0.02 },
      { x: 0.1, y: 0.24, w: 0.3, h: 0.02 },
    ])
    expect(merged).toHaveLength(2)
  })

  it('同一行但间距很大（分栏）不合并', () => {
    const merged = mergeLineRects([
      { x: 0.05, y: 0.2, w: 0.2, h: 0.02 },
      { x: 0.6, y: 0.2, w: 0.2, h: 0.02 },
    ])
    expect(merged).toHaveLength(2)
  })

  it('空输入与单元素输入原样返回', () => {
    expect(mergeLineRects([])).toEqual([])
    const one = [{ x: 0.1, y: 0.1, w: 0.1, h: 0.1 }]
    expect(mergeLineRects(one)).toEqual(one)
  })
})

describe('normalizeQuoteText / pickQuote', () => {
  it('去掉软连字符（PDF 断词常见，肉眼不可见但会让匹配失败）', () => {
    expect(normalizeQuoteText('re\u00adsponse')).toBe('response')
  })

  it('去掉行尾硬连字符，但保留词内连字符', () => {
    expect(normalizeQuoteText('state-of-\nthe-art')).toBe('state-ofthe-art')
    expect(normalizeQuoteText('e-mail')).toBe('e-mail')
    expect(normalizeQuoteText('well-known term')).toBe('well-known term')
  })

  it('折叠空白', () => {
    expect(normalizeQuoteText('  a \n\n b\t c  ')).toBe('a b c')
  })

  it('null / undefined 安全', () => {
    expect(normalizeQuoteText(null)).toBe('')
    expect(normalizeQuoteText(undefined)).toBe('')
  })

  it('pickQuote 截取引文与前后文，且前后文都被裁剪到上限', () => {
    const text = 'A'.repeat(50) + '引文内容' + 'B'.repeat(50)
    const { quote, prefix, suffix } = pickQuote(text, 50, 54)
    expect(quote).toBe('引文内容')
    expect(prefix).toBe('A'.repeat(QUOTE_CONTEXT))
    expect(suffix).toBe('B'.repeat(QUOTE_CONTEXT))
  })

  it('pickQuote 在文档开头/结尾时不越界', () => {
    const { quote, prefix, suffix } = pickQuote('开头引文', 0, 4)
    expect(quote).toBe('开头引文')
    expect(prefix).toBeNull()
    expect(suffix).toBeNull()
  })
})

describe('locateQuote（PDF 换版后的兜底定位）', () => {
  it('全串唯一命中 → exact', () => {
    const r = locateQuote('前缀 目标引文 后缀', { quote: '目标引文', prefix: null, suffix: null })
    expect(r).not.toBeNull()
    expect(r!.mode).toBe('exact')
    expect('前缀 目标引文 后缀'.slice(r!.start, r!.end)).toBe('目标引文')
  })

  it('⭐ 多处命中 → 用 prefix/suffix 选对那一处', () => {
    const text = '甲文 共同句 。 乙文 共同句 。'
    const first = text.indexOf('共同句')
    const second = text.indexOf('共同句', first + 1)

    const pickFirst = locateQuote(text, { quote: '共同句', prefix: '甲文', suffix: '。 乙文' })
    expect(pickFirst!.start).toBe(first)
    expect(pickFirst!.mode).toBe('context')

    const pickSecond = locateQuote(text, { quote: '共同句', prefix: '乙文', suffix: null })
    expect(pickSecond!.start).toBe(second)
  })

  it('引文里的空白与页面文本不一致时，去空白后仍能命中（fuzzy）', () => {
    const r = locateQuote('Vue3 使用 Proxy 替代', { quote: 'Vue 3 使用 Proxy', prefix: null, suffix: null })
    expect(r).not.toBeNull()
    expect(r!.mode).toBe('fuzzy')
    // 映射回原串的下标必须能取出包含原意的片段
    const got = 'Vue3 使用 Proxy 替代'.slice(r!.start, r!.end)
    expect(got.replace(/\s/g, '')).toBe('Vue3使用Proxy')
  })

  it('确实找不到时返回 null（调用方据此提示「定位已失效」）', () => {
    expect(locateQuote('完全无关的内容', { quote: '不存在的句子', prefix: null, suffix: null })).toBeNull()
    expect(locateQuote('任意内容', { quote: '   ', prefix: null, suffix: null })).toBeNull()
  })
})

describe('文本层索引与 DOM 定位', () => {
  /** 造一个结构类似 PDF.js 文本层的节点：一行被拆成多个 span。 */
  function makeLayer(parts: string[]): HTMLElement {
    const root = document.createElement('div')
    for (const p of parts) {
      const span = document.createElement('span')
      span.textContent = p
      root.appendChild(span)
    }
    document.body.appendChild(root)
    return root
  }

  it('拼接各文本节点并按 DOM 顺序建立索引', () => {
    const root = makeLayer(['Hello ', 'World'])
    const idx = buildTextIndex(root)
    expect(idx.text).toBe('Hello World')
    expect(idx.records).toHaveLength(2)
    root.remove()
  })

  it('归一化后的下标能映射回原始节点偏移（跨 span 选择）', () => {
    const root = makeLayer(['Alpha ', 'Beta', ' Gamma'])
    const idx = buildTextIndex(root)
    expect(idx.text).toBe('Alpha Beta Gamma')

    // 选中 "Beta"（跨节点的中间那个）
    const range = document.createRange()
    range.setStart(root.childNodes[1].firstChild!, 0)
    range.setEnd(root.childNodes[1].firstChild!, 4)
    const off = selectionToNormOffsets(idx, range)
    expect(off).not.toBeNull()
    expect(idx.text.slice(off!.start, off!.end)).toBe('Beta')
    root.remove()
  })

  it('⭐ 坐标丢失后，靠引文在文本层里重建 Range', () => {
    const root = makeLayer(['Vue 3 使用 ', 'Proxy', ' 替代 defineProperty'])
    const hit = locateQuoteInLayer(root, {
      quote: 'Proxy 替代',
      prefix: '使用',
      suffix: 'defineProperty',
    })
    expect(hit).not.toBeNull()
    expect(normalizeQuoteText(hit!.range.toString())).toBe('Proxy 替代')
    root.remove()
  })

  it('引文跨三个 span 也能定位（PDF.js 一行常被拆成多个文本项）', () => {
    const root = makeLayer(['依赖', '收集', '与触发'])
    const hit = locateQuoteInLayer(root, { quote: '依赖收集与触发', prefix: null, suffix: null })
    expect(hit).not.toBeNull()
    expect(normalizeQuoteText(hit!.range.toString())).toBe('依赖收集与触发')
    root.remove()
  })

  it('同页多处相同文字时按上下文选中正确的那一处', () => {
    const root = makeLayer(['第一次 响应式系统 ', '第二次 响应式系统'])
    const hit = locateQuoteInLayer(root, {
      quote: '响应式系统',
      prefix: '第二次',
      suffix: null,
    })
    expect(hit).not.toBeNull()
    // 命中的应该落在第二个 span 内
    expect(hit!.range.startContainer.parentElement).toBe(root.childNodes[1])
    root.remove()
  })

  it('文本层里没有该引文时返回 null（绝不静默丢高亮）', () => {
    const root = makeLayer(['完全不同的内容'])
    expect(locateQuoteInLayer(root, { quote: '找不到', prefix: null, suffix: null })).toBeNull()
    root.remove()
  })
})
