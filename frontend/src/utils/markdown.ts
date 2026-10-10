import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

const md = new MarkdownIt({
  // 语雀 / Notion 等导出的笔记含 <font style="color:..."> 这类内联样式标签，
  // 必须开启 html 才能正确显示颜色与字体；下面会做一次轻量清理以防脚本注入。
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
 * 移除危险标签与内联事件，避免导入的文档在预览时执行脚本。
 * 注意：这是针对「本地单用户、内容来自用户自己的文档」的轻量防护，
 * 并非通用的 HTML 净化器。
 */
function sanitize(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/<object[\s\S]*?<\/object>/gi, '')
    .replace(/<embed\b[^>]*>/gi, '')
    .replace(/\son\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
}

/**
 * 给 <img> 补上 referrerpolicy="no-referrer"。
 * 语雀 / Notion 等图床有防盗链：请求带 Referer 会返回 403，去掉后正常 200。
 */
function fixImages(html: string): string {
  return html.replace(
    /<img\b(?![^>]*referrerpolicy)/gi,
    '<img referrerpolicy="no-referrer" loading="lazy"',
  )
}

export function renderMarkdown(text: string): string {
  return fixImages(sanitize(md.render(text || '')))
}
