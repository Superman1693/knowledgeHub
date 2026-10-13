<template>
  <div class="mermaid-wrap">
    <div v-if="error" class="mermaid-error">
      <el-alert type="warning" :closable="false" :title="error" show-icon />
      <pre class="mermaid-raw">{{ code }}</pre>
    </div>
    <div v-else ref="host" v-loading="loading" class="mermaid-host" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import mermaid from 'mermaid'

const props = defineProps<{ code: string }>()

const host = ref<HTMLElement | null>(null)
const error = ref('')
const loading = ref(false)

mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  // 图表代码来自 AI 生成结果：必须用 strict。
  // loose 模式会放行标签内的 HTML 与点击事件，等于给 AI 输出开了注入口子。
  securityLevel: 'strict',
  fontFamily: 'inherit',
})

let seq = 0

async function render() {
  const code = (props.code || '').trim()
  if (!code) {
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  // 出错分支会卸载 host 节点；等 DOM 更新完再取引用，
  // 否则「先失败、后成功」时 host.value 仍是 null，图表会渲染成空白。
  await nextTick()
  try {
    // mermaid.render 需要唯一 id，否则重复渲染会命中缓存
    const { svg } = await mermaid.render(`kh-mermaid-${Date.now()}-${seq++}`, code)
    if (host.value) host.value.innerHTML = svg
  } catch (err) {
    error.value = `图表渲染失败：${(err as Error).message}`
  } finally {
    loading.value = false
  }
}

onMounted(render)
watch(() => props.code, render)
</script>

<style scoped>
.mermaid-wrap {
  width: 100%;
}
.mermaid-host {
  overflow-x: auto;
  padding: 10px 0;
  min-height: 60px;
}
.mermaid-host :deep(svg) {
  max-width: 100%;
  height: auto;
}
.mermaid-raw {
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--kh-bg-deep);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
}
</style>
