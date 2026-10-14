/**
 * 静态站导出：ZIP 打包与站点生成。
 *
 * 这两块都是「纯逻辑、`vue-tsc` 完全拦不住」的代码——
 * 与项目里 Markdown 净化 / SSE 解析两个测试文件同类。
 *
 * ZIP 尤其需要测试：字节偏移写错一个数字**不会报错**，
 * 只会让解压工具说「压缩包损坏」，且很难查。这里逐字段验签。
 */
import { describe, expect, it } from 'vitest'
import { createZip } from '@/utils/zip'
import { buildSlugMap, buildStaticSite, slugify, type SiteNote } from '@/utils/staticSite'
import hljsTheme from 'highlight.js/styles/github.css?raw'

/**
 * vitest 的 CSS 处理会拦截 node_modules 里 `?raw` 的导入，使主题在测试环境为空
 * （已实测：同一条 import 在 vitest 得到长度 0，在生产构建产物里正常）。
 * 所以这条用例在该环境下**跳过**而不是放宽断言——放宽会给出「已验证」的假象。
 * 生产侧的证据：`dist/assets/DocumentsView-*.js` 内含 `hljs-keyword` 规则。
 */
const THEME_AVAILABLE = typeof hljsTheme === 'string' && hljsTheme.length > 0

/** 按小端读 4 字节，用于验签与偏移。 */
function u32(bytes: Uint8Array, at: number): number {
  return (
    bytes[at]! | (bytes[at + 1]! << 8) | (bytes[at + 2]! << 16) | (bytes[at + 3]! << 24)
  ) >>> 0
}
function u16(bytes: Uint8Array, at: number): number {
  return bytes[at]! | (bytes[at + 1]! << 8)
}
const decoder = new TextDecoder()

describe('createZip', () => {
  it('写出合法的本地头 / 中央目录 / EOCD 签名', () => {
    const zip = createZip([{ path: 'a.txt', content: 'hello' }])
    // 本地文件头
    expect(u32(zip, 0)).toBe(0x04034b50)
    // EOCD 在最后 22 字节
    const eocdAt = zip.length - 22
    expect(u32(zip, eocdAt)).toBe(0x06054b50)
    // 中央目录位置从 EOCD 读，不手工算偏移（算错就变成了在测自己的算术）
    const cdOffset = u32(zip, eocdAt + 16)
    expect(u32(zip, cdOffset)).toBe(0x02014b50)
  })

  it('中央目录记录的本地头偏移量指向正确的签名', () => {
    // 这是最容易写错的一处：偏移差一个字节整个包就废
    const zip = createZip([
      { path: 'one.txt', content: 'first file' },
      { path: 'two.txt', content: 'second file' },
    ])
    const eocdAt = zip.length - 22
    const total = u16(zip, eocdAt + 10)
    const cdOffset = u32(zip, eocdAt + 16)
    expect(total).toBe(2)

    let p = cdOffset
    for (let i = 0; i < total; i++) {
      expect(u32(zip, p)).toBe(0x02014b50)
      const nameLen = u16(zip, p + 28)
      const localOffset = u32(zip, p + 42)
      // 偏移量必须落在本地文件头的签名上
      expect(u32(zip, localOffset)).toBe(0x04034b50)
      p += 46 + nameLen
    }
  })

  it('置 UTF-8 标志位，中文文件名不会乱码', () => {
    const zip = createZip([{ path: 'notes/中文笔记.html', content: '内容' }])
    // 标志位在本地头偏移 6，0x0800 表示文件名为 UTF-8
    expect(u16(zip, 6)).toBe(0x0800)
    // 文件名按 UTF-8 编码后出现在本地头里
    const nameBytes = new TextEncoder().encode('notes/中文笔记.html')
    const nameAt = 30
    const got = decoder.decode(zip.slice(nameAt, nameAt + nameBytes.length))
    expect(got).toBe('notes/中文笔记.html')
  })

  it('大小为 0 的文件也能正常打包', () => {
    const zip = createZip([{ path: 'empty.txt', content: '' }])
    expect(u32(zip, 0)).toBe(0x04034b50)
    expect(u32(zip, 14)).toBe(0) // CRC 为 0
    expect(u32(zip, 18)).toBe(0) // 压缩后大小
  })

  it('空列表产出只含 EOCD 的合法包', () => {
    const zip = createZip([])
    expect(zip.length).toBe(22)
    expect(u32(zip, 0)).toBe(0x06054b50)
    expect(u16(zip, 10)).toBe(0) // 条目数 0
  })
})

describe('slugify', () => {
  it('去掉路径分隔符与 Windows 保留字符', () => {
    // 中文标题里出现全角冒号很常见（「笔记：第一章」）
    expect(slugify('笔记：第一章')).not.toContain(':')
    expect(slugify('a/b\\c')).not.toContain('/')
    expect(slugify('a/b\\c')).not.toContain('\\')
    expect(slugify('a?b*c"d<e>f|g')).not.toMatch(/[?*"<>|]/)
  })

  it('折叠空白与多余连字符', () => {
    expect(slugify('  Hello   World  ')).toBe('Hello-World')
    expect(slugify('a---b')).toBe('a-b')
  })

  it('空标题回退到 fallback，不产生空文件名', () => {
    expect(slugify('', 'untitled')).toBe('untitled')
    expect(slugify('///', 'untitled')).toBe('untitled')
    expect(slugify('   ', 'untitled')).toBe('untitled')
  })
})

describe('buildSlugMap', () => {
  it('同名标题得到不同文件名，且每篇都保留自己的页面', () => {
    // 这是真出过的 bug：表以标题为键 → 后一篇覆盖前一篇 → 只生成一个页面、丢内容
    const maps = buildSlugMap([
      { id: '1', title: '重复', content_text: '' },
      { id: '2', title: '重复', content_text: '' },
      { id: '3', title: '重复', content_text: '' },
    ])
    const slugs = [...maps.byId.values()]
    expect(maps.byId.size).toBe(3)
    expect(new Set(slugs).size).toBe(3)
    // 标题查表取第一篇（双链只能按标题解析，与应用内口径一致）
    expect(maps.byTitle.size).toBe(1)
    expect(maps.byTitle.get('重复')).toBe(slugs[0])
  })

  it('同名笔记各自生成独立页面', () => {
    const { entries, noteCount } = buildStaticSite([
      { id: '1', title: '同名', content_text: '第一篇内容' },
      { id: '2', title: '同名', content_text: '第二篇内容' },
    ])
    expect(noteCount).toBe(2)
    const pages = entries.filter((e) => e.path.startsWith('notes/'))
    expect(pages.length).toBe(2)
    expect(pages.some((p) => p.content.includes('第一篇内容'))).toBe(true)
    expect(pages.some((p) => p.content.includes('第二篇内容'))).toBe(true)
  })

  it('大小写不同的标题也算冲突（Windows 文件系统不区分大小写）', () => {
    const maps = buildSlugMap([
      { id: '1', title: 'Readme', content_text: '' },
      { id: '2', title: 'readme', content_text: '' },
    ])
    expect(new Set([...maps.byId.values()].map((s) => s.toLowerCase())).size).toBe(2)
  })
})

describe('buildStaticSite', () => {
  const notes: SiteNote[] = [
    {
      id: '1',
      title: 'Vue 响应式',
      content_text: 'Vue 3 用 Proxy。参见 [[Proxy 原理]]。',
      updated_at: '2026-10-14T10:00:00+08:00',
    },
    {
      id: '2',
      title: 'Proxy 原理',
      content_text: '这是 Proxy 的说明。',
    },
  ]

  it('生成索引页、每篇笔记一页、样式表', () => {
    const { entries, noteCount } = buildStaticSite(notes)
    const paths = entries.map((e) => e.path)
    expect(noteCount).toBe(2)
    expect(paths).toContain('index.html')
    expect(paths).toContain('style.css')
    expect(paths.filter((p) => p.startsWith('notes/')).length).toBe(2)
  })

  it('双链变成页面之间的真实相对链接', () => {
    const { entries } = buildStaticSite(notes)
    const page = entries.find((e) => e.path.startsWith('notes/') && e.content.includes('Proxy'))!
    const vuePage = entries.find((e) => e.content.includes('Vue 3 用 Proxy'))!
    // 引用方页面上应出现指向目标页的相对链接（页面在 notes/ 下，退一级）
    expect(vuePage.content).toMatch(/href="\.\.\/notes\/[^"]+\.html"/)
    expect(vuePage.content).toMatch(/class="kh-wikilink-link"/)
    expect(page).toBeTruthy()
  })

  it('指向未创建笔记的引用降级为虚线标记，不留死链', () => {
    const { entries, missingLinks } = buildStaticSite([
      { id: '1', title: 'A', content_text: '参见 [[根本不存在]]。' },
    ])
    const page = entries.find((e) => e.path === 'notes/A.html')!
    expect(missingLinks).toBe(1)
    expect(page.content).toContain('kh-missing')
    expect(page.content).not.toMatch(/href="\.\.\/notes\/[^"]*" [^>]*>根本不存在/)
  })

  it('生成反向链接（被引用计数）', () => {
    const { entries } = buildStaticSite(notes)
    const target = entries.find((e) => e.content.includes('这是 Proxy 的说明'))!
    expect(target.content).toContain('被引用')
    expect(target.content).toContain('Vue 响应式')
  })

  it('正文里的原始 HTML 被净化，不产生脚本注入', () => {
    // 静态站是拿来分享/托管的，注入面必须堵死
    const { entries } = buildStaticSite([
      { id: '1', title: 'X', content_text: '<script>alert(1)</script>\n\n正常内容' },
    ])
    const page = entries.find((e) => e.path === 'notes/X.html')!
    expect(page.content).not.toContain('<script>alert(1)</script>')
    expect(page.content).toContain('正常内容')
  })

  it('标题里的 HTML 被转义（标题不经过 markdown 管线，需单独转义）', () => {
    const { entries } = buildStaticSite([
      { id: '1', title: '<img src=x onerror=alert(1)>', content_text: 'body' },
    ])
    const index = entries.find((e) => e.path === 'index.html')!
    expect(index.content).not.toContain('<img src=x onerror=alert(1)>')
    expect(index.content).toContain('&lt;img')
  })

  it.skipIf(!THEME_AVAILABLE)('样式表带上 highlight.js 主题，代码块才有配色', () => {
    // 少了这份主题，导出站的代码块有 hljs-* 类但没有任何配色规则，一片黑
    const { entries } = buildStaticSite([{ id: '1', title: 'A', content_text: '```js\nconst a=1\n```' }])
    const css = entries.find((e) => e.path === 'style.css')!.content
    expect(css).toContain('hljs')
  })

  it('索引页按分类分组并带筛选脚本（不依赖外部资源，保证离线可用）', () => {
    const { entries } = buildStaticSite([
      { id: '1', title: 'A', content_text: 'a', category: '前端' },
      { id: '2', title: 'B', content_text: 'b' },
    ])
    const index = entries.find((e) => e.path === 'index.html')!
    expect(index.content).toContain('前端')
    expect(index.content).toContain('未分类')
    expect(index.content).toContain('id="q"')
    // 不引入任何外部资源
    expect(index.content).not.toMatch(/<script\s+src=/)
    expect(index.content).not.toMatch(/https?:\/\/cdn/)
  })
})
