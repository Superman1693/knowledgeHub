<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="brand">
        <span class="brand-mark">KH</span>
        <div class="brand-text">
          <div class="brand-name">KnowledgeHub</div>
          <div class="brand-sub">本地个人知识库</div>
        </div>
      </div>
      <el-menu :default-active="activePath" router class="menu">
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">{{ currentTitle }}</div>
        <div class="header-status">
          <el-tag :type="health.database_ok ? 'success' : 'danger'" size="small" effect="plain">
            数据库：{{ health.database_ok ? '正常' : '异常' }}
          </el-tag>
          <el-tag size="small" effect="plain" type="info">存储：{{ health.storage_mode }}</el-tag>
          <el-tag size="small" effect="plain" type="warning">AI：{{ health.ai_mode }}</el-tag>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { systemApi } from '@/api'
import type { HealthOut } from '@/api/types'

const route = useRoute()

const menuItems = [
  { path: '/workbench', title: '知识工作台', icon: 'HomeFilled' },
  { path: '/documents', title: '文档管理', icon: 'Document' },
  { path: '/upload', title: '导入文档', icon: 'UploadFilled' },
  { path: '/categories', title: '分类管理', icon: 'FolderOpened' },
  { path: '/tags', title: '标签管理', icon: 'PriceTag' },
  { path: '/glossary', title: '术语词典', icon: 'Notebook' },
  { path: '/search', title: '知识检索', icon: 'Search' },
  { path: '/chat', title: 'AI 问答', icon: 'ChatDotRound' },
  { path: '/settings', title: '系统设置', icon: 'Setting' },
  { path: '/data', title: '数据与备份', icon: 'Coin' },
  { path: '/extensions', title: '后续扩展', icon: 'Grid' },
]

const health = ref<HealthOut>({
  status: 'unknown',
  database_ok: false,
  database_message: '',
  storage_mode: '-',
  ai_mode: '-',
  data_dir: '',
})

const activePath = computed(() => {
  const p = route.path
  const match = menuItems.find((m) => p === m.path || p.startsWith(m.path + '/'))
  return match?.path ?? p
})

const currentTitle = computed(() => (route.meta.title as string) ?? '')

onMounted(async () => {
  try {
    health.value = await systemApi.health()
  } catch {
    /* 状态获取失败不阻塞页面 */
  }
})
</script>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  background: #fff;
  border-right: 1px solid var(--kh-border);
  display: flex;
  flex-direction: column;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px 14px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #409eff;
  color: #fff;
  display: grid;
  place-items: center;
  font-weight: 700;
  font-size: 13px;
}

.brand-name {
  font-weight: 600;
  font-size: 15px;
}

.brand-sub {
  color: var(--kh-text-sub);
  font-size: 12px;
}

.menu {
  border-right: none;
  flex: 1;
  overflow: auto;
}

.header {
  background: #fff;
  border-bottom: 1px solid var(--kh-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.header-status {
  display: flex;
  gap: 8px;
}

.main {
  padding: 0;
  overflow: auto;
  background: var(--kh-bg);
}
</style>
