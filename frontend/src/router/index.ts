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
          // PDF 阅读与批注。单独一个路由而不是嵌在详情页里：
          // 它是一个占满整屏的阅读器（自带滚动与侧栏），
          // 塞进详情页的卡片流里既挤又难用
          path: 'documents/:id/annotate',
          name: 'document-annotate',
          component: () => import('@/views/PdfAnnotateView.vue'),
          meta: { title: 'PDF 批注', hidden: true },
        },
        {
          path: 'notes/new',
          name: 'note-new',
          component: () => import('@/views/NoteEditView.vue'),
          meta: { title: '新建笔记', hidden: true },
        },
        {
          path: 'notes/:id/edit',
          name: 'note-edit',
          component: () => import('@/views/NoteEditView.vue'),
          meta: { title: '编辑笔记', hidden: true },
        },
        {
          path: 'trash',
          name: 'trash',
          component: () => import('@/views/TrashView.vue'),
          meta: { title: '回收站', icon: 'Delete' },
        },
        {
          path: 'attachments',
          name: 'attachments',
          component: () => import('@/views/AttachmentsView.vue'),
          meta: { title: '附件管理', icon: 'Picture' },
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
          path: 'graph',
          name: 'graph',
          component: () => import('@/views/GraphView.vue'),
          meta: { title: '知识图谱', icon: 'Share' },
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
          path: 'insights',
          name: 'insights',
          component: () => import('@/views/InsightsView.vue'),
          meta: { title: '知识加工', icon: 'MagicStick' },
        },
        {
          path: 'learning',
          name: 'learning',
          component: () => import('@/views/LearningView.vue'),
          meta: { title: '学习辅助', icon: 'Reading' },
        },
        {
          path: 'devhelper',
          name: 'devhelper',
          component: () => import('@/views/DevHelperView.vue'),
          meta: { title: '开发辅助', icon: 'Tools' },
        },
        {
          path: 'extensions',
          name: 'extensions',
          component: () => import('@/views/ExtensionsView.vue'),
          meta: { title: '扩展总览', icon: 'Grid' },
        },
      ],
    },
  ],
})

export default router
