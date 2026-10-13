<template>
  <Teleport to="body">
    <div v-if="modelValue" class="cp-mask" @click.self="close">
      <div class="cp-panel">
        <div class="cp-head">
          <el-icon class="cp-head-icon"><Search /></el-icon>
          <input
            ref="inputEl"
            v-model="keyword"
            class="cp-input"
            placeholder="搜索笔记与片段…（Esc 关闭）"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="choose"
          />
          <span class="cp-kbd">Esc</span>
        </div>

        <div class="cp-body">
          <!-- 无关键词：快捷操作 -->
          <template v-if="!keyword.trim()">
            <div class="cp-label">快捷操作</div>
            <button
              v-for="(a, i) in actions"
              :key="a.path"
              class="cp-item"
              :class="{ active: i === activeIndex }"
              type="button"
              @click="runAction(a)"
            >
              <el-icon class="cp-item-icon"><component :is="a.icon" /></el-icon>
              <span class="cp-title">{{ a.title }}</span>
            </button>
          </template>

          <!-- 有关键词：检索结果 -->
          <template v-else>
            <div v-if="loading" class="cp-empty">搜索中…</div>
            <template v-else>
              <div v-if="!hits.length" class="cp-empty">没有找到匹配的片段</div>
              <button
                v-for="(h, i) in hits"
                :key="h.chunk_id"
                class="cp-item is-hit"
                :class="{ active: i === activeIndex }"
                type="button"
                @click="openHit(h)"
              >
                <div class="cp-item-main">
                  <div class="cp-title">
                    {{ h.document_title }}
                    <span v-if="h.heading" class="cp-sub">· {{ h.heading }}</span>
                  </div>
                  <div class="cp-snippet" v-html="highlighted(h.snippet, h.highlights)" />
                </div>
              </button>
            </template>
          </template>
        </div>

        <div class="cp-foot">
          <span><b>↑↓</b> 选择</span>
          <span><b>Enter</b> 打开</span>
          <span><b>Esc</b> 关闭</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { searchApi } from '@/api'
import type { SearchHit } from '@/api/types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const router = useRouter()
const inputEl = ref<HTMLInputElement | null>(null)
const keyword = ref('')
const hits = ref<SearchHit[]>([])
const loading = ref(false)
const activeIndex = ref(0)
let timer: number | null = null
let seq = 0

/** 无关键词时展示的快捷操作。 */
const actions = [
  { path: '/notes/new', title: '新建笔记', icon: 'EditPen' },
  { path: '/documents', title: '文档管理', icon: 'Document' },
  { path: '/upload', title: '导入文档', icon: 'UploadFilled' },
  { path: '/search', title: '高级检索', icon: 'Search' },
  { path: '/trash', title: '回收站', icon: 'Delete' },
  { path: '/workbench', title: '工作台', icon: 'HomeFilled' },
]

const itemCount = computed(() =>
  keyword.value.trim() ? hits.value.length : actions.length,
)

function close() {
  emit('update:modelValue', false)
}

function move(delta: number) {
  const n = itemCount.value
  if (!n) return
  activeIndex.value = (activeIndex.value + delta + n) % n
}

function choose() {
  if (keyword.value.trim()) {
    const hit = hits.value[activeIndex.value]
    if (hit) openHit(hit)
  } else {
    const action = actions[activeIndex.value]
    if (action) runAction(action)
  }
}

function runAction(action: { path: string }) {
  close()
  router.push(action.path)
}

function openHit(hit: SearchHit) {
  close()
  router.push({
    path: `/documents/${hit.document_id}`,
    query: { chunk: hit.chunk_id },
  })
}

function escapeHtml(text: string): string {
  return text.replace(
    /[&<>"']/g,
    (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  )
}

/** 先转义再一次性高亮，避免 XSS，也避免二次包裹 <mark>。 */
function highlighted(text: string, terms: string[] = []): string {
  const esc = escapeHtml(text || '')
  const valid = (terms || [])
    .filter(Boolean)
    .map((t) => escapeHtml(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!valid.length) return esc
  return esc.replace(new RegExp(`(${valid.join('|')})`, 'gi'), '<mark>$1</mark>')
}

async function runSearch() {
  const q = keyword.value.trim()
  if (!q) {
    hits.value = []
    return
  }
  const mySeq = ++seq
  loading.value = true
  try {
    const res = await searchApi.search({ query: q, mode: 'hybrid', top_k: 8 })
    if (mySeq !== seq) return
    hits.value = res.hits
    activeIndex.value = 0
  } catch {
    if (mySeq === seq) hits.value = []
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch(keyword, () => {
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(runSearch, 250)
})

onBeforeUnmount(() => {
  // 组件卸载后仍在排队的防抖搜索必须取消，否则会向已销毁组件写入响应式状态
  if (timer !== null) window.clearTimeout(timer)
  timer = null
})

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      keyword.value = ''
      hits.value = []
      activeIndex.value = 0
      await nextTick()
      inputEl.value?.focus()
    }
  },
)
</script>

<style scoped>
.cp-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  background: rgba(31, 35, 40, 0.32);
  display: flex;
  justify-content: center;
  padding-top: 12vh;
}

.cp-panel {
  width: min(620px, 92vw);
  max-height: 62vh;
  display: flex;
  flex-direction: column;
  background: var(--kh-panel);
  border: 1px solid var(--kh-border);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.cp-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--kh-border-light);
}

.cp-head-icon {
  color: var(--kh-text-mute);
  font-size: 16px;
}

.cp-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-family: inherit;
  font-size: 15px;
  color: var(--kh-text);
}

.cp-kbd,
.cp-foot b {
  font-size: 11px;
  color: var(--kh-text-mute);
  background: var(--kh-bg-deep);
  border-radius: 4px;
  padding: 1px 6px;
}

.cp-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.cp-label {
  font-size: 11.5px;
  color: var(--kh-text-mute);
  padding: 6px 10px;
}

.cp-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  border-radius: 8px;
  padding: 9px 11px;
  cursor: pointer;
  font-family: inherit;
  color: var(--kh-text);
}

.cp-item.active {
  background: var(--kh-primary-soft);
}

.cp-item-icon {
  color: var(--kh-text-sub);
}

.cp-item-main {
  min-width: 0;
  flex: 1;
}

.cp-title {
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cp-sub {
  color: var(--kh-text-mute);
  font-size: 12px;
}

.cp-snippet {
  font-size: 12px;
  color: var(--kh-text-sub);
  line-height: 1.6;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cp-snippet :deep(mark) {
  background: #fff2ba;
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}

.cp-empty {
  padding: 26px 0;
  text-align: center;
  color: var(--kh-text-mute);
  font-size: 12.5px;
}

.cp-foot {
  display: flex;
  gap: 16px;
  padding: 9px 16px;
  border-top: 1px solid var(--kh-border-light);
  font-size: 11.5px;
  color: var(--kh-text-mute);
}
</style>
