<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">扩展总览</h1>
        <p class="page-sub">
          三个扩展模块均已实现，可点击卡片下方「进入模块」使用。
          它们沿用核心闭环的存储架构，并遵守同样的事实性约束
        </p>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="8" v-for="group in groups" :key="group.name">
        <div class="card">
          <div class="group-head">
            <el-tag :type="group.tag as never" size="small">{{ group.priority }}</el-tag>
            <span class="group-name">{{ group.name }}</span>
          </div>
          <ul class="items">
            <li v-for="item in group.items" :key="item">{{ item }}</li>
          </ul>
          <div class="dep">依赖：{{ group.dep }}</div>
          <el-button type="primary" size="small" class="enter-btn" @click="$router.push(group.path)">
            进入模块
          </el-button>
        </div>
      </el-col>
    </el-row>

    <div class="card mt">
      <div class="section-title">扩展模块的共性约束</div>
      <ul class="items">
        <li>事实 / 观点 / 计划 / 推断必须分离，不得把计划写成已完成、把推断写成用户观点</li>
        <li>复习与面试不得虚构用户曾经答错的题目</li>
        <li>代码评审必须区分「知识库记录」与「AI 新提出的建议」</li>
        <li>故障排查未经验证时不得把可能原因说成确定根因</li>
        <li>时间线无法从原文确认日期时应标注为未知，不得推测</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
const groups = [
  {
    name: 'AI 知识加工',
    priority: 'P1',
    tag: 'danger',
    dep: '文档管理、分块与索引',
    path: '/insights',
    items: ['笔记整理与归档', '标签推荐', '冗余检测', '跨文档知识关联', '思维导图'],
  },
  {
    name: '学习辅助',
    priority: 'P2',
    tag: 'warning',
    dep: 'RAG 问答与引用',
    path: '/learning',
    items: ['模拟面试（多方向/多难度）', '评分与点评', '错题管理', '快捷复习'],
  },
  {
    name: '项目开发辅助',
    priority: 'P2',
    tag: 'warning',
    dep: '检索与问答',
    path: '/devhelper',
    items: ['代码评审', '故障排查', '需求拆解', '项目时间线'],
  },
]
</script>

<style scoped>
.group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.group-name {
  font-weight: 600;
}
.items {
  margin: 0;
  padding-left: 18px;
  color: #606266;
  line-height: 1.9;
}
.dep {
  color: var(--kh-text-sub);
  font-size: 12px;
  margin-top: 10px;
}
.enter-btn {
  margin-top: 12px;
}
.section-title {
  font-weight: 600;
  margin-bottom: 10px;
}
.mt {
  margin-top: 16px;
}
</style>
