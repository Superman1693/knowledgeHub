import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

/**
 * Markdown 渲染的**安全**回归。
 *
 * 背景：这里曾经用手写正则黑名单净化（只拦 `\son\w+=`，且要求事件属性前有空白），
 * 结果 `<svg/onload=...>`、`<img/src=x/onerror=...>` 可以绕过，`javascript:` 也完全没处理，
 * 而渲染结果直接喂给 `v-html`。改用 DOMPurify 后，这些用例守住底线。
 */
/**
 * 把渲染结果放进真实 DOM 再检查——比字符串匹配可靠得多。
 *
 * 原因：markdown-it 对「非法块级 HTML」会**转义成文本**（如 `<svg/onload=…>` 不在
 * 块级标签表里，会被转义），此时输出里仍然出现 "onload" 字样但完全无害。
 * 因此断言应该落在「有没有真的生成危险元素/属性」上，而不是「字符串里有没有这个词」。
 */
function parse(html: string): HTMLElement {
  const div = document.createElement('div')
  div.innerHTML = html
  return div
}

function assertNoDangerousNode(html: string) {
  const root = parse(html)
  expect(root.querySelector('script, iframe, object, embed')).toBeNull()
  for (const el of Array.from(root.querySelectorAll('*'))) {
    for (const attr of Array.from(el.attributes)) {
      expect(attr.name.toLowerCase().startsWith('on'), `危险事件属性 ${attr.name}`).toBe(false)
      expect(
        attr.value.trim().toLowerCase().startsWith('javascript:'),
        `危险的 javascript: 值`,
      ).toBe(false)
    }
  }
}

describe('renderMarkdown 安全净化', () => {
  it('移除 <script>', () => {
    const html = renderMarkdown('正文\n\n<script>alert(1)</script>')
    expect(parse(html).querySelector('script')).toBeNull()
    assertNoDangerousNode(html)
  })

  it('内联事件处理器（含无空白的 svg/onload 写法）不会落地成属性', () => {
    const html = renderMarkdown('<svg/onload=alert(2)>')
    assertNoDangerousNode(html)
    expect(parse(html).querySelector('svg')).toBeNull()
  })

  it('移除 img 上的 onerror', () => {
    const html = renderMarkdown('<img src=x onerror=alert(3)>')
    assertNoDangerousNode(html)
    // 图片本身可以保留，但 onerror 必须没了
    expect(html).not.toMatch(/onerror\s*=/i)
  })

  it('移除 javascript: 链接', () => {
    const html = renderMarkdown('<a href="javascript:alert(4)">点我</a>')
    assertNoDangerousNode(html)
    expect(html.toLowerCase()).not.toContain('javascript:')
  })

  it('移除 iframe / object / embed', () => {
    const html = renderMarkdown(
      '<iframe src="https://evil.test"></iframe><object data="x"></object><embed src="x">',
    )
    assertNoDangerousNode(html)
    expect(parse(html).querySelector('iframe, object, embed')).toBeNull()
  })

  it('保留 style（语雀/Notion 颜色依赖它），但 javascript: 不会落到链接/资源属性上', () => {
    // 说明：style 属性是刻意保留的——语雀导出的 `color` / `font` 全靠它。
    // style 里可能出现的 `url(javascript:…)` / `expression()` 在现代浏览器中**不执行**
    // （只有 IE≤7 会），属于已消亡的攻击面，因此不为此再加一层正则消毒。
    // 真正要守住的是：链接与资源属性上不能出现 javascript: 协议。
    const html = renderMarkdown(
      '<a href="javascript:alert(6)">链接</a><div style="color:red">红字</div>',
    )
    const root = parse(html)
    expect(root.querySelector('a[href^="javascript:"]')).toBeNull()
    expect(html.toLowerCase()).not.toContain('href="javascript:')
    // 需要的样式能力必须还在，否则语雀笔记会掉色
    expect(root.querySelector('div[style]')?.getAttribute('style')).toContain('color:red')
    assertNoDangerousNode(html)
  })
})

describe('renderMarkdown 正常渲染', () => {
  it('渲染标题、列表与行内代码', () => {
    const html = renderMarkdown('# 标题\n\n- 一\n- 二\n\n`code`')
    expect(html).toContain('<h1')
    expect(html).toContain('<li>一</li>')
    expect(html).toContain('<code>code</code>')
  })

  it('保留语雀/Notion 导出的内联样式（<font> 与 style）', () => {
    const html = renderMarkdown('<font style="color:red">红字</font>')
    expect(html).toContain('红字')
    expect(html.toLowerCase()).toContain('color:red')
  })

  it('给图片补 referrerpolicy（语雀图床防盗链）', () => {
    const html = renderMarkdown('![图](https://cdn.example.com/a.png)')
    expect(html).toContain('referrerpolicy="no-referrer"')
  })

  it('空输入不报错', () => {
    expect(renderMarkdown('')).toBe('')
  })
})

/**
 * 双链与块级引用的渲染。
 *
 * 背景：markdown-it 不认识 `[[标题]]`，此前它只是正文里一段不可点的纯文本 ——
 * 双链只在知识图谱和侧栏列表里生效。现在在 HTML 层补成可点的 <a>。
 */
describe('双链渲染', () => {
  it('[[标题]] 变成带 data-title 的可点链接', () => {
    const root = parse(renderMarkdown('见 [[vue]] 的安装说明'))
    const link = root.querySelector<HTMLElement>('.kh-wikilink')
    expect(link).not.toBeNull()
    expect(link?.dataset.title).toBe('vue')
    expect(link?.textContent).toBe('vue')
  })

  it('[[标题#锚点]] 同时带上 data-anchor', () => {
    const root = parse(renderMarkdown('见 [[docker#安装]]'))
    const link = root.querySelector<HTMLElement>('.kh-wikilink')
    expect(link?.dataset.title).toBe('docker')
    expect(link?.dataset.anchor).toBe('安装')
  })

  it('[[标题|别名]] 显示别名、标题仍可解析', () => {
    const root = parse(renderMarkdown('见 [[vue|Vue 官方文档]]'))
    const link = root.querySelector<HTMLElement>('.kh-wikilink')
    expect(link?.textContent).toBe('Vue 官方文档')
    expect(link?.dataset.title).toBe('vue')
  })

  it('![[标题]] 是嵌入引用，与普通链接区分开', () => {
    const root = parse(renderMarkdown('嵌入 ![[vue#简介]] 在这里'))
    const embed = root.querySelector<HTMLElement>('.kh-embed')
    expect(embed).not.toBeNull()
    expect(embed?.dataset.title).toBe('vue')
    expect(embed?.dataset.anchor).toBe('简介')
    // 同一条嵌入不应再被当成普通链接（否则会重复记一条边）
    expect(root.querySelectorAll('.kh-wikilink')).toHaveLength(0)
  })

  it('代码块里的双方括号语法不被转换', () => {
    const html = renderMarkdown('```\n[[这不是链接]]\n```')
    expect(html).not.toContain('kh-wikilink')
    expect(html).toContain('[[这不是链接]]')
  })

  it('行内代码里同样不转换', () => {
    const html = renderMarkdown('用 `[[标题]]` 建立双链')
    expect(html).not.toContain('kh-wikilink')
  })

  it('注入的属性值经过转义，不含 HTML 注入面', () => {
    // 注意：断言要落在 DOM 上，而不是「字符串里有没有 onmouseover」——
    // 转义后这个词会作为普通文本出现在属性值里，那是无害的；
    // 真正危险的是它变成一个真实的事件属性。
    const root = parse(renderMarkdown('[[a"onmouseover=alert(1)]]'))
    expect(root.querySelector('.kh-wikilink')).not.toBeNull()
    for (const el of Array.from(root.querySelectorAll('*'))) {
      for (const attr of Array.from(el.attributes)) {
        expect(attr.name.toLowerCase().startsWith('on'), `危险事件属性 ${attr.name}`).toBe(false)
      }
    }
    // 引号被转义，属性没有提前闭合
    const link = root.querySelector<HTMLElement>('.kh-wikilink')
    expect(link?.dataset.title).toBe('a"onmouseover=alert(1)')
  })
})
