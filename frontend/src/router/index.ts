import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      redirect: '/workbench',
      children: [
        {
          path: 'workbench',
          name: 'workbench',
          component: () => import('@/views/WorkbenchView.vue'),
          meta: { title: '知识工作台', icon: 'HomeFilled' },
        },
        {
          path: 'documents',
          name: 'documents',
          component: () => import('@/views/DocumentsView.vue'),
          meta: { title: '文档管理', icon: 'Document' },
        },
        {
          path: 'documents/:id',
          name: 'document-detail',
          component: () => import('@/views/DocumentDetailView.vue'),
          meta: { title: '文档详情', hidden: true },
        },
        {
          path: 'upload',
          name: 'upload',
          component: () => import('@/views/UploadView.vue'),
          meta: { title: '导入文档', icon: 'UploadFilled' },
        },
        {
          path: 'categories',
          name: 'categories',
          component: () => import('@/views/CategoriesView.vue'),
          meta: { title: '分类管理', icon: 'FolderOpened' },
        },
        {
          path: 'tags',
          name: 'tags',
          component: () => import('@/views/TagsView.vue'),
          meta: { title: '标签管理', icon: 'PriceTag' },
        },
        {
          path: 'glossary',
          name: 'glossary',
          component: () => import('@/views/GlossaryView.vue'),
          meta: { title: '术语词典', icon: 'Notebook' },
        },
        {
          path: 'search',
          name: 'search',
          component: () => import('@/views/SearchView.vue'),
          meta: { title: '知识检索', icon: 'Search' },
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/ChatView.vue'),
          meta: { title: 'AI 问答', icon: 'ChatDotRound' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: '系统设置', icon: 'Setting' },
        },
        {
          path: 'data',
          name: 'data',
          component: () => import('@/views/DataView.vue'),
          meta: { title: '数据与备份', icon: 'Coin' },
        },
        {
          path: 'extensions',
          name: 'extensions',
          component: () => import('@/views/ExtensionsView.vue'),
          meta: { title: '后续扩展', icon: 'Grid' },
        },
      ],
    },
  ],
})

export default router
