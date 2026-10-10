<template>
  <div class="page" v-loading="loading">
    <div class="page-header">
      <div>
        <h1 class="page-title">系统设置</h1>
        <p class="page-sub">配置 AI 服务、检索参数与本地运行选项。密钥写入 .env，其余存入本地数据库</p>
      </div>
    </div>

    <div class="card">
      <div class="section-title">AI 服务</div>
      <el-form label-width="150px" style="max-width: 720px">
        <el-form-item label="服务模式">
          <el-radio-group v-model="form.ai_mode">
            <el-radio-button value="local">本地模型</el-radio-button>
            <el-radio-button value="external">外部 API</el-radio-button>
          </el-radio-group>
          <div class="hint">界面与回答均会标明当前使用的模式。外部 API 模式并非离线。</div>
        </el-form-item>

        <template v-if="form.ai_mode === 'local'">
          <el-form-item label="本地服务地址">
            <el-input v-model="form.local_model_base_url" placeholder="http://127.0.0.1:11434" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="外部服务地址">
            <el-input v-model="form.external_api_base_url" placeholder="https://api.example.com/v1" />
          </el-form-item>
          <el-form-item label="API 密钥">
            <el-input
              v-model="apiKey"
              type="password"
              show-password
              :placeholder="settings?.has_external_key ? '已配置（留空则不修改）' : '未配置'"
            />
          </el-form-item>
        </template>

        <el-form-item label="聊天模型">
          <el-input v-model="form.chat_model" placeholder="例如 deepseek-v4-flash / qwen2.5:7b" />
        </el-form-item>

        <el-divider content-position="left">嵌入服务（可与对话服务不同）</el-divider>

        <el-form-item label="嵌入服务地址">
          <el-input v-model="form.embedding_base_url" placeholder="留空则复用对话服务地址" />
        </el-form-item>
        <el-form-item label="嵌入 API 密钥">
          <el-input
            v-model="embeddingKey"
            type="password"
            show-password
            :placeholder="settings?.has_embedding_key ? '已配置（留空则不修改）' : '未配置'"
          />
        </el-form-item>
        <el-form-item label="嵌入模型">
          <el-input
            v-model="form.embedding_model"
            placeholder="例如 qwen3.7-text-embedding-flash / bge-m3"
          />
        </el-form-item>
        <el-form-item label="嵌入维度">
          <el-input-number v-model="form.embedding_dim" :min="64" :max="4096" />
          <span class="hint">必须与嵌入模型实际输出一致；修改后需要重建全部索引</span>
        </el-form-item>
        <el-form-item label="请求超时（秒）">
          <el-input-number v-model="form.request_timeout" :min="5" :max="600" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="save">保存设置</el-button>
          <el-button :loading="testing" @click="test">检测模型服务</el-button>
        </el-form-item>
        <el-alert v-if="testResult" :type="testResult.ok ? 'success' : 'error'" :closable="false">
          <div>对话服务：{{ testResult.message }}</div>
          <div v-if="testResult.models.length" class="hint">
            可用模型：{{ testResult.models.slice(0, 12).join('、') }}
          </div>
          <div style="margin-top: 6px" :class="{ warn: !testResult.embedding_ok }">
            嵌入服务：{{ testResult.embedding_message }}
          </div>
        </el-alert>
      </el-form>
    </div>

    <div class="card mt">
      <div class="section-title">检索与运行</div>
      <el-form label-width="150px" style="max-width: 720px">
        <el-form-item label="关键词权重 α">
          <el-input-number v-model="form.hybrid_alpha" :min="0" :max="1" :step="0.1" />
        </el-form-item>
        <el-form-item label="语义权重 β">
          <el-input-number v-model="form.hybrid_beta" :min="0" :max="1" :step="0.1" />
        </el-form-item>
        <el-form-item label="默认返回条数">
          <el-input-number v-model="form.search_top_k" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="上传大小上限（MB）">
          <el-input-number v-model="form.max_upload_mb" :min="1" :max="2048" />
        </el-form-item>
        <el-form-item label="数据目录">
          <el-input v-model="form.data_dir" disabled />
        </el-form-item>
        <el-form-item label="分块方式">
          <el-radio-group v-model="form.chunk_mode">
            <el-radio-button value="semantic">语义分块</el-radio-button>
            <el-radio-button value="rule">规则分块</el-radio-button>
            <el-radio-button value="ai">AI 分块</el-radio-button>
          </el-radio-group>
          <span class="hint">
            语义分块按句子向量相似度找话题断点，效果好且只消耗嵌入调用（推荐）；
            规则分块按标题/段落/句子切分，快且零成本（模型不可用时的兜底）；
            AI 分块由对话模型判断边界，最准但最贵，适合结构混乱的文档。
            修改后需对文档「重建索引」才生效。
          </span>
        </el-form-item>

        <el-form-item label="父子检索">
          <el-switch v-model="form.parent_child_enabled" />
          <span class="hint">
            开启后，文档会同时切出「子块」（约 400 字，用于向量检索，匹配更精准）与
            「父块」（约 1500 字，命中后回传给模型，上下文更完整）。
            关闭则退化为单级分块。修改后需对文档「重建索引」才生效。
          </span>
        </el-form-item>

        <el-form-item label="存储方案">
          <el-tag>{{ settings?.storage_mode }}</el-tag>
          <span class="hint">本机 PostgreSQL 18 + pgvector（关系 + 向量 + 关键词一库覆盖）</span>
        </el-form-item>

        <el-divider content-position="left">联网补充</el-divider>

        <el-form-item label="启用联网搜索">
          <el-switch v-model="form.web_search_enabled" />
          <span class="hint">
            关闭时系统绝不联网；开启后可在问答页临时选择是否联网，
            联网信息会标注 🌐 并附真实链接
          </span>
        </el-form-item>
        <template v-if="form.web_search_enabled">
          <el-form-item label="搜索服务">
            <el-radio-group v-model="form.web_search_provider">
              <el-radio-button value="bing">Bing（免密钥）</el-radio-button>
              <el-radio-button value="duckduckgo">DuckDuckGo（需外网）</el-radio-button>
              <el-radio-button value="custom">自备搜索 API</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <template v-if="form.web_search_provider === 'custom'">
            <el-form-item label="搜索 API 地址">
              <el-input
                v-model="form.web_search_api_url"
                placeholder="https://your-search.example.com/search"
              />
            </el-form-item>
            <el-form-item label="搜索 API 密钥">
              <el-input
                v-model="webKey"
                type="password"
                show-password
                :placeholder="settings?.has_web_search_key ? '已配置（留空则不修改）' : '未配置'"
              />
            </el-form-item>
          </template>
          <el-form-item label="返回条数">
            <el-input-number v-model="form.web_search_top_k" :min="1" :max="8" />
          </el-form-item>
        </template>

        <el-form-item>
          <el-button type="primary" @click="save">保存设置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="card mt">
      <div class="section-title">向量索引状态</div>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="文档总数">{{ idx.document_total }}</el-descriptions-item>
        <el-descriptions-item label="已索引（含向量）">{{ idx.indexed }}</el-descriptions-item>
        <el-descriptions-item label="部分索引（仅关键词）">
          <span :class="{ warn: idx.partial > 0 }">{{ idx.partial }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="等待/处理中">{{ idx.pending + idx.processing }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ idx.failed }}</el-descriptions-item>
        <el-descriptions-item label="片段总数">{{ idx.chunk_total }}</el-descriptions-item>
        <el-descriptions-item label="已向量化">{{ idx.embedded_chunks }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="idx.partial > 0 && !form.embedding_model"
        class="mt-sm"
        type="warning"
        :closable="false"
        title="当前未配置嵌入模型：文档已完成分块，关键词检索可用；语义检索不可用。配置嵌入模型后，在文档管理中对文档「重建索引」即可补齐向量。"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { settingsApi } from '@/api'
import type { IndexStatus, SettingsOut } from '@/api/types'

const loading = ref(false)
const testing = ref(false)
const settings = ref<SettingsOut | null>(null)
const apiKey = ref('')
const embeddingKey = ref('')
const webKey = ref('')
const testResult = ref<{
  ok: boolean
  message: string
  models: string[]
  embedding_ok: boolean
  embedding_message: string
} | null>(null)

const form = reactive({
  ai_mode: 'local',
  local_model_base_url: '',
  external_api_base_url: '',
  chat_model: '',
  embedding_model: '',
  embedding_dim: 1024,
  embedding_base_url: '',
  request_timeout: 60,
  hybrid_alpha: 0.3,
  hybrid_beta: 0.7,
  search_top_k: 10,
  max_upload_mb: 50,
  data_dir: '',
  chunk_mode: 'semantic',
  parent_child_enabled: true,
  web_search_enabled: false,
  web_search_provider: 'bing',
  web_search_api_url: '',
  web_search_top_k: 5,
})

const idx = ref<IndexStatus>({
  document_total: 0,
  indexed: 0,
  partial: 0,
  pending: 0,
  processing: 0,
  failed: 0,
  chunk_total: 0,
  embedded_chunks: 0,
})

async function load() {
  loading.value = true
  try {
    const s = await settingsApi.get()
    settings.value = s
    Object.assign(form, {
      ai_mode: s.ai_mode,
      local_model_base_url: s.local_model_base_url,
      external_api_base_url: s.external_api_base_url,
      chat_model: s.chat_model,
      embedding_model: s.embedding_model,
      embedding_dim: s.embedding_dim,
      embedding_base_url: s.embedding_base_url,
      request_timeout: s.request_timeout,
      hybrid_alpha: s.hybrid_alpha,
      hybrid_beta: s.hybrid_beta,
      search_top_k: s.search_top_k,
      max_upload_mb: s.max_upload_mb,
      data_dir: s.data_dir,
      chunk_mode: s.chunk_mode,
      parent_child_enabled: s.parent_child_enabled,
      web_search_enabled: s.web_search_enabled,
      web_search_provider: s.web_search_provider,
      web_search_api_url: s.web_search_api_url,
      web_search_top_k: s.web_search_top_k,
    })
    idx.value = await settingsApi.indexStatus()
  } finally {
    loading.value = false
  }
}

async function save() {
  const payload: Record<string, unknown> = { ...form }
  if (apiKey.value) payload.external_api_key = apiKey.value
  if (embeddingKey.value) payload.embedding_api_key = embeddingKey.value
  if (webKey.value) payload.web_search_api_key = webKey.value
  settings.value = await settingsApi.update(payload)
  apiKey.value = ''
  embeddingKey.value = ''
  webKey.value = ''
  ElMessage.success('设置已保存')
}

async function test() {
  testing.value = true
  try {
    testResult.value = await settingsApi.testModel()
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.section-title {
  font-weight: 600;
  margin-bottom: 16px;
}
.mt {
  margin-top: 16px;
}
.hint {
  color: var(--kh-text-sub);
  font-size: 12px;
  margin-left: 8px;
}
.warn {
  color: #e6a23c;
  font-weight: 600;
}
.mt-sm {
  margin-top: 12px;
}
</style>
