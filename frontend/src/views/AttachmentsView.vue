<template>
  <div class="att">
    <header class="att-head">
      <div>
        <h2 class="att-title">附件管理</h2>
        <p class="att-desc">
          笔记里插入的图片与文件都存放在这里。可以预览、复制 Markdown 引用复用到别的笔记，
          或删除不再需要的附件（删除后正文里的引用会失效，请先确认没有笔记在使用）。
        </p>
      </div>
      <div class="att-actions">
        <el-button :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
        <el-button type="primary" :loading="uploading" @click="pick">
          <el-icon><UploadFilled /></el-icon>
          <span>上传附件</span>
        </el-button>
        <input
          ref="fileEl"
          type="file"
          multiple
          hidden
          @change="onFiles"
        />
      </div>
    </header>

    <div class="att-bar">
      <el-radio-group v-model="filter" size="small">
        <el-radio-button value="all">全部 {{ items.length }}</el-radio-button>
        <el-radio-button value="image">图片 {{ imageCount }}</el-radio-button>
        <el-radio-button value="file">其它 {{ items.length - imageCount }}</el-radio-button>
      </el-radio-group>
      <span class="att-total">共占用 {{ sizeText(totalBytes) }}</span>
    </div>

    <div v-loading="loading" class="att-body">
      <div v-if="!shown.length && !loading" class="att-empty">
        <el-icon><Picture /></el-icon>
        <span>还没有附件。在编辑器里粘贴截图，或点右上角「上传附件」。</span>
      </div>

      <div v-else class="att-grid">
        <div v-for="a in shown" :key="a.url" class="att-card">
          <div class="att-thumb">
            <img v-if="isImage(a)" :src="a.url" :alt="a.name" loading="lazy" />
            <el-icon v-else class="att-file-icon"><Document /></el-icon>
          </div>
          <div class="att-info">
            <div class="att-name" :title="a.name">{{ a.name }}</div>
            <div class="att-meta">{{ sizeText(a.size) }} · {{ a.sub === 'images' ? '图片' : '文件' }}</div>
          </div>
          <div class="att-ops">
            <el-button size="small" text @click="open(a)">
              <el-icon><View /></el-icon>
            </el-button>
            <el-button size="small" text @click="copyRef(a)">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
            <el-button size="small" text type="danger" @click="remove(a)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { attachmentsApi } from '@/api'
import type { AttachmentOut } from '@/api/types'

const items = ref<AttachmentOut[]>([])
const loading = ref(false)
const uploading = ref(false)
const filter = ref<'all' | 'image' | 'file'>('all')
const fileEl = ref<HTMLInputElement | null>(null)

/** 图片按扩展名判断（与后端 IMAGE_EXTENSIONS 一致的子集）。 */
const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'avif', 'ico']

function isImage(a: AttachmentOut) {
  const ext = a.name.split('.').pop()?.toLowerCase() ?? ''
  return IMAGE_EXT.includes(ext)
}

const imageCount = computed(() => items.value.filter(isImage).length)
const totalBytes = computed(() => items.value.reduce((s, a) => s + a.size, 0))
const shown = computed(() =>
  items.value.filter((a) =>
    filter.value === 'all' ? true : filter.value === 'image' ? isImage(a) : !isImage(a),
  ),
)

function sizeText(bytes: number) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  try {
    const res = await attachmentsApi.list()
    items.value = res.items
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

function pick() {
  fileEl.value?.click()
}

async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (!files.length) return
  uploading.value = true
  let ok = 0
  try {
    for (const f of files) {
      try {
        await attachmentsApi.upload(f)
        ok += 1
      } catch {
        /* 单文件失败不影响其余；错误提示由请求层统一弹出 */
      }
    }
    if (ok) ElMessage.success(`已上传 ${ok} 个附件`)
    await load()
  } finally {
    uploading.value = false
    input.value = '' // 允许重复选择同一文件
  }
}

function open(a: AttachmentOut) {
  window.open(a.url, '_blank', 'noopener')
}

async function copyRef(a: AttachmentOut) {
  const label = a.name.replace(/\.[^.]+$/, '') || a.name
  const md = isImage(a) ? `![${label}](${a.url})` : `[${label}](${a.url})`
  try {
    await navigator.clipboard.writeText(md)
    ElMessage.success('已复制 Markdown 引用，可直接粘贴到笔记里')
  } catch {
    // 剪贴板不可用（非 https / 浏览器限制）时降级为提示，不静默失败
    ElMessage.warning(`复制失败，请手动复制：${md}`)
  }
}

async function remove(a: AttachmentOut) {
  try {
    await ElMessageBox.confirm(
      `删除附件「${a.name}」？引用它的笔记会显示为失效链接，且无法恢复。`,
      '删除确认',
      { type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  await attachmentsApi.remove(a.sub, a.name)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.att {
  padding: 22px 26px;
  height: 100vh;
  overflow-y: auto;
  background: var(--kh-bg);
}

.att-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.att-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 6px;
}

.att-desc {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.7;
  margin: 0;
  max-width: 640px;
}

.att-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.att-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.att-total {
  font-size: 12px;
  color: var(--kh-text-mute);
}

.att-body {
  min-height: 200px;
}

.att-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 70px 0;
  color: var(--kh-text-mute);
  font-size: 13px;
  text-align: center;
}

.att-empty .el-icon {
  font-size: 28px;
}

.att-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.att-card {
  background: var(--kh-panel);
  border: 1px solid var(--kh-border-light);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.att-thumb {
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--kh-bg);
  border-bottom: 1px solid var(--kh-border-light);
  overflow: hidden;
}

.att-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.att-file-icon {
  font-size: 32px;
  color: var(--kh-text-mute);
}

.att-info {
  padding: 8px 10px 4px;
  min-width: 0;
}

.att-name {
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.att-meta {
  font-size: 11px;
  color: var(--kh-text-mute);
  margin-top: 2px;
}

.att-ops {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
  padding: 0 6px 6px;
}
</style>
