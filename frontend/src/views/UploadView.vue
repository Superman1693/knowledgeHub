<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">导入文档</h1>
        <p class="page-sub">
          支持 Markdown、文本、PDF、Word、代码等多种格式，拖拽即可导入；
          截图（PNG/JPG）会自动 OCR 识别其中的文字
        </p>
      </div>
    </div>

    <!-- 网页剪藏：看到好文章直接存进来，不必复制粘贴（格式会乱、且脱离知识库） -->
    <div class="card">
      <div class="section-title">从网页剪藏</div>
      <div class="clip-row">
        <el-input
          v-model="clipUrl"
          placeholder="粘贴网页链接，例如 https://example.com/article"
          clearable
          :disabled="clipping"
          @keydown.enter="submitClip"
        />
        <el-button type="primary" :loading="clipping" :disabled="!clipUrl.trim()" @click="submitClip">
          剪藏
        </el-button>
      </div>
      <div class="hint mt-sm">
        自动提取正文并转为 Markdown，标题与来源地址一并保留。
        只支持公开网页（<strong>不允许指向内网或本机地址</strong>），
        需登录或纯前端渲染的页面可能取不到正文。
      </div>
      <div v-if="clipError" class="clip-error">{{ clipError }}</div>
    </div>

    <div class="card mt">
      <el-upload
        drag
        multiple
        :auto-upload="false"
        :show-file-list="true"
        :file-list="fileList"
        :on-change="onChange"
        :on-remove="onRemove"
        :limit="50"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">把文件拖到这里，或<em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">
            单个文件不超过 {{ maxMb }} MB。重复文件会给出提示但不会自动覆盖。
          </div>
        </template>
      </el-upload>

      <div class="mt">
        <el-button type="primary" :loading="uploading" :disabled="!fileList.length" @click="submit">
          开始导入（{{ fileList.length }} 个文件）
        </el-button>
        <el-button @click="fileList = []">清空</el-button>
      </div>
    </div>

    <div v-if="results.length" class="card mt">
      <div class="section-title">导入结果</div>
      <el-table :data="results" size="small">
        <el-table-column prop="title" label="文件" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="重复提示" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.duplicate_warning" type="warning" size="small">疑似重复</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="$router.push(`/documents/${row.id}`)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-alert
        class="mt-sm"
        type="info"
        :closable="false"
        title="文档正在后台解析与建立索引，状态会从「等待」变为「已索引」。若嵌入模型不可用，状态会显示为「失败」，可稍后在文档管理中重建索引。"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile, UploadFiles } from 'element-plus'
import { documentsApi, settingsApi } from '@/api'
import type { DocStatus } from '@/api/types'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const fileList = ref<UploadFiles>([])
const uploading = ref(false)
const maxMb = ref(50)

interface ResultRow {
  id: string
  title: string
  status: DocStatus
  duplicate_warning: boolean
}

const results = ref<ResultRow[]>([])

// ---------------- 网页剪藏 ----------------
const clipUrl = ref('')
const clipping = ref(false)
const clipError = ref('')

async function submitClip() {
  const url = clipUrl.value.trim()
  if (!url) return
  clipping.value = true
  clipError.value = ''
  try {
    const doc = await documentsApi.clipFromUrl(url)
    ElMessage.success(`已剪藏《${doc.title}》`)
    clipUrl.value = ''
  } catch (e: any) {
    // 后端对「已剪藏过」「内网地址」「取不到正文」都给了可读提示，
    // 这里原样展示在卡片内而不是只弹 toast——用户需要照着提示改 URL
    clipError.value =
      e?.response?.data?.message || e?.response?.data?.detail || '剪藏失败，请检查链接'
  } finally {
    clipping.value = false
  }
}

// 轮询定时器放在组件作用域，便于卸载时清理（否则离开页面后仍会持续请求）
let pollTimer: number | null = null

function onChange(_file: UploadFile, files: UploadFiles) {
  fileList.value = files
}
function onRemove(_file: UploadFile, files: UploadFiles) {
  fileList.value = files
}

async function submit() {
  const raw = fileList.value.map((f) => f.raw).filter(Boolean) as File[]
  if (!raw.length) return
  uploading.value = true
  try {
    const res = await documentsApi.upload(raw)
    results.value = res.items.map((it) => ({
      id: it.document.id,
      title: it.document.title,
      status: it.document.status,
      duplicate_warning: it.duplicate_warning,
    }))
    ElMessage.success(`已提交 ${raw.length} 个文件，正在后台处理`)
    fileList.value = []
    poll()
  } finally {
    uploading.value = false
  }
}

/** 轮询刷新处理状态。 */
function poll() {
  let rounds = 0
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    rounds += 1
    let allDone = true
    for (const row of results.value) {
      try {
        const doc = await documentsApi.get(row.id)
        row.status = doc.status
        if (doc.status === 'pending' || doc.status === 'processing') allDone = false
      } catch {
        /* ignore */
      }
    }
    if (allDone || rounds > 60) {
      if (pollTimer !== null) window.clearInterval(pollTimer)
      pollTimer = null
    }
  }, 2000)
}

onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = null
})

onMounted(async () => {
  try {
    const s = await settingsApi.get()
    maxMb.value = s.max_upload_mb
  } catch {
    /* 使用默认值 */
  }
})
</script>

<style scoped>
.section-title {
  font-weight: 600;
  margin-bottom: 12px;
}
.mt {
  margin-top: 16px;
}
.mt-sm {
  margin-top: 12px;
}

/* ---------------- 网页剪藏 ---------------- */
.clip-row {
  display: flex;
  gap: 10px;
}

.clip-error {
  margin-top: 10px;
  padding: 8px 11px;
  border-radius: 6px;
  background: #fdf0f0;
  border: 1px solid #f2c9c9;
  color: #a32d2d;
  font-size: 12.5px;
  line-height: 1.6;
}

/* 窄屏：输入框与按钮堆叠，按钮撑满 */
@media (max-width: 860px) {
  .clip-row {
    flex-direction: column;
  }
}
</style>
