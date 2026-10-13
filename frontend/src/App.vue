<template>
  <router-view />
</template>

<script setup lang="ts">
/**
 * 全局注册正文双链的点击委托。
 *
 * 放在 App 级而不是各页面：正文链接可能出现在任何渲染 Markdown 的地方
 * （文档详情、检索结果摘要、问答引用预览），逐个页面接一遍容易漏。
 */
import { useWikiLinks } from '@/composables/useWikiLinks'

useWikiLinks()
</script>
