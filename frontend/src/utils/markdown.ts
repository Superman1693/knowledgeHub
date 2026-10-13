import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'

const md = new MarkdownIt({
  // 语雀 / Notion 等导出的笔记含 <font style="color:..."> 这类内联样式标签，
  // 必须开启 html 才能正确显示颜色与字体；原始 HTML 由下面的 DOMPurify 净化。
  html: true,
  linkify: true,
  breaks: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        /* 回退到转义输出 */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
  },
})

/**
 * 净化 HTML，避免导入/粘贴的文档在预览时执行脚本。
 *
 * 使用 DOMPurify（而不是手写正则黑名单）：
 * 正则版只拦截 `\son\w+=` 且要求事件属性前有空白字符，
 * `<svg/onload=alert(1)>`、`<img/src=x/onerror=...>` 这类写法可直接绕过；
 * 也完全不处理 `javascript:` 协议。DOMPurify 按白名单解析，才是真正的净化。
 */
const PURIFY_CONFIG = {
  // 保留 <font>（语雀导出常用）与 target 属性；style 属性默认即在白名单内
  ADD_TAGS: ['font'],
  ADD_ATTR: ['target'],
}

/**
 * 给 <img> 补上 referrerpolicy="no-referrer"。
 * 语雀 / Notion 等图床有防盗链：请求带 Referer 会返回 403，去掉后正常 200。
 * 在净化之后执行，避免 DOMPurify 因未知属性而剥掉它。
 */
function fixImages(html: string): string {
  return html.replace(
    /<img\b(?![^>]*referrerpolicy)/gi,
    '<img referrerpolicy="no-referrer" loading="lazy"',
  )
}

/**
 * 把正文里的 `[[标题#锚点]]` / `![[标题#锚点]]` 变成可点击的链接。
 *
 * markdown-it 不认识双方括号语法，会原样输出成纯文本 —— 也就是说
 * 双链此前只在知识图谱和侧栏列表里生效，正文里点了没反应。
 * 这里在 HTML 层面补齐：渲染成带 data-title / data-anchor 的 <a>，
 * 由全局点击委托查表拿到目标文档 ID 再跳转（见 `composables/useWikiLinks.ts`）。
 *
 * **不加 href**：`javascript:` 会被安全策略拦，`#` 又会污染 history 路由的
 * 查询串。改用无 href + `cursor:pointer` + 全局点击委托，行为完全可控。
 *
 * 代码内不做替换：用户可能正是在文档里讲解这个语法本身。
 * 块级代码（<pre>）与行内代码（<code>）都要跳过 —— 只挡 <pre> 的话，
 * `` `[[标题]]` `` 这种写在行内代码里的说明文字也会被误转成链接。
 * 注入的属性值都经过 escAttr / escText 转义，不存在 HTML 注入面。
 */
function linkifyWikilinks(html: string): string {
  // 按 <pre>…</pre> 与 <code>…</code> 切分，奇数段是代码，原样保留
  const parts = html.split(/(<pre[\s\S]*?<\/pre>|<code[^>]*>[\s\S]*?<\/code>)/gi)
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part
      // 先处理嵌入引用，再处理普通链接（`![[x]]` 的前半段会被后者匹配到）
      return part
        .replace(
          /!\[\[([^\[\]\n|#]+)(?:#([^\[\]\n|]+))?(?:\|([^\[\]\n]+))?\]\]/g,
          (_m, title: string, anchor: string, alias: string) =>
            `<a class="kh-embed" role="link" tabindex="0"` +
            ` data-title="${escAttr(title)}" data-anchor="${escAttr(anchor || '')}">` +
            `${escText(alias || title)}</a>`,
        )
        .replace(
          /(?<!!)\[\[([^\[\]\n|#]+)(?:#([^\[\]\n|]+))?(?:\|([^\[\]\n]+))?\]\]/g,
          (_m, title: string, anchor: string, alias: string) =>
            `<a class="kh-wikilink" role="link" tabindex="0"` +
            ` data-title="${escAttr(title)}" data-anchor="${escAttr(anchor || '')}">` +
            `${escText(alias || title)}</a>`,
        )
    })
    .join('')
}

function escAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
}

function escText(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function renderMarkdown(text: string): string {
  const raw = md.render(text || '')
  return linkifyWikilinks(fixImages(DOMPurify.sanitize(raw, PURIFY_CONFIG)))
}
