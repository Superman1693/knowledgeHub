<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">分类管理</h1>
        <p class="page-sub">
          用多级文件夹组织知识。删除分类只会解除关联、子分类自动上提，不会删除文档
        </p>
      </div>
    </div>

    <el-alert class="guide" type="info" :closable="false" show-icon title="分类怎么用？">
      <div>
        分类是<b>粗粒度分区</b>（如「工作 / 学习 / 生活」），现在支持<b>多级</b>嵌套。
        一篇文档只能属于一个分类；给文档设置分类的入口在「文档管理」→ 文档详情页的「分类」下拉框。
        点某个分类的<b>文档数</b>可查看该分类下的文档。
      </div>
    </el-alert>

    <div class="card">
      <div class="row">
        <el-tree-select
          v-model="newParentId"
          :data="parentOptions"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          check-strictly
          clearable
          placeholder="父分类（留空为顶层）"
          style="width: 240px"
        />
        <el-input
          v-model="newName"
          placeholder="新分类名称"
          style="width: 200px"
          @keyup.enter="create"
        />
        <el-input v-model="newDesc" placeholder="描述（可选）" style="width: 240px" />
        <el-button type="primary" @click="create">新建分类</el-button>
      </div>

      <div v-loading="loading" class="tree-wrap">
        <el-tree
          v-if="tree.length"
          :data="tree"
          node-key="id"
          default-expand-all
          :expand-on-click-node="false"
          :props="{ label: 'name', children: 'children' }"
        >
          <template #default="{ data }">
            <div class="node">
              <el-icon class="node-icon"><FolderOpened /></el-icon>
              <span class="node-name">{{ data.name }}</span>
              <span v-if="data.description" class="node-desc">{{ data.description }}</span>
              <el-tag v-if="data.document_count" size="small" effect="plain" class="node-tag">
                {{ data.document_count }} 篇
              </el-tag>
              <span v-if="data.total_count > data.document_count" class="node-sub">
                含子分类共 {{ data.total_count }} 篇
              </span>

              <span class="node-actions">
                <el-button link type="primary" size="small" @click.stop="addChild(data)">
                  新建子分类
                </el-button>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="!data.document_count"
                  @click.stop="openDocuments(data.id)"
                >
                  查看文档
                </el-button>
                <el-button link type="primary" size="small" @click.stop="rename(data)">
                  重命名
                </el-button>
                <el-button link type="primary" size="small" @click.stop="move(data)">
                  移动
                </el-button>
                <el-button link type="danger" size="small" @click.stop="remove(data)">
                  删除
                </el-button>
              </span>
            </div>
          </template>
        </el-tree>

        <div v-else-if="!loading" class="empty-state">
          <div class="empty-icon"><el-icon><FolderOpened /></el-icon></div>
          <div class="empty-title">还没有分类</div>
          <div class="empty-desc">
            分类适合做知识分区，支持多级嵌套（如「技术 / 前端 / Vue」）。
          </div>
        </div>
      </div>
    </div>

    <!-- 移动分类 -->
    <el-dialog v-model="moveOpen" title="移动分类" width="420px">
      <div class="move-tip">
        把「{{ moving?.name }}」移动到：<b>不能选它自己或其子分类</b>（会形成环）。
      </div>
      <el-tree-select
        v-model="moveTargetId"
        :data="moveOptions"
        :props="{ label: 'name', children: 'children' }"
        node-key="id"
        check-strictly
        clearable
        placeholder="留空 = 移动到顶层"
        style="width: 100%"
      />
      <template #footer>
        <el-button @click="moveOpen = false">取消</el-button>
        <el-button type="primary" @click="confirmMove">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { categoriesApi } from '@/api'
import type { CategoryTreeNode } from '@/api/types'

const router = useRouter()
const loading = ref(false)
const tree = ref<CategoryTreeNode[]>([])
const newParentId = ref<string | null>(null)
const newName = ref('')
const newDesc = ref('')

const moveOpen = ref(false)
const moving = ref<CategoryTreeNode | null>(null)
const moveTargetId = ref<string | null>(null)

/** 新建时的父分类候选（全部节点）。 */
const parentOptions = computed(() => tree.value)

/** 移动时的候选：排除自身与其全部子孙（后端也会校验，这里提前避免误选）。 */
const moveOptions = computed(() => {
  if (!moving.value) return tree.value
  const blocked = new Set<string>([moving.value.id])
  const collect = (nodes: CategoryTreeNode[]) => {
    for (const n of nodes) {
      blocked.add(n.id)
      collect(n.children || [])
    }
  }
  collect(moving.value.children || [])

  const filter = (nodes: CategoryTreeNode[]): CategoryTreeNode[] =>
    nodes
      .filter((n) => !blocked.has(n.id))
      .map((n) => ({ ...n, children: filter(n.children || []) }))
  return filter(tree.value)
})

function openDocuments(categoryId: string) {
  router.push({ path: '/documents', query: { category: categoryId } })
}

async function load() {
  loading.value = true
  try {
    tree.value = await categoriesApi.tree()
  } finally {
    loading.value = false
  }
}

async function create() {
  const name = newName.value.trim()
  if (!name) {
    ElMessage.warning('请输入分类名称')
    return
  }
  await categoriesApi.create({
    name,
    description: newDesc.value || undefined,
    parent_id: newParentId.value,
  })
  ElMessage.success('已创建')
  newName.value = ''
  newDesc.value = ''
  newParentId.value = null
  load()
}

async function addChild(node: CategoryTreeNode) {
  let value: string
  try {
    const res = await ElMessageBox.prompt(`在「${node.name}」下新建子分类`, '新建子分类', {
      inputPattern: /\S/,
      inputErrorMessage: '名称不能为空',
    })
    value = (res.value || '').trim()
  } catch {
    return
  }
  if (!value) return
  await categoriesApi.create({ name: value, parent_id: node.id })
  ElMessage.success('已创建')
  load()
}

async function rename(node: CategoryTreeNode) {
  let value: string
  try {
    const res = await ElMessageBox.prompt('输入新的分类名称', '重命名', {
      inputValue: node.name,
      inputPattern: /\S/,
      inputErrorMessage: '名称不能为空',
    })
    value = (res.value || '').trim()
  } catch {
    return
  }
  if (!value || value === node.name) return
  await categoriesApi.update(node.id, { name: value })
  ElMessage.success('已更新')
  load()
}

function move(node: CategoryTreeNode) {
  moving.value = node
  moveTargetId.value = node.parent_id ?? null
  moveOpen.value = true
}

async function confirmMove() {
  const node = moving.value
  if (!node) return
  const payload =
    moveTargetId.value === null
      ? { move_to_root: true }
      : { parent_id: moveTargetId.value }
  await categoriesApi.update(node.id, payload)
  ElMessage.success('已移动')
  moveOpen.value = false
  moving.value = null
  load()
}

async function remove(node: CategoryTreeNode) {
  const childHint = node.children?.length
    ? `它的 ${node.children.length} 个子分类会自动上提为上一层。`
    : ''
  try {
    await ElMessageBox.confirm(
      `删除分类「${node.name}」？其中的 ${node.document_count} 篇文档会变为未分类，` +
        `文档本身不会被删除。${childHint}`,
      '删除确认',
      { type: 'warning' },
    )
  } catch {
    return // 用户取消（ElMessageBox reject 未捕获会产生 unhandled rejection）
  }
  await categoriesApi.remove(node.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.mt {
  margin-top: 16px;
}
.guide {
  margin-bottom: 16px;
}
.muted {
  color: var(--kh-text-mute);
}
.tree-wrap {
  margin-top: 16px;
  min-height: 120px;
}
.node {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding-right: 6px;
}
.node-icon {
  color: var(--kh-text-mute);
  font-size: 14px;
}
.node-name {
  font-size: 13.5px;
}
.node-desc {
  font-size: 12px;
  color: var(--kh-text-mute);
}
.node-tag {
  transform: scale(0.9);
}
.node-sub {
  font-size: 11.5px;
  color: var(--kh-text-mute);
}
.node-actions {
  margin-left: auto;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.node:hover .node-actions {
  opacity: 1;
}
.move-tip {
  font-size: 12.5px;
  color: var(--kh-text-sub);
  line-height: 1.7;
  margin-bottom: 10px;
}
</style>
