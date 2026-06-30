<template>
  <div class="factory-view">
    <div class="chat-container">
      <!-- 计划面板 -->
      <div v-if="runtimeStore.currentPlan" class="plan-section">
        <n-collapse arrow-placement="right" :default-expanded-names="[]">
          <n-collapse-item name="runtime-plan">
            <template #header>
              <div class="plan-summary">
                <span class="plan-summary-label">计划</span>
                <span class="plan-summary-goal">{{ runtimeStore.currentPlan.goal }}</span>
                <n-tag size="small" :bordered="false" :type="planStatusType">
                  {{ runtimeStore.currentPlan.status }}
                </n-tag>
              </div>
            </template>
            <div class="plan-section-body">
              <PlanPanel compact />
            </div>
          </n-collapse-item>
        </n-collapse>
      </div>

      <div class="chat-target-bar" :class="{ 'agent-target': isAgentChatActive }">
        <div class="target-copy">
          <span class="target-kind">{{ isAgentChatActive ? '子 Agent' : '闲聊' }}</span>
          <span class="target-title">{{ chatTargetTitle }}</span>
          <span v-if="chatTargetMeta" class="target-meta">{{ chatTargetMeta }}</span>
        </div>
        <n-button
          v-if="isAgentChatActive"
          size="small"
          :disabled="runtimeStore.hasActiveRun"
          @click="leaveAgentChat"
        >
          返回闲聊
        </n-button>
      </div>

      <!-- 消息列表 -->
      <div class="messages-section">
        <n-scrollbar ref="scrollbarRef" class="messages-scrollbar">
          <div class="messages-list">
            <n-empty
              v-if="runtimeStore.transcript.length === 0 && !hasActiveStreams"
              description="开始对话"
              style="margin-top: 60px"
            >
              <template #icon>
                <n-icon size="48">
                  <ChatbubbleEllipses />
                </n-icon>
              </template>
              <template #extra>
                <n-text depth="3">
                  在下方输入框输入消息开始对话
                </n-text>
              </template>
            </n-empty>

            <MessageItem
              v-for="message in runtimeStore.transcript"
              :key="message.id"
              :message="message"
              :streaming="isMessageStreaming(message.streamId)"
            />

            <MessageItem
              v-for="message in untrackedActiveStreamMessages"
              :key="message.id"
              :message="message"
              streaming
            />

            <div
              v-if="toolActivityHint"
              class="tool-activity-inline"
              role="status"
              aria-live="polite"
            >
              <span class="tool-activity-spinner" aria-hidden="true"></span>
              <span>{{ toolActivityHint }}</span>
            </div>
          </div>
        </n-scrollbar>
      </div>

      <ToolApprovalPanel
        v-if="hasApprovalRequests"
        class="approval-section"
      />

      <!-- 输入区 -->
      <div class="input-section">
        <MessageInput
          ref="inputRef"
          :placeholder="inputPlaceholder"
          :disabled="runtimeStore.isInputLocked"
          :is-running="runtimeStore.hasActiveRun"
          :attachments-enabled="!isAgentChatActive"
          @send="handleSend"
          @cancel="handleCancel"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { NScrollbar, NEmpty, NIcon, NText, NButton, NCollapse, NCollapseItem, NTag } from 'naive-ui'
import { ChatbubbleEllipses } from '@vicons/ionicons5'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import PlanPanel from '@/components/plan/PlanPanel.vue'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import type { ToolActivity, TranscriptItem } from '@/types/protocol'

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const commands = useCommand()
const scrollbarRef = ref()
const inputRef = ref()

const isAgentChatActive = computed(() => Boolean(agentStore.activeChatPackageId))
const activeChatPackageTitle = computed(() => {
  const pkg = agentStore.activeChatPackage
  return pkg?.agent_name || pkg?.name || '未命名 Agent'
})
const chatTargetTitle = computed(() => (
  isAgentChatActive.value ? activeChatPackageTitle.value : '闲聊'
))
const chatTargetMeta = computed(() => {
  if (!isAgentChatActive.value) return '主会话'
  const session = agentStore.selectedSession
  return session?.display_title || session?.first_user_input || '新子会话'
})
const inputPlaceholder = computed(() => (
  isAgentChatActive.value
    ? `向 ${activeChatPackageTitle.value} 发送消息...`
    : '输入消息...'
))
const planStatusType = computed(() => {
  const status = runtimeStore.currentPlan?.status || ''
  if (status.includes('completed')) return 'success'
  if (status.includes('failed')) return 'error'
  if (status.includes('active') || status.includes('running')) return 'info'
  return 'default'
})

const activeStreams = computed(() => {
  return Object.values(runtimeStore.modelStreams).filter(
    (stream) => stream.visibleToUser && stream.active
  )
})

const hasActiveStreams = computed(() => activeStreams.value.length > 0)
const transcriptStreamIds = computed(() => {
  return new Set(runtimeStore.transcript.map((message) => message.streamId).filter(Boolean))
})
const untrackedActiveStreamMessages = computed<TranscriptItem[]>(() => {
  return activeStreams.value
    .filter((stream) => !transcriptStreamIds.value.has(stream.streamId))
    .map((stream) => ({
      id: stream.streamId,
      role: 'assistant',
      content: stream.content,
      timestamp: new Date().toISOString(),
      streamId: stream.streamId,
    }))
})
const hasApprovalRequests = computed(() => runtimeStore.currentApprovalRequests.length > 0)
const runningToolActivities = computed(() => {
  return runtimeStore.tools.filter((tool) => isToolActivityRunning(tool))
})
const toolActivityHint = computed(() => {
  if (!runtimeStore.hasActiveRun || runningToolActivities.value.length === 0) return ''
  if (runningToolActivities.value.some((tool) => tool.status === 'approval')) return '等待工具确认'
  if (runningToolActivities.value.some((tool) => isKnowledgeRetrievalTool(tool))) return '知识库检索中'
  return runningToolActivities.value.length > 1
    ? `${runningToolActivities.value.length} 个工具调用中`
    : '工具调用中'
})

function isMessageStreaming(streamId?: string): boolean {
  if (!streamId) return false
  return Boolean(runtimeStore.modelStreams[streamId]?.active)
}

function isToolActivityRunning(tool: ToolActivity): boolean {
  return tool.status === 'proposed' || tool.status === 'approval' || tool.status === 'started'
}

function isKnowledgeRetrievalTool(tool: ToolActivity): boolean {
  const name = String(tool.toolName || '').toLowerCase()
  if (name !== 'knowledge') return false
  const action = String(tool.payload?.arguments?.action || '').toLowerCase()
  return !action || ['search', 'open', 'read', 'list_documents', 'describe_source', 'list_sources'].includes(action)
}

function handleSend(message: string, attachments: any[]) {
  const packageId = agentStore.activeChatPackageId
  if (packageId) {
    const agentSessionId = agentStore.selectedSessionId || undefined
    const command = commands.runAgentPackage(packageId, message, agentSessionId)
    runtimeStore.addUserMessage(message, command.request_id, {
      mode: 'agent_package',
      package_id: packageId,
      agent_session_id: agentSessionId || null,
    })
  } else {
    const command = commands.sendMessage(message, 'chat', attachments.length > 0 ? attachments : undefined)
    runtimeStore.addUserMessage(message, command.request_id, { mode: 'chat' })
  }

  // 滚动到底部
  nextTick(() => {
    scrollToBottom()
  })
}

function handleCancel() {
  commands.cancelRequest('user_cancelled')
}

function leaveAgentChat() {
  if (runtimeStore.hasActiveRun) return
  agentStore.leaveAgentChat()
  if (runtimeStore.currentMode !== 'chat') {
    commands.setMode('chat')
  }
  nextTick(() => {
    inputRef.value?.focus()
  })
}

function scrollToBottom() {
  scrollbarRef.value?.scrollTo({ position: 'bottom', behavior: 'smooth' })
}

// 监听消息变化，自动滚动
watch(
  () => runtimeStore.transcript.length,
  () => {
    nextTick(() => {
      scrollToBottom()
    })
  }
)

// 监听流式输出，自动滚动
watch(
  () => [activeStreams.value.map((s) => s.content).join(''), toolActivityHint.value].join(''),
  () => {
    nextTick(() => {
      scrollToBottom()
    })
  }
)

onMounted(() => {
  // 设置模式为 chat
  if (!isAgentChatActive.value && runtimeStore.currentMode !== 'chat') {
    commands.setMode('chat')
  }

  // 聚焦输入框
  nextTick(() => {
    inputRef.value?.focus()
  })
})
</script>

<style scoped>
.factory-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--n-color);
}

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.plan-section {
  margin-bottom: 10px;
  flex-shrink: 0;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  background: var(--n-color);
}

.plan-section :deep(.n-collapse-item__header) {
  padding: 8px 12px;
}

.plan-section :deep(.n-collapse-item__content-inner) {
  padding: 0 12px 12px;
}

.plan-summary {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.plan-summary-label {
  flex-shrink: 0;
  color: var(--n-text-color-2);
  font-size: 12px;
  font-weight: 600;
}

.plan-summary-goal {
  min-width: 0;
  color: var(--n-text-color-1);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-section-body {
  max-height: 220px;
  overflow-y: auto;
}

.chat-target-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  background: var(--n-color);
}

.chat-target-bar.agent-target {
  border-color: var(--n-text-color-1);
}

.target-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.target-kind {
  flex-shrink: 0;
  padding: 2px 7px;
  border: 1px solid var(--n-border-color);
  border-radius: 999px;
  color: var(--n-text-color-2);
  font-size: 12px;
  line-height: 18px;
}

.agent-target .target-kind {
  border-color: var(--n-text-color-1);
  background: var(--n-text-color-1);
  color: var(--n-color);
}

.target-title {
  min-width: 0;
  color: var(--n-text-color-1);
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-meta {
  min-width: 0;
  color: var(--n-text-color-3);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.messages-section {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.messages-scrollbar {
  height: 100%;
}

.messages-list {
  padding: 16px 0;
}

.tool-activity-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 4px 16px 12px 64px;
  padding: 8px 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  color: var(--n-text-color-2);
  background: var(--n-color);
  font-size: 13px;
  line-height: 1;
}

.tool-activity-spinner {
  width: 12px;
  height: 12px;
  flex: 0 0 12px;
  border: 1px solid var(--n-border-color);
  border-top-color: var(--n-text-color-1);
  border-radius: 50%;
  animation: tool-activity-spin 0.8s linear infinite;
}

@keyframes tool-activity-spin {
  to {
    transform: rotate(360deg);
  }
}

.approval-section {
  margin-top: 12px;
}

.input-section {
  margin-top: 16px;
}
</style>
