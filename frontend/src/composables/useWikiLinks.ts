import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { documentsApi } from '@/api'

/**
 * 正文双链点击委托。
 *
 * `renderMarkdown` 会把 `[[标题#锚点]]` 渲染成带 data-title / data-anchor 的
 * `<a class="kh-wikilink">`（见 utils/markdown.ts）。这些链接没有 href ——
 * 目标文档 ID 只有服务端知道，所以用事件委托在点击时才查表。
 *
 * 查表用「标题」与「去掉扩展名的主干」两种键：上传文档的标题是 `vue.md`，
 * 而用户写链接时通常只写 `[[vue]]`。
 */
const titleMap = ref<Map<string, string>>(new Map())
const loaded = ref(false)

/** 去掉最后一个扩展名：`vue.md` → `vue`；没有点则原样返回。 */
function stem(title: string): string {
  const i = title.lastIndexOf('.')
  return i > 0 ? title.slice(0, i) : title
}

function rebuild(items: { id: string; title: string }[]) {
  const map = new Map<string, string>()
  for (const it of items) {
    const raw = (it.title || '').trim().toLowerCase()
    if (raw) map.set(raw, it.id)
    const s = stem(raw).trim()
    if (s && !map.has(s)) map.set(s, it.id)
  }
  titleMap.value = map
}

/** 刷新标题 → ID 映射。新建/重命名笔记后应调用，否则点击会落到「未创建」。 */
export async function refreshWikiLinkTargets() {
  try {
    const res = await documentsApi.linkTargets()
    rebuild(res.items ?? [])
    loaded.value = true
  } catch {
    /* 查不到表时点击会提示未创建，不影响其它功能 */
  }
}

function resolve(title: string): string | undefined {
  const key = (title || '').trim().toLowerCase()
  return titleMap.value.get(key) ?? titleMap.value.get(stem(key).trim())
}

/** 供测试与调试：当前能否解析某个标题。 */
export function canResolveWikiLink(title: string): boolean {
  return Boolean(resolve(title))
}

export function useWikiLinks() {
  const router = useRouter()

  async function onClick(event: MouseEvent) {
    const el = (event.target as HTMLElement | null)?.closest?.(
      '.kh-wikilink, .kh-embed',
    ) as HTMLElement | null
    if (!el) return
    event.preventDefault()

    const title = el.dataset.title || ''
    const anchor = el.dataset.anchor || ''
    const docId = resolve(title)
    if (!docId) {
      ElMessage.warning(`「${title}」还没有对应笔记，先在编辑器里创建它`)
      return
    }
    await router.push({
      name: 'document-detail',
      params: { id: docId },
      // 锚点走 query 而不是 hash：history 路由下 hash 会被当成页面内锚点，
      // 而我们需要它触发目标页的定位逻辑
      query: anchor ? { h: anchor } : undefined,
    })
  }

  onMounted(() => {
    if (!loaded.value) void refreshWikiLinkTargets()
    document.addEventListener('click', onClick)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('click', onClick)
  })
}
