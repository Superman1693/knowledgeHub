/**
 * 静态站导出：把知识库编译成一组可以离线打开 / 直接托管的 HTML。
 *
 * ## 为什么渲染放在前端
 *
 * 应用自身的 Markdown 管线是 `markdown-it({html: true})` + **DOMPurify**。
 * `html: true` 是必需的（语雀/Notion 导出的笔记带 `<font style=...>` 内联标签），
 * 而 DOMPurify 才是真正挡住 XSS 的那一层。
 * 后端没有 DOMPurify，而**手写 HTML 净化器正是最危险的事**——
 * 本项目历史上就用正则黑名单做过净化，被 `<svg/onload=...>` 直接绕过。
 *
 * 所以这里直接复用 `renderMarkdown()`：既不重复实现净化，又保证
 * **静态站的样子 = 应用里预览的样子**。
 *
 * ## 双链怎么处理
 *
 * `renderMarkdown()` 把 `[[标题]]` 渲染成 `<a class="kh-wikilink" data-title="...">`
 * （应用内靠全局点击委托跳转，所以没有 href）。静态站里没有那套委托，
 * 需要把它换成真实的相对链接 `<a href="../notes/xxx.html#锚点">`；
 * 目标笔记不存在的，降级成带虚线标记的 `<span>`，保留「这是个未创建的引用」的语义。
 */
import { renderMarkdown } from '@/utils/markdown'
import { createZip, type ZipEntry } from '@/utils/zip'
// 与应用内同一份代码高亮主题（`:?raw` 由 Vite 提供，取到的是 CSS 原文）。
// 不带上它的话，导出站的代码块有 `hljs-*` 类但没有任何配色规则，一片黑。
import hljsTheme from 'highlight.js/styles/github.css?raw'

export interface SiteNote {
  id: string
  title: string
  content_text: string
  category?: string | null
  tags?: string[]
  updated_at?: string | null
  source_url?: string | null
}

export interface SiteBuildResult {
  entries: ZipEntry[]
  noteCount: number
  /** 存在但目标缺失的双链数量（未创建的引用） */
  missingLinks: number
}

/** 文件名安全化：去掉路径分隔符与 Windows 保留字符，折叠空白。 */
export function slugify(title: string, fallback = 'untitled'): string {
  const cleaned = (title || '')
    .trim()
    // 路径分隔符与 Windows 非法字符（含全角冒号，中文标题里常见）
    .replace(/[\\/:*?"<>|\uFF1A\uFF0A]/g, '-')
    // 控制字符
    // eslint-disable-next-line no-control-regex
    .replace(/[\x00-\x1f\x7f]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
  return cleaned || fallback
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export interface SlugMaps {
  /** 文档 ID → 文件名。页面生成用它，因为**同一标题可以有多篇笔记**。 */
  byId: Map<string, string>
  /** 标题 → 文件名。双链解析用它（`[[标题]]` 只能按标题找）。 */
  byTitle: Map<string, string>
}

/**
 * 生成唯一文件名（重名时追加 -2、-3…）。
 *
 * ⚠️ 必须**按文档 ID**保存映射，不能只按标题：
 * 同一标题完全可能对应多篇笔记（复制一份再改内容是最常见的用法），
 * 只按标题登记会让后一篇覆盖前一篇，最终只生成一个页面、丢内容。
 *
 * 双链只能按标题解析，所以另给一份 `byTitle`（同名时取第一篇）；
 * 这与应用内的双链解析口径一致——那里的 `[[标题]]` 也是按标题查。
 */
export function buildSlugMap(notes: SiteNote[]): SlugMaps {
  const byId = new Map<string, string>()
  const byTitle = new Map<string, string>()
  const used = new Set<string>()

  for (const n of notes) {
    const base = slugify(n.title || n.id)
    let slug = base
    let i = 2
    while (used.has(slug.toLowerCase())) {
      slug = `${base}-${i++}`
    }
    used.add(slug.toLowerCase())
    byId.set(n.id, slug)
    if (!byTitle.has(n.title)) byTitle.set(n.title, slug)
  }
  return { byId, byTitle }
}

/** 从渲染结果里抽出这篇笔记引用了哪些标题（用于算反向链接）。 */
function extractOutgoing(html: string): string[] {
  const out: string[] = []
  const re = /<a class="kh-(?:wikilink|embed)"[^>]*data-title="([^"]*)"/g
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    out.push(m[1]!.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&lt;/g, '<'))
  }
  return out
}

/**
 * 把 `<a class="kh-wikilink" data-title="X">` 换成真实链接。
 *
 * 未创建的引用降级为 `<span>` 而不是留死链——死链点了 404，
 * 而虚线标记能告诉读者「作者本来想写这篇」。
 */
function rewriteWikilinks(
  html: string,
  slugByTitle: Map<string, string>,
  depthPrefix: string,
): { html: string; missing: number } {
  let missing = 0
  const re =
    /<a class="kh-(wikilink|embed)"[^>]*data-title="([^"]*)"[^>]*data-anchor="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g

  const out = html.replace(
    re,
    (_m, kind: string, rawTitle: string, rawAnchor: string, inner: string) => {
      const title = rawTitle
        .replace(/&amp;/g, '&')
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, '<')
      const slug = slugByTitle.get(title)
      if (!slug) {
        missing += 1
        return `<span class="kh-missing" title="笔记「${escapeHtml(title)}」尚未创建">${inner}</span>`
      }
      const anchor = rawAnchor ? `#${encodeURIComponent(rawAnchor)}` : ''
      const cls = kind === 'embed' ? 'kh-embed-link' : 'kh-wikilink-link'
      return `<a class="${cls}" href="${depthPrefix}notes/${slug}.html${anchor}">${inner}</a>`
    },
  )
  return { html: out, missing }
}

const SITE_CSS = `:root {
  --fg: #24292f; --fg-sub: #57606a; --fg-mute: #8b949e;
  --bg: #ffffff; --bg-sub: #f6f8fa; --border: #d0d7de;
  --accent: #0969da; --mark: #fff2ba;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 20px 64px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 15px; line-height: 1.75; color: var(--fg); background: var(--bg);
}
.wrap { max-width: 820px; margin: 0 auto; }
header.site {
  border-bottom: 1px solid var(--border); padding: 18px 0; margin-bottom: 28px;
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
}
header.site a { color: var(--fg); text-decoration: none; font-weight: 600; font-size: 17px; }
header.site .sub { color: var(--fg-mute); font-size: 13px; }
h1 { font-size: 26px; line-height: 1.35; margin: 0 0 10px; }
h2 { font-size: 21px; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
h3 { font-size: 17px; margin: 26px 0 10px; }
h4, h5, h6 { font-size: 15px; margin: 22px 0 8px; }
a { color: var(--accent); }
.meta { color: var(--fg-mute); font-size: 13px; margin-bottom: 26px; }
.meta .tag {
  display: inline-block; background: var(--bg-sub); border: 1px solid var(--border);
  border-radius: 10px; padding: 0 8px; margin-right: 6px; font-size: 12px;
}
code {
  background: var(--bg-sub); border-radius: 4px; padding: 1px 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.9em;
}
pre {
  background: var(--bg-sub); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px; overflow-x: auto; line-height: 1.55;
}
pre code { background: none; padding: 0; font-size: 13px; }
blockquote {
  margin: 14px 0; padding: 2px 0 2px 14px;
  border-left: 3px solid var(--border); color: var(--fg-sub);
}
table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 14px; }
th, td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
th { background: var(--bg-sub); }
img { max-width: 100%; height: auto; }
hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
mark { background: var(--mark); }
/* 双链：与普通外链区分开，一眼看出是站内引用 */
a.kh-wikilink-link { border-bottom: 1px dashed var(--accent); text-decoration: none; }
a.kh-embed-link { border-bottom: 2px solid var(--accent); text-decoration: none; }
.kh-missing {
  border-bottom: 1px dashed var(--fg-mute); color: var(--fg-mute); cursor: help;
}
/* 索引页 */
.note-list { list-style: none; padding: 0; margin: 0; }
.note-list li { padding: 8px 0; border-bottom: 1px solid var(--bg-sub); }
.note-list a { text-decoration: none; font-weight: 500; }
.note-list a:hover { text-decoration: underline; }
.note-list .d { color: var(--fg-mute); font-size: 12.5px; margin-left: 8px; }
.cat { margin-top: 26px; }
.cat h2 { font-size: 15px; color: var(--fg-sub); border: none; margin: 0 0 6px; }
.backlinks { margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--border); }
.backlinks h2 { font-size: 15px; border: none; margin: 0 0 8px; color: var(--fg-sub); }
#q {
  width: 100%; padding: 9px 12px; font-size: 14px; font-family: inherit;
  border: 1px solid var(--border); border-radius: 8px; margin-bottom: 18px;
}
footer.site {
  margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--border);
  color: var(--fg-mute); font-size: 12.5px;
}
`

/** 全站共用的页头/页脚，各页保持一致。 */
function pageShell(title: string, inner: string, depthPrefix: string, siteName: string): string {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} · ${escapeHtml(siteName)}</title>
<link rel="stylesheet" href="${depthPrefix}style.css">
</head>
<body>
<div class="wrap">
<header class="site">
  <a href="${depthPrefix}index.html">${escapeHtml(siteName)}</a>
  <span class="sub">${escapeHtml(title)}</span>
</header>
${inner}
<footer class="site">由 KnowledgeHub 导出为静态站点</footer>
</div>
</body>
</html>`
}

export function buildStaticSite(
  notes: SiteNote[],
  siteName = '我的知识库',
): SiteBuildResult {
  const { byId: slugById, byTitle: slugByTitle } = buildSlugMap(notes)

  // 先渲染一遍拿 out-links，才能算出反向链接（需要两遍：先收集再生成）
  const rendered = notes.map((n) => {
    const html = renderMarkdown(n.content_text || '')
    return { note: n, rawHtml: html, outgoing: extractOutgoing(html) }
  })

  const backlinks = new Map<string, string[]>()
  for (const r of rendered) {
    for (const target of r.outgoing) {
      if (!slugByTitle.has(target) || target === r.note.title) continue
      const list = backlinks.get(target) || []
      list.push(r.note.title)
      backlinks.set(target, list)
    }
  }

  const entries: ZipEntry[] = []
  let missingLinks = 0

  for (const r of rendered) {
    const slug = slugById.get(r.note.id)!
    // 页面在 notes/ 下，所以回指站内要退一级
    const { html, missing } = rewriteWikilinks(r.rawHtml, slugByTitle, '../')
    missingLinks += missing

    const note = r.note
    const parts = [`<h1>${escapeHtml(note.title)}</h1>`]

    const metaBits: string[] = []
    if (note.updated_at) {
      metaBits.push(`更新于 ${escapeHtml(note.updated_at.slice(0, 10))}`)
    }
    if (note.category) metaBits.push(`分类：${escapeHtml(note.category)}`)
    if (note.source_url) {
      metaBits.push(
        `来源：<a href="${escapeHtml(note.source_url)}" target="_blank" rel="noopener noreferrer">原文</a>`,
      )
    }
    const tagHtml = (note.tags || [])
      .map((t) => `<span class="tag">${escapeHtml(t)}</span>`)
      .join('')
    if (metaBits.length || tagHtml) {
      parts.push(`<div class="meta">${metaBits.join(' · ')} ${tagHtml}</div>`)
    }

    parts.push(`<article>${html}</article>`)

    const back = backlinks.get(note.title)
    if (back && back.length) {
      parts.push(
        `<div class="backlinks"><h2>被引用（${back.length}）</h2><ul class="note-list">` +
          back
            .map(
              (t) =>
                `<li><a href="${slugByTitle.get(t)}.html">${escapeHtml(t)}</a></li>`,
            )
            .join('') +
          '</ul></div>',
      )
    }

    entries.push({
      path: `notes/${slug}.html`,
      content: pageShell(note.title, parts.join('\n'), '../', siteName),
    })
  }

  // ---- 索引页 ----
  const byCategory = new Map<string, SiteNote[]>()
  for (const n of notes.slice().sort((a, b) => a.title.localeCompare(b.title, 'zh'))) {
    const key = n.category || '未分类'
    byCategory.set(key, [...(byCategory.get(key) || []), n])
  }

  const catHtml = [...byCategory.entries()]
    .map(([cat, list]) => {
      const items = list
        .map((n) => {
          const date = n.updated_at ? `<span class="d">${n.updated_at.slice(0, 10)}</span>` : ''
          return `<li data-title="${escapeHtml(n.title.toLowerCase())}"><a href="notes/${slugById.get(n.id)}.html">${escapeHtml(n.title)}</a>${date}</li>`
        })
        .join('\n')
      return `<div class="cat"><h2>${escapeHtml(cat)}（${list.length}）</h2><ul class="note-list">${items}</ul></div>`
    })
    .join('\n')

  // 纯静态站点，筛选用一个内联脚本即可，不引入任何外部资源（保证离线可用）
  const indexHtml = pageShell(
    '全部笔记',
    `<h1>${escapeHtml(siteName)}</h1>
<div class="meta">共 ${notes.length} 篇</div>
<input id="q" type="search" placeholder="筛选标题…" autocomplete="off">
${catHtml}
<script>
(function () {
  var input = document.getElementById('q')
  if (!input) return
  input.addEventListener('input', function () {
    var kw = input.value.trim().toLowerCase()
    document.querySelectorAll('.cat').forEach(function (cat) {
      var shown = 0
      cat.querySelectorAll('li').forEach(function (li) {
        var hit = !kw || (li.getAttribute('data-title') || '').indexOf(kw) >= 0
        li.style.display = hit ? '' : 'none'
        if (hit) shown++
      })
      cat.style.display = shown ? '' : 'none'
    })
  })
})()
</script>`,
    '',
    siteName,
  )

  entries.push({ path: 'index.html', content: indexHtml })
  entries.push({ path: 'style.css', content: SITE_CSS + '\n' + hljsTheme })

  return { entries, noteCount: notes.length, missingLinks }
}

/** 生成 zip 字节流，供浏览器直接下载。 */
export function buildSiteZip(notes: SiteNote[], siteName = '我的知识库'): {
  bytes: Uint8Array
  noteCount: number
  missingLinks: number
  filename: string
} {
  const { entries, noteCount, missingLinks } = buildStaticSite(notes, siteName)
  const ts = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}_${pad(ts.getHours())}${pad(ts.getMinutes())}`
  return {
    bytes: createZip(entries, ts),
    noteCount,
    missingLinks,
    filename: `knowledgehub_site_${stamp}.zip`,
  }
}
