<template>
  <div class="layout">
    <!-- ============ 侧边栏 ============ -->
    <aside class="sidebar" :class="{ 'is-open': drawerOpen }">
      <div class="brand">
        <div class="brand-mark">KH</div>
        <div class="brand-text">
          <div class="brand-name">KnowledgeHub</div>
          <div class="brand-sub">本地个人知识库</div>
        </div>
        <!-- 窄屏关闭按钮：宽屏下隐藏 -->
        <button
          class="sidebar-close"
          type="button"
          aria-label="关闭导航菜单"
          @click="drawerOpen = false"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <nav class="nav">
        <div v-for="group in menuGroups" :key="group.label" class="nav-group">
          <div class="nav-group-label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: activePath === item.path }"
          >
            <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
            <span class="nav-text">{{ item.title }}</span>
            <span v-if="item.path === '/chat' && status.failed > 0" class="nav-dot is-warning" />
          </router-link>
        </div>
      </nav>

      <div class="sidebar-foot">
        <el-popover placement="right-end" :width="272" trigger="click">
          <template #reference>
            <button class="status-pill" type="button">
              <span class="status-dot" :class="statusDotClass" />
              <span class="status-text">{{ statusText }}</span>
              <el-icon class="status-more"><ArrowRight /></el-icon>
            </button>
          </template>

          <div class="status-panel">
            <div class="status-panel-title">运行状态</div>
            <div class="status-row">
              <span class="status-row-label">数据库</span>
              <el-tag :type="health.database_ok ? 'success' : 'danger'" size="small" effect="light">
                {{ health.database_ok ? '连接正常' : '连接异常' }}
              </el-tag>
            </div>
            <div class="status-row">
              <span class="status-row-label">存储模式</span>
              <span class="status-row-value">{{ health.storage_mode }}</span>
            </div>
            <div class="status-row">
              <span class="status-row-label">AI 模式</span>
              <span class="status-row-value">{{ health.ai_mode }}</span>
            </div>
            <div class="status-row is-block">
              <span class="status-row-label">数据目录</span>
              <code class="status-path">{{ health.data_dir || '-' }}</code>
            </div>
            <div v-if="!health.database_ok && health.database_message" class="status-err">
              {{ health.database_message }}
            </div>
          </div>
        </el-popover>

        <div class="version">
          <span>v0.1.0 · 数据全部保存在本机</span>
          <el-tooltip
            :content="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
            placement="top"
          >
            <button class="theme-toggle" type="button" @click="toggleTheme">
              <el-icon>
                <Moon v-if="theme === 'light'" />
                <Sunny v-else />
              </el-icon>
              <span>{{ theme === 'dark' ? '浅色' : '深色' }}</span>
            </button>
          </el-tooltip>
        </div>
      </div>
    </aside>

    <!-- ============ 内容区 ============ -->
    <main class="content">
      <!-- 窄屏菜单按钮：宽屏下隐藏（侧栏常驻）。放这里而不是侧栏里，
           否则侧栏收起后就没有入口能再打开了。 -->
      <button
        class="menu-toggle"
        type="button"
        aria-label="打开导航菜单"
        @click="drawerOpen = true"
      >
        <el-icon><Menu /></el-icon>
      </button>

      <!-- :key 用 fullPath：否则在 /documents/A → /documents/B 这类「同路由仅参数变化」
           的跳转中组件会被复用，页面数据不会重新加载 -->
      <router-view :key="route.fullPath" />
    </main>

    <!-- 窄屏遮罩：点击空白处关闭侧栏 -->
    <div
      v-if="drawerOpen"
      class="drawer-mask"
      @click="drawerOpen = false"
    />

    <!-- 全局快捷搜索 / 跳转（Ctrl/Cmd + K） -->
    <CommandPalette v-model="paletteOpen" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { systemApi, settingsApi } from '@/api'
import type { HealthOut } from '@/api/types'
import CommandPalette from '@/components/CommandPalette.vue'

const route = useRoute()
/** 快捷搜索面板开关（Ctrl/Cmd + K） */
const paletteOpen = ref(false)
/** 窄屏侧栏抽屉开关（宽屏下侧栏常驻，此状态无意义） */
const drawerOpen = ref(false)

// 窄屏点完导航要自动收起抽屉：否则侧栏盖住内容，用户以为页面没跳转
watch(
  () => route.fullPath,
  () => {
    drawerOpen.value = false
  },
)

// ---------------- 明暗主题 ----------------
type Theme = 'light' | 'dark'
const THEME_KEY = 'kh-theme'
const theme = ref<Theme>('light')

function applyTheme(next: Theme) {
  theme.value = next
  // 深色时在 <html> 上打标记，styles.css 的 [data-theme='dark'] 生效
  if (next === 'dark') document.documentElement.dataset.theme = 'dark'
  else delete document.documentElement.dataset.theme
  try {
    localStorage.setItem(THEME_KEY, next)
  } catch {
    /* 隐私模式下可能不可用，忽略 */
  }
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

/** 首次进入：优先用本地偏好，其次跟随系统。 */
function initTheme() {
  let saved: string | null = null
  try {
    saved = localStorage.getItem(THEME_KEY)
  } catch {
    saved = null
  }
  if (saved === 'dark' || saved === 'light') {
    applyTheme(saved)
    return
  }
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
  applyTheme(prefersDark ? 'dark' : 'light')
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = true
  }
}

interface MenuItem {
  path: string
  title: string
  icon: string
}

interface MenuGroup {
  label: string
  items: MenuItem[]
}

/** 按使用频率与心智模型分组，降低新用户寻找成本 */
const menuGroups: MenuGroup[] = [
  {
    label: '知识库',
    items: [
      { path: '/workbench', title: '工作台', icon: 'HomeFilled' },
      { path: '/notes/new', title: '新建笔记', icon: 'EditPen' },
      { path: '/documents', title: '文档管理', icon: 'Document' },
      { path: '/upload', title: '导入文档', icon: 'UploadFilled' },
    ],
  },
  {
    label: '整理',
    items: [
      { path: '/categories', title: '分类', icon: 'FolderOpened' },
      { path: '/tags', title: '标签', icon: 'PriceTag' },
      { path: '/glossary', title: '术语词典', icon: 'Notebook' },
      { path: '/attachments', title: '附件管理', icon: 'Picture' },
      { path: '/trash', title: '回收站', icon: 'Delete' },
    ],
  },
  {
    label: '使用',
    items: [
      { path: '/chat', title: 'AI 问答', icon: 'ChatDotRound' },
      { path: '/search', title: '知识检索', icon: 'Search' },
      { path: '/graph', title: '知识图谱', icon: 'Share' },
    ],
  },
  {
    label: '扩展能力',
    items: [
      { path: '/insights', title: '知识加工', icon: 'MagicStick' },
      { path: '/learning', title: '学习辅助', icon: 'Reading' },
      { path: '/devhelper', title: '开发辅助', icon: 'Tools' },
    ],
  },
  {
    label: '系统',
    items: [
      { path: '/settings', title: '系统设置', icon: 'Setting' },
      { path: '/data', title: '数据与备份', icon: 'Coin' },
      { path: '/extensions', title: '扩展总览', icon: 'Grid' },
    ],
  },
]

const health = ref<HealthOut>({
  status: 'unknown',
  database_ok: false,
  database_message: '',
  storage_mode: '-',
  ai_mode: '-',
  data_dir: '',
})

/** 处理失败的文档数，用于侧栏提醒（复用工作台接口） */
const status = ref({ failed: 0 })

const activePath = computed(() => {
  const p = route.path
  for (const group of menuGroups) {
    for (const item of group.items) {
      if (p === item.path || p.startsWith(item.path + '/')) return item.path
    }
  }
  return p
})

const statusDotClass = computed(() => {
  if (!health.value.database_ok) return 'is-danger'
  if (health.value.ai_mode === 'external' || health.value.ai_mode === 'local') return 'is-success'
  return 'is-idle'
})

const statusText = computed(() => {
  if (!health.value.database_ok) return '数据库异常'
  return '运行正常'
})

onMounted(async () => {
  initTheme()
  window.addEventListener('keydown', onGlobalKeydown)
  try {
    health.value = await systemApi.health()
  } catch {
    /* 状态获取失败不阻塞页面 */
  }
  try {
    const s = await settingsApi.indexStatus()
    status.value = { failed: s.failed }
  } catch {
    /* 忽略 */
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  background: var(--kh-bg);
}

/* ---------------- 侧边栏 ---------------- */
.sidebar {
  width: var(--kh-sidebar-w);
  flex-shrink: 0;
  background: var(--kh-panel);
  border-right: 1px solid var(--kh-border);
  display: flex;
  flex-direction: column;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 20px 18px 18px;
}

.brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--kh-primary) 0%, #6b7ce8 100%);
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 0.02em;
  box-shadow: 0 3px 10px rgba(74, 95, 214, 0.28);
  flex-shrink: 0;
}

.brand-name {
  font-weight: 650;
  font-size: 14.5px;
  line-height: 1.3;
}

.brand-sub {
  color: var(--kh-text-mute);
  font-size: 11.5px;
  line-height: 1.4;
}

/* ---------------- 导航 ---------------- */
.nav {
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px 12px;
}

.nav-group + .nav-group {
  margin-top: 14px;
}

.nav-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--kh-text-mute);
  letter-spacing: 0.08em;
  padding: 6px 10px 6px;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  color: var(--kh-text-sub);
  text-decoration: none;
  font-size: 13.5px;
  transition: background 0.15s ease, color 0.15s ease;
  margin-bottom: 2px;
}

.nav-item:hover {
  background: var(--kh-bg);
  color: var(--kh-text);
}

.nav-item.active {
  background: var(--kh-primary-soft);
  color: var(--kh-primary);
  font-weight: 600;
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 18px;
  border-radius: 0 3px 3px 0;
  background: var(--kh-primary);
}

.nav-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.nav-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.nav-dot.is-warning {
  background: var(--kh-warning);
}

/* ---------------- 侧栏底部 ---------------- */
.sidebar-foot {
  border-top: 1px solid var(--kh-border-light);
  padding: 12px 12px 14px;
}

.status-pill {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 11px;
  border: 1px solid var(--kh-border);
  background: var(--kh-bg);
  border-radius: 8px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--kh-text-sub);
  transition: border-color 0.15s ease, background 0.15s ease;
}

.status-pill:hover {
  border-color: var(--kh-primary-border);
  background: var(--kh-primary-soft);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.is-success {
  background: var(--kh-success);
  box-shadow: 0 0 0 3px rgba(47, 158, 110, 0.16);
}
.status-dot.is-danger {
  background: var(--kh-danger);
  box-shadow: 0 0 0 3px rgba(207, 91, 86, 0.16);
}
.status-dot.is-idle {
  background: var(--kh-text-mute);
}

.status-text {
  flex: 1;
  text-align: left;
}

.status-more {
  font-size: 12px;
  color: var(--kh-text-mute);
}

.version {
  margin-top: 10px;
  font-size: 11px;
  color: var(--kh-text-mute);
  text-align: center;
  line-height: 1.5;
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 7px;
  padding: 3px 10px;
  border: 1px solid var(--kh-border);
  border-radius: 999px;
  background: var(--kh-panel);
  color: var(--kh-text-sub);
  font-family: inherit;
  font-size: 11.5px;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.theme-toggle:hover {
  border-color: var(--kh-primary-border);
  color: var(--kh-primary);
  background: var(--kh-primary-soft);
}

/* ---------------- 状态面板 ---------------- */
.status-panel-title {
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 12px;
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 0;
  font-size: 13px;
}

.status-row.is-block {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.status-row-label {
  color: var(--kh-text-sub);
}

.status-row-value {
  font-weight: 500;
}

.status-path {
  font-size: 11.5px;
  color: var(--kh-text-sub);
  background: var(--kh-bg);
  border: 1px solid var(--kh-border-light);
  border-radius: 5px;
  padding: 4px 7px;
  word-break: break-all;
  width: 100%;
  font-family: 'Cascadia Code', Consolas, Monaco, monospace;
}

.status-err {
  margin-top: 8px;
  font-size: 12px;
  color: var(--kh-danger);
  background: var(--kh-danger-soft);
  border-radius: 6px;
  padding: 7px 9px;
  line-height: 1.55;
}

/* ---------------- 内容区 ---------------- */
.content {
  flex: 1;
  overflow: auto;
  min-width: 0;
}

/* ---------------- 窄屏菜单按钮（宽屏隐藏） ---------------- */
.menu-toggle {
  display: none;
  position: sticky;
  top: 0;
  z-index: 5;
  margin: 0 0 4px;
  padding: 6px 10px;
  border: 1px solid var(--kh-border);
  border-radius: 8px;
  background: var(--kh-panel);
  color: var(--kh-text-sub);
  cursor: pointer;
  line-height: 1;
}

.menu-toggle:hover {
  color: var(--kh-primary);
  border-color: var(--kh-primary-border);
}

.sidebar-close {
  display: none;
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--kh-text-sub);
  cursor: pointer;
  padding: 4px;
  line-height: 1;
}

.drawer-mask {
  display: none;
}

/* ---------------- 窄屏：侧栏变成抽屉 ---------------- */
@media (max-width: 860px) {
  .menu-toggle {
    display: inline-flex;
    align-items: center;
  }

  .sidebar-close {
    display: inline-flex;
    align-items: center;
  }

  /* 侧栏滑出屏幕外，靠 transform 位移（比 display 切换多一层动画，
     且不脱离文档流导致内容跳动） */
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 40;
    transform: translateX(-100%);
    transition: transform 0.24s ease;
    box-shadow: none;
  }

  .sidebar.is-open {
    transform: translateX(0);
    box-shadow: 0 0 40px rgba(0, 0, 0, 0.18);
  }

  .drawer-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 30;
    background: rgba(0, 0, 0, 0.32);
  }

  /* 内容区不再给侧栏留位，撑满可用宽度。
     不加 padding：各页面的 .page 自带内边距，这里再加会双重缩进。 */
  .content {
    width: 100%;
  }
}
</style>
