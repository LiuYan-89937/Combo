<template>
  <div class="agent-group-view">
    <div class="agent-group-container">
      <!-- 消息列表 -->
      <div class="message-list" ref="messageListRef">
        <div v-if="store.loading" class="loading-indicator">
          <n-spin size="large" />
        </div>

        <div v-else-if="!store.activeGroup" class="empty-state">
          <n-empty description="未选择群聊">
            <template #extra>
              <n-button @click="handleCreateGroup">创建新群聊</n-button>
            </template>
          </n-empty>
        </div>

        <div v-else class="messages-container">
          <!-- 群聊标题 -->
          <div class="group-header">
            <h2>{{ store.activeGroup.title }}</h2>
            <n-tag :type="statusTagType(store.activeGroup.status)">
              {{ store.activeGroup.status }}
            </n-tag>
          </div>

          <!-- 消息列表 -->
          <div class="messages">
            <div
              v-for="message in store.messages"
              :key="message.message_id"
              class="message-wrapper"
              :class="`message-${message.speaker_type}`"
            >
              <!-- 用户消息 -->
              <div v-if="message.speaker_type === 'user'" class="user-message">
                <div class="message-header">
                  <span class="speaker">用户</span>
                  <span class="timestamp">{{ formatTime(message.created_at) }}</span>
                </div>
                <div class="message-content">{{ message.content }}</div>
              </div>

              <!-- Agent 消息 -->
              <div v-else-if="message.speaker_type === 'agent'" class="agent-message">
                <div class="message-header">
                  <span class="speaker">{{ getAgentName(message.speaker_package_id) }}</span>
                  <n-tag v-if="message.group_run_id" size="small">
                    {{ getRunStatus(message.group_run_id) }}
                  </n-tag>
                  <span class="timestamp">{{ formatTime(message.created_at) }}</span>
                </div>
                <div class="message-content" :class="`kind-${message.message_kind}`">
                  {{ message.content }}
                </div>
              </div>

              <!-- 系统消息 -->
              <div v-else class="system-message">
                <span class="content">{{ message.content }}</span>
              </div>
            </div>
          </div>

          <!-- Active runs 指示器 -->
          <div v-if="store.activeRuns.length > 0" class="active-runs-indicator">
            <n-spin size="small" />
            <span>{{ store.activeRuns.length }} 个 Agent 运行中...</span>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <div v-if="store.activeGroup" class="input-container">
          <!-- @mention 选择器 -->
          <div v-if="showMentionPicker" class="mention-picker">
            <n-list bordered>
              <n-list-item
                v-for="member in store.members"
                :key="member.package_id"
                clickable
                @click="selectMention(member.package_id)"
              >
                <div class="mention-option">
                  <strong>{{ getAgentName(member.package_id) }}</strong>
                  <span v-if="getAgent(member.package_id)?.agent_description" class="description">
                    {{ getAgent(member.package_id)?.agent_description }}
                  </span>
                </div>
              </n-list-item>
            </n-list>
          </div>

          <!-- 已选 @mentions -->
          <div v-if="selectedMentions.length > 0" class="selected-mentions">
            <n-tag
              v-for="packageId in selectedMentions"
              :key="packageId"
              closable
              @close="removeMention(packageId)"
            >
              @{{ getAgentName(packageId) }}
            </n-tag>
          </div>

          <!-- 输入框 -->
          <n-input
            v-model:value="messageInput"
            type="textarea"
            :placeholder="selectedMentions.length > 0 ? '输入消息...' : '输入 @ 选择 Agent，然后输入消息'"
            :autosize="{ minRows: 3, maxRows: 8 }"
            @keydown="handleKeyDown"
            @input="handleInput"
          />

          <div class="input-actions">
            <n-button
              type="primary"
              :disabled="!canSend"
              :loading="store.saving"
              @click="handleSend"
            >
              发送
            </n-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { NButton, NEmpty, NInput, NList, NListItem, NSpin, NTag } from 'naive-ui'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useRouter } from 'vue-router'

const store = useAgentGroupStore()
const router = useRouter()

const messageListRef = ref<HTMLElement>()
const messageInput = ref('')
const selectedMentions = ref<string[]>([])
const showMentionPicker = ref(false)
const mentionPickerPosition = ref(0)

// Computed
const canSend = computed(() => {
  return messageInput.value.trim().length > 0 && selectedMentions.value.length > 0 && !store.saving
})

// 监听消息变化，自动滚动
watch(
  () => store.messages.length,
  () => {
    nextTick(() => {
      if (messageListRef.value) {
        messageListRef.value.scrollTop = messageListRef.value.scrollHeight
      }
    })
  }
)

// 定期刷新（临时方案，完整 SSE 留给阶段7）
let refreshTimer: number | null = null
watch(
  () => store.activeGroup,
  (group) => {
    if (refreshTimer) clearInterval(refreshTimer)
    if (group && store.activeRuns.length > 0) {
      refreshTimer = window.setInterval(() => {
        store.loadGroup(group.group_id)
      }, 3000)
    }
  },
  { immediate: true }
)

// Methods
const getAgentName = (packageId: string | undefined) => {
  if (!packageId) return '未知'
  const agent = store.agentById(packageId)
  return agent?.agent_name || packageId
}

const getAgent = (packageId: string) => {
  return store.agentById(packageId)
}

const getRunStatus = (runId: string) => {
  const run = store.runs.find(r => r.group_run_id === runId)
  return run?.status || ''
}

const statusTagType = (status: string) => {
  if (status === 'active') return 'success'
  if (status === 'archived') return 'default'
  return 'info'
}

const formatTime = (timestamp: string) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const handleInput = (value: string) => {
  // 检测 @ 符号
  const lastChar = value[value.length - 1]
  if (lastChar === '@') {
    showMentionPicker.value = true
  } else {
    showMentionPicker.value = false
  }
}

const selectMention = (packageId: string) => {
  if (!selectedMentions.value.includes(packageId)) {
    selectedMentions.value.push(packageId)
  }
  showMentionPicker.value = false
  // 移除输入框中的 @
  if (messageInput.value.endsWith('@')) {
    messageInput.value = messageInput.value.slice(0, -1)
  }
}

const removeMention = (packageId: string) => {
  selectedMentions.value = selectedMentions.value.filter(id => id !== packageId)
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
    handleSend()
  }
}

const handleSend = async () => {
  if (!canSend.value) return

  try {
    await store.sendMessage(messageInput.value.trim(), selectedMentions.value)
    messageInput.value = ''
    selectedMentions.value = []
  } catch (e) {
    console.error('Failed to send message:', e)
  }
}

const handleCreateGroup = () => {
  // TODO: 打开创建群聊对话框
}

// 生命周期
store.bootstrap()
</script>

<style scoped>
.agent-group-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--n-color);
}

.agent-group-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.loading-indicator,
.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}

.messages-container {
  max-width: 800px;
  margin: 0 auto;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}

.group-header h2 {
  margin: 0;
  font-size: 20px;
}

.messages {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-wrapper {
  animation: fadeIn 0.3s;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.user-message,
.agent-message {
  padding: 12px;
  border-radius: 8px;
  background: var(--n-color-modal);
}

.user-message {
  margin-left: 0;
  border-left: 3px solid var(--n-color-primary);
}

.agent-message {
  margin-right: 0;
  border-left: 3px solid var(--n-color-info);
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.message-header .speaker {
  font-weight: 600;
}

.message-header .timestamp {
  color: var(--n-text-color-disabled);
  font-size: 12px;
}

.message-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.kind-progress {
  color: var(--n-text-color-disabled);
  font-style: italic;
}

.system-message {
  text-align: center;
  color: var(--n-text-color-disabled);
  font-size: 13px;
  padding: 8px;
}

.active-runs-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--n-color-info);
  border-radius: 4px;
  margin-top: 16px;
  font-size: 14px;
}

.input-area {
  border-top: 1px solid var(--n-border-color);
  padding: 16px;
  background: var(--n-color-modal);
}

.input-container {
  max-width: 800px;
  margin: 0 auto;
}

.mention-picker {
  margin-bottom: 12px;
}

.mention-option {
  display: flex;
  flex-direction: column;
}

.mention-option .description {
  font-size: 12px;
  color: var(--n-text-color-disabled);
}

.selected-mentions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.input-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
