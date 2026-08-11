<template>
  <div class="conversation-shell">
    <aside class="session-rail">
      <div class="brand-row">
        <img :src="appIcon" alt="" />
        <strong>FastAgentFactory</strong>
      </div>
      <n-button type="primary" block @click="runtime.newConversation">新建对话</n-button>
      <n-scrollbar class="session-list">
        <button
          v-for="session in runtime.conversations"
          :key="session.session_id"
          class="session-button"
          :class="{ active: session.session_id === runtime.activeSessionId }"
          type="button"
          @click="runtime.openConversation(session.session_id)"
        >
          <span>{{ session.title }}</span>
          <small>{{ session.status }}</small>
        </button>
      </n-scrollbar>
      <router-link class="settings-link" :to="{ name: 'ModelPool' }">模型与凭据</router-link>
    </aside>

    <main class="conversation-main">
      <header class="conversation-header">
        <div>
          <strong>{{ runtime.activeConversation?.title || '统一对话' }}</strong>
          <span class="runtime-status" :class="runtime.status">{{ statusLabel }}</span>
        </div>
        <div class="policy-controls">
          <n-select v-model:value="executionPreference" size="small" :options="strategyOptions" />
          <n-select v-model:value="approvalMode" size="small" :options="approvalOptions" />
          <n-select
            v-model:value="modelProfileId"
            size="small"
            filterable
            placeholder="选择主模型"
            :options="modelOptions"
          />
          <n-button size="small" :disabled="!modelProfileId" @click="persistPolicy">保存策略</n-button>
        </div>
      </header>

      <n-alert v-if="runtime.error" type="error" closable class="runtime-alert">
        {{ runtime.error }}
      </n-alert>
      <n-alert v-if="!runtime.policy" type="warning" class="runtime-alert">
        发送消息前需要选择一个可用的主模型并保存运行策略。
      </n-alert>

      <n-scrollbar ref="messageScroller" class="message-scroll">
        <div v-if="!runtime.messages.length" class="empty-state">
          <h2>今天想完成什么？</h2>
          <p>主 Agent 会在快速执行与计划执行之间路由，并为每次运行冻结能力快照。</p>
        </div>
        <article
          v-for="message in runtime.messages"
          :key="message.message_id"
          class="message"
          :class="message.role"
        >
          <div class="message-role">{{ roleLabel(message.role) }}</div>
          <div class="message-body">
            <template v-for="(part, index) in message.parts" :key="`${message.message_id}-${index}`">
              <p v-if="part.kind === 'text'">{{ String(part.text || '') }}</p>
              <div v-else-if="part.kind === 'tool_call'" class="event-card">
                调用工具 {{ part.model_alias }}
              </div>
              <div v-else-if="part.kind === 'tool_result'" class="event-card">
                工具结果：{{ part.status }}
              </div>
              <div v-else class="event-card">{{ part.kind }}</div>
            </template>
          </div>
        </article>
        <div v-if="runtime.status === 'running'" class="running-indicator">主 Agent 正在执行…</div>
      </n-scrollbar>

      <footer class="composer">
        <n-input
          v-model:value="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 8 }"
          placeholder="给主 Agent 发送消息…"
          :disabled="!runtime.policy"
          @keydown="handleKeydown"
        />
        <n-button
          type="primary"
          :loading="runtime.status === 'running'"
          :disabled="!draft.trim() || !runtime.policy"
          @click="send"
        >
          发送
        </n-button>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NInput, NScrollbar, NSelect } from 'naive-ui'
import appIcon from '@/assets/fast-agent-factory-icon.png'
import { modelPoolApi, type ModelPoolProfile } from '@/api/modelPool'
import { useRuntimeStore } from '@/stores/runtime'

const runtime = useRuntimeStore()
const draft = ref('')
const profiles = ref<ModelPoolProfile[]>([])
const modelProfileId = ref('')
const executionPreference = ref<'auto' | 'react' | 'plan_and_execute'>('auto')
const approvalMode = ref<'ask' | 'auto' | 'always_approval'>('ask')
const messageScroller = ref<InstanceType<typeof NScrollbar> | null>(null)

const modelOptions = computed(() => profiles.value
  .filter(item => item.kind === 'chat' && item.enabled && item.credential?.enabled && item.credential.has_api_key)
  .map(item => ({ label: item.display_name, value: item.profile_id })))
const strategyOptions = [
  { label: '自动', value: 'auto' },
  { label: '快速', value: 'react' },
  { label: '计划', value: 'plan_and_execute' },
]
const approvalOptions = [
  { label: '按风险询问', value: 'ask' },
  { label: '自动批准', value: 'auto' },
  { label: '始终询问', value: 'always_approval' },
]
const statusLabel = computed(() => ({
  idle: '未连接', connecting: '连接中', ready: '就绪', running: '执行中', error: '异常',
}[runtime.status]))

onMounted(async () => {
  profiles.value = (await modelPoolApi.profiles()).profiles
  await runtime.initialize()
  syncPolicy()
})

watch(() => runtime.policy, syncPolicy)
watch(() => runtime.messages.length, () => nextTick(() => messageScroller.value?.scrollTo({ top: 1e9 })))

function syncPolicy(): void {
  modelProfileId.value = runtime.policy?.model_profile_id || modelOptions.value[0]?.value || ''
  executionPreference.value = runtime.policy?.execution_preference || 'auto'
  approvalMode.value = runtime.policy?.approval_mode || 'ask'
}

async function persistPolicy(): Promise<void> {
  await runtime.savePolicy({
    modelProfileId: modelProfileId.value,
    executionPreference: executionPreference.value,
    approvalMode: approvalMode.value,
  })
}

async function send(): Promise<void> {
  const content = draft.value.trim()
  if (!content) return
  draft.value = ''
  try {
    await runtime.sendMessage(content)
  } catch {
    draft.value = content
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void send()
}

function roleLabel(role: string): string {
  return role === 'user' ? '你' : role === 'assistant' ? '主 Agent' : '工具'
}
</script>

<style scoped>
.conversation-shell { height: 100%; display: grid; grid-template-columns: 260px minmax(0, 1fr); color: var(--app-text); }
.session-rail { min-width: 0; padding: 16px; display: flex; flex-direction: column; gap: 14px; background: var(--app-surface-muted); border-right: 1px solid var(--app-border); }
.brand-row { display: flex; align-items: center; gap: 9px; min-height: 36px; }
.brand-row img { width: 28px; height: 28px; }
.session-list { flex: 1; min-height: 0; }
.session-button { width: 100%; border: 0; background: transparent; color: inherit; display: flex; justify-content: space-between; gap: 8px; padding: 10px; border-radius: 9px; text-align: left; cursor: pointer; }
.session-button:hover, .session-button.active { background: var(--app-surface-elevated); }
.session-button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-button small { color: var(--app-text-tertiary); }
.settings-link { color: var(--app-text-secondary); text-decoration: none; padding: 8px; }
.conversation-main { min-width: 0; display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; }
.conversation-header { min-height: 62px; padding: 12px 20px; border-bottom: 1px solid var(--app-border); display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.conversation-header > div:first-child { display: flex; align-items: center; gap: 10px; }
.runtime-status { font-size: 12px; color: var(--app-text-tertiary); }
.runtime-status.running { color: var(--app-primary); }
.runtime-status.error { color: var(--app-error); }
.policy-controls { display: grid; grid-template-columns: 100px 120px minmax(160px, 240px) auto; gap: 8px; }
.runtime-alert { margin: 12px 20px 0; }
.message-scroll { min-height: 0; }
.empty-state { min-height: 55vh; display: grid; place-content: center; text-align: center; gap: 10px; color: var(--app-text-secondary); }
.empty-state h2 { color: var(--app-text); font-size: 28px; }
.message { max-width: 880px; margin: 0 auto; padding: 18px 24px; display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 16px; }
.message.user .message-body { background: var(--app-primary-soft); padding: 12px 14px; border-radius: 14px; }
.message-role { color: var(--app-text-tertiary); font-size: 13px; padding-top: 3px; }
.message-body { white-space: pre-wrap; line-height: 1.65; overflow-wrap: anywhere; }
.message-body p + p { margin-top: 10px; }
.event-card { margin-top: 8px; padding: 9px 11px; border-radius: 8px; background: var(--app-surface-muted); color: var(--app-text-secondary); font-size: 13px; }
.running-indicator { max-width: 880px; margin: 10px auto; padding: 0 24px; color: var(--app-primary); }
.composer { padding: 14px 20px 18px; border-top: 1px solid var(--app-border); display: flex; align-items: flex-end; gap: 10px; background: var(--app-surface); }
@media (max-width: 860px) { .conversation-shell { grid-template-columns: 190px minmax(0, 1fr); } .conversation-header { align-items: flex-start; flex-direction: column; } .policy-controls { width: 100%; grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
