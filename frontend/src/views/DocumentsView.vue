<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">文档管理</h1>
        <p class="page-sub">浏览、筛选、预览、删除与导出你的本地文档</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" @click="$router.push('/notes/new')">
          <el-icon><EditPen /></el-icon>
          <span>新建笔记</span>
        </el-button>
        <el-button @click="exportAll">
          <el-icon><Download /></el-icon>
          <span>整库导出</span>
        </el-button>
        <el-button @click="siteExportOpen = true">
          <el-icon><Monitor /></el-icon>
          <span>导出静态站</span>
        </el-button>
        <el-button @click="$router.push('/upload')">
          <el-icon><UploadFilled /></el-icon>
          <span>导入文档</span>
        </el-button>
      </div>
    </div>

    <div class="card toolbar">
      <el-radio-group v-model="filters.view" size="small" @change="onViewChange">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="favorite">收藏</el-radio-button>
        <el-radio-button value="pinned">置顶</el-radio-button>
        <el-radio-button value="recent">最近访问</el-radio-button>
        <el-radio-button value="note">我的笔记</el-radio-button>
      </el-radio-group>
    </div>

    <div class="card toolbar mt">
      <el-input v-model="filters.q" placeholder="搜索标题 / 文件名" clearable style="width: 220px" @keyup.enter="reload" />
      <el-select v-model="filters.category_id" placeholder="全部分类" clearable style="width: 160px" @change="reload">
        <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-select v-model="filters.tag" placeholder="全部标签" clearable style="width: 150px" @change="reload">
        <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.name" />
      </el-select>
      <el-select v-model="filters.sort" style="width: 150px" @change="reload">
        <el-option label="按更新时间" value="updated_at" />
        <el-option label="按创建时间" value="created_at" />
      </el-select>
      <el-button type="primary" @click="reload"><el-icon><Search /></el-icon>查询</el-button>
    </div>

    <div class="card mt">
      <!-- 批量操作条：勾选后才出现，避免长期占用视觉空间 -->
      <div v-if="selected.length" class="batch-bar">
        <span class="batch-count">已选 {{ selected.length }} 篇</span>
        <el-button size="small" @click="batch('favorite', { value: true })">收藏</el-button>
        <el-button size="small" @click="batch('favorite', { value: false })">取消收藏</el-button>
        <el-button size="small" @click="batch('pin', { value: true })">置顶</el-button>
        <el-button size="small" @click="batch('pin', { value: false })">取消置顶</el-button>
        <el-select
          v-model="batchCategory"
          placeholder="移动分类"
          size="small"
          clearable
          style="width: 150px"
          @change="onBatchMove"
        >
          <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button size="small" @click="batchTag">打标签</el-button>
        <el-button size="small" type="danger" plain @click="batchRemove">移入回收站</el-button>
        <el-button size="small" link @click="clearSelection">取消选择</el-button>
      </div>

      <el-table
        ref="tableEl"
        :data="items"
        v-loading="loading"
        size="default"
        row-key="id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="" width="78" align="center">
          <template #default="{ row }">
            <el-tooltip :content="row.is_favorite ? '取消收藏' : '加入收藏'">
              <el-icon
                class="mark-icon"
                :class="{ 'is-on': row.is_favorite }"
                @click="toggleFavorite(row)"
              >
                <StarFilled v-if="row.is_favorite" />
                <Star v-else />
              </el-icon>
            </el-tooltip>
            <el-tooltip :content="row.is_pinned ? '取消置顶' : '置顶'">
              <el-icon
                class="mark-icon"
                :class="{ 'is-on': row.is_pinned }"
                @click="togglePinned(row)"
              >
                <Top />
              </el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" @click="$router.push(`/documents/${row.id}`)">{{ row.title }}</el-link>
            <el-tag v-if="row.source === 'note'" size="small" effect="plain" class="title-tag">笔记</el-tag>
            <el-tooltip v-if="row.ai_enabled === false" content="私密笔记：不进入 AI 检索范围">
              <el-tag size="small" type="info" effect="plain" class="title-tag">私密</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="file_type" label="类型" width="90" />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ (row.file_size / 1024).toFixed(1) }} KB</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip :disabled="!row.error_message" :content="row.error_message || ''">
              <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="片段" width="80" />
        <el-table-column prop="updated_at" label="更新时间" width="170">
          <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="272" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="isEditable(row)"
              link
              type="primary"
              size="small"
              @click="$router.push(`/notes/${row.id}/edit`)"
            >编辑</el-button>
            <el-button link type="primary" size="small" @click="reindex(row)">重建索引</el-button>
            <el-button link type="primary" size="small" @click="exportDoc(row)">导出</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <div class="empty-icon"><el-icon><FolderOpened /></el-icon></div>
            <div class="empty-title">
              {{ hasFilter ? '没有匹配的文档' : '还没有文档' }}
            </div>
            <div class="empty-desc">
              {{
                hasFilter
                  ? '试试换个关键词，或清空筛选条件重新查找。'
                  : '导入 Markdown、TXT、PDF、Word 或代码文件，系统会自动解析并建立索引。'
              }}
            </div>
            <el-button v-if="hasFilter" @click="resetFilters">清空筛选</el-button>
            <template v-else>
              <el-button type="primary" @click="$router.push('/notes/new')">
                <el-icon><EditPen /></el-icon> 新建笔记
              </el-button>
              <el-button @click="$router.push('/upload')">
                <el-icon><UploadFilled /></el-icon> 导入文档
              </el-button>
            </template>
          </div>
        </template>
      </el-table>

      <el-pagination
        class="mt"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="filters.page_size"
        :current-page="filters.page"
        @current-change="onPage"
      />
    </div>
  </div>
  <!-- 静态站导出：可离线打开、可直接托管（GitHub Pages / 内网静态服务） -->
  <el-dialog v-model="siteExportOpen" title="导出静态站" width="520px">
    <div class="site-export-body">
      <p>
        把全部笔记编译成一组 HTML（索引页 + 每篇一页 + 样式表），
        打包为 zip。解压后双击 <code>index.html</code> 即可离线阅读，
        也可以直接托管到任意静态服务器。
      </p>
      <ul>
        <li>双链 <code>[[标题]]</code> 会变成页面之间的真实链接</li>
        <li>指向未创建笔记的引用会保留虚线标记（不留死链）</li>
        <li>渲染复用应用自身的管线，<strong>样子与这里预览一致</strong></li>
      </ul>
      <el-checkbox v-model="siteIncludePrivate">
        包含私密笔记（{{ privateCount }} 篇）
      </el-checkbox>
      <div class="site-export-warn">
        <el-icon><WarningFilled /></el-icon>
        <span>
          静态站是拿来分享或发布的。私密笔记默认<strong>不导出</strong>——
          它们的「不进入 AI 检索」设定不代表可以公开。
          确需导出请显式勾选。
        </span>
      </div>
    </div>
    <template #footer>
      <el-button @click="siteExportOpen = false">取消</el-button>
      <el-button type="primary" :loading="siteExporting" @click="exportSite">
        生成并下载
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened, UploadFilled } from '@element-plus/icons-vue'
import { buildSiteZip } from '@/utils/staticSite'
import { categoriesApi, documentsApi, tagsApi } from '@/api'
import type { Category, DocumentOut, Tag } from '@/api/types'
import { docStatusText as statusText, docStatusType as statusType } from '@/utils/status'

const route = useRoute()
const loading = ref(false)
const items = ref<DocumentOut[]>([])
const total = ref(0)
const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])

const filters = reactive({
  q: '',
  category_id: null as string | null,
  tag: null as string | null,
  sort: 'updated_at',
  page: 1,
  page_size: 20,
  /** all | favorite | pinned | recent | note */
  view: 'all',
})

/** 可在应用内编辑的纯文本格式（二进制格式不回写磁盘，故不提供编辑入口）。 */
const TEXT_TYPES = new Set([
  'md', 'markdown', 'txt', 'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'htm', 'css',
  'json', 'yaml', 'yml', 'ini', 'toml', 'conf', 'cfg', 'env', 'java', 'go', 'rs',
  'c', 'cpp', 'h', 'hpp', 'cs', 'php', 'rb', 'sql', 'sh', 'bat', 'xml', 'csv', 'log',
])

function isEditable(row: DocumentOut): boolean {
  return TEXT_TYPES.has((row.file_type || '').toLowerCase())
}

function onViewChange() {
  filters.page = 1
  reload()
}

async function toggleFavorite(row: DocumentOut) {
  const next = !row.is_favorite
  const updated = await documentsApi.setFavorite(row.id, next)
  row.is_favorite = updated.is_favorite
}

async function togglePinned(row: DocumentOut) {
  const next = !row.is_pinned
  const updated = await documentsApi.setPinned(row.id, next)
  row.is_pinned = updated.is_pinned
  // 置顶会改变排序，重新拉取以体现顺序
  reload()
}

// ---------------- 静态站导出 ----------------
const siteExportOpen = ref(false)
const siteExporting = ref(false)
const siteIncludePrivate = ref(false)
/** 预取的全量数据：打开对话框时拉一次，导出时直接用，避免重复请求 */
const siteBundle = ref<Awaited<ReturnType<typeof documentsApi.siteBundle>> | null>(null)
const privateCount = computed(() => siteBundle.value?.excluded_private ?? 0)

async function loadSiteBundle() {
  siteBundle.value = null
  try {
    siteBundle.value = await documentsApi.siteBundle(true)
  } catch {
    /* 错误提示由拦截器统一处理 */
  }
}

watch(siteExportOpen, (open) => {
  if (open) {
    siteIncludePrivate.value = false
    void loadSiteBundle()
  }
})

async function exportSite() {
  const bundle = siteBundle.value
  if (!bundle) {
    ElMessage.warning('数据还没准备好，请稍候重试')
    return
  }
  siteExporting.value = true
  try {
    // 勾选框即时生效：数据里带 ai_enabled，本地过滤即可，无需再请求
    const chosen = siteIncludePrivate.value
      ? bundle.notes
      : bundle.notes.filter((n) => n.ai_enabled !== false)

    if (!chosen.length) {
      ElMessage.warning('没有可导出的笔记')
      return
    }

    const { bytes, noteCount, missingLinks, filename } = buildSiteZip(
      chosen.map((n) => ({
        id: n.id,
        title: n.title,
        content_text: n.content_text,
        category: n.category,
        tags: n.tags,
        updated_at: n.updated_at,
        source_url: n.source_url,
      })),
    )

    const blob = new Blob([bytes as unknown as BlobPart], { type: 'application/zip' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)

    const excluded = bundle.notes.length - chosen.length
    const parts = [`已导出静态站：${noteCount} 篇`]
    if (missingLinks) parts.push(`含 ${missingLinks} 处未创建的引用`)
    if (excluded) parts.push(`已排除 ${excluded} 篇私密笔记`)
    ElMessage.success(parts.join('，'))
    siteExportOpen.value = false
  } catch {
    /* 错误提示由拦截器统一处理 */
  } finally {
    siteExporting.value = false
  }
}

async function exportAll() {
  try {
    const res = await documentsApi.exportAll()
    ElMessage.success(
      `已导出 ${res.count} 篇到 ${res.path}（含 YAML front-matter，可直接迁移）`,
    )
  } catch {
    /* 错误提示由拦截器处理 */
  }
}

/** 是否处于筛选状态（用于区分「空库」与「无匹配结果」） */
const hasFilter = computed(
  () => Boolean(filters.q || filters.category_id || filters.tag),
)

function resetFilters() {
  filters.q = ''
  filters.category_id = null
  filters.tag = null
  filters.page = 1
  reload()
}

const fmt = (v: string) => new Date(v).toLocaleString('zh-CN')

async function reload() {
  loading.value = true
  try {
    const data = await documentsApi.list({ ...filters })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPage(p: number) {
  filters.page = p
  reload()
}

async function reindex(row: DocumentOut) {
  try {
    const res = await documentsApi.reindex(row.id)
    ElMessage.success(`重建完成，共 ${res.chunk_count} 个片段`)
    reload()
  } catch {
    reload()
  }
}

async function exportDoc(row: DocumentOut) {
  const res = await documentsApi.export(row.id, 'md')
  const blob = new Blob([res.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = res.filename
  a.click()
  URL.revokeObjectURL(url)
}

async function remove(row: DocumentOut) {
  await ElMessageBox.confirm(
    `《${row.title}》将被移入回收站（原文件与索引保留，可随时恢复）。是否继续？`,
    '移入回收站',
    { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' },
  )
  await documentsApi.remove(row.id)
  ElMessage.success('已移入回收站')
  reload()
}

// ---------------- 批量操作 ----------------
const tableEl = ref<{ clearSelection: () => void } | null>(null)
const selected = ref<DocumentOut[]>([])
const batchCategory = ref<string | null>(null)

function onSelectionChange(rows: DocumentOut[]) {
  selected.value = rows
}

function clearSelection() {
  tableEl.value?.clearSelection()
  selected.value = []
}

/** 执行批量操作，逐条处理结果如实反馈（后端不做整批回滚）。 */
async function runBatch(
  action: 'favorite' | 'pin' | 'move' | 'tag' | 'delete',
  extra: Record<string, unknown> = {},
) {
  if (!selected.value.length) return
  const res = await documentsApi.batch({
    action,
    ids: selected.value.map((d) => d.id),
    ...extra,
  })
  if (res.failed.length) {
    ElMessage.warning(
      `成功 ${res.ok_count} 篇，失败 ${res.failed.length} 篇：${res.failed[0].error}`,
    )
  } else {
    ElMessage.success(`已处理 ${res.ok_count} 篇`)
  }
  batchCategory.value = null
  await reload()
  clearSelection()
}

const batch = runBatch

function onBatchMove(v: string | null) {
  if (v) runBatch('move', { category_id: v })
}

async function batchRemove() {
  try {
    await ElMessageBox.confirm(
      `选中的 ${selected.value.length} 篇将被移入回收站（原文件与索引保留，可随时恢复）。是否继续？`,
      '批量移入回收站',
      { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await runBatch('delete')
}

async function batchTag() {
  // 改为「追加」语义：后端会保留原标签再并入新标签，
  // 避免批量操作不可逆地抹掉已有标签
  let res: { value: string }
  try {
    res = await ElMessageBox.prompt('输入要追加的标签（逗号或空格分隔）', '批量打标签', {
      inputPlaceholder: '如：Vue3, 性能优化',
    })
  } catch {
    return
  }
  const names = (res.value || '')
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!names.length) return
  await runBatch('tag', { tags: names })
}

/** 支持从「分类管理 / 标签管理」带筛选条件跳转过来。 */
function applyRouteFilters() {  if (route.query.category) filters.category_id = String(route.query.category)
  if (route.query.tag) filters.tag = String(route.query.tag)
  // 视图筛选（工作台「我的笔记 / 收藏」等统计卡跳转时携带）
  if (route.query.view) filters.view = String(route.query.view) as typeof filters.view
}

onMounted(async () => {
  const [cats, tgs] = await Promise.all([categoriesApi.list(), tagsApi.list()])
  categories.value = cats
  tags.value = tgs
  applyRouteFilters()
  await reload()
})

// 已停留在文档页时再次从分类/标签页跳转，同样生效
watch(
  () => route.query,
  () => {
    applyRouteFilters()
    reload()
  },
)
</script>

<style scoped>
.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--kh-border-light);
  background: var(--kh-bg);
  border-radius: 8px;
}

.batch-count {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  margin-right: 4px;
}

.toolbar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.mt {
  margin-top: 16px;
}
.mark-icon {
  font-size: 15px;
  color: var(--kh-text-mute);
  cursor: pointer;
  margin: 0 3px;
  transition: color 0.15s ease;
}
.mark-icon:hover {
  color: var(--kh-primary);
}
.mark-icon.is-on {
  color: #e6a23c;
}
.title-tag {
  margin-left: 6px;
  transform: scale(0.88);
}
/* ================= 静态站导出对话框 ================= */
.site-export-body p {
  margin: 0 0 10px;
  line-height: 1.7;
  color: var(--kh-text-sub);
  font-size: 13px;
}

.site-export-body ul {
  margin: 0 0 14px;
  padding-left: 18px;
  line-height: 1.8;
  color: var(--kh-text-sub);
  font-size: 13px;
}

.site-export-body code {
  background: var(--kh-bg-deep);
  border-radius: 3px;
  padding: 0 3px;
  font-size: 12px;
}

.site-export-warn {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-top: 12px;
  padding: 9px 11px;
  border-radius: 6px;
  background: #fdf8ef;
  border: 1px solid #e8d5b0;
  color: #8a5f1a;
  font-size: 12.5px;
  line-height: 1.65;
}

.site-export-warn .el-icon {
  margin-top: 2px;
  flex-shrink: 0;
}
</style>