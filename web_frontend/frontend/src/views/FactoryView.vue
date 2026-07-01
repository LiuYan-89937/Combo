<template>
  <div class="factory-view">
    <div class="chat-container">
      <div v-if="isEvolutionRoute" class="evolution-target-bar">
        <span class="evolution-target-label">进化对象</span>
        <n-select
          class="evolution-target-select"
          :value="selectedEvolutionPackageId"
          :options="evolutionPackageOptions"
          placeholder="选择要进化的 Agent 包"
          filterable
          @update:value="handleEvolutionPackageSelect"
        />
      </div>

      <!-- 消息列表 -->
      <div class="messages-section">
        <n-scrollbar ref="scrollbarRef" class="messages-scrollbar">
          <div class="messages-list">
            <n-empty
              v-if="runtimeStore.transcript.length === 0 && !hasActiveStreams"
              :description="emptyDescription"
              style="margin-top: 60px"
            >
              <template #icon>
                <n-icon size="48">
                  <ChatbubbleEllipses />
                </n-icon>
              </template>
              <template #extra>
                <n-text depth="3">
                  {{ emptyHint }}
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

            <MessageItem
              v-for="message in thinkingMessages"
              :key="message.id"
              :message="message"
              thinking
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
          :disabled="inputDisabled"
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
import { useRoute } from 'vue-router'
import { NScrollbar, NEmpty, NIcon, NText, NSelect } from 'naive-ui'
import { ChatbubbleEllipses } from '@vicons/ionicons5'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import type { FactoryMode, ToolActivity, TranscriptItem } from '@/types/protocol'

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const uiStore = useUiStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const route = useRoute()
const scrollbarRef = ref()
const inputRef = ref()

const isAgentChatActive = computed(() => Boolean(agentStore.activeChatPackageId))
const isManufacturingRoute = computed(() => route.name === 'Manufacturing')
const isEvolutionRoute = computed(() => route.name === 'Evolution')
const currentFactoryMessageMode = computed<FactoryMode>(() => {
  if (isManufacturingRoute.value) return 'create_agent'
  if (isEvolutionRoute.value) return 'evolve_agent'
  return 'chat'
})
const activeChatPackageTitle = computed(() => {
  const pkg = agentStore.activeChatPackage
  return pkg?.agent_name || pkg?.name || '未命名 Agent'
})
const inputPlaceholder = computed(() => (
  isAgentChatActive.value
    ? `向 ${activeChatPackageTitle.value} 发送消息...`
    : currentFactoryMessageMode.value === 'create_agent'
      ? '描述要制造的 Agent...'
      : currentFactoryMessageMode.value === 'evolve_agent'
        ? selectedEvolutionPackageId.value
          ? `描述对 ${selectedEvolutionPackageTitle.value} 的进化方向...`
          : '先选择要进化的 Agent 包'
    : '输入消息...'
))
const selectedEvolutionPackageId = computed(() => (
  isEvolutionRoute.value ? agentStore.selectedPackageId : null
))
const selectedEvolutionPackageTitle = computed(() => {
  const pkg = agentStore.selectedPackage
  return pkg?.agent_name || pkg?.name || '当前 Agent'
})
const evolutionPackageOptions = computed(() => agentStore.agentPackages.map((pkg) => ({
  label: pkg.agent_name || pkg.name || pkg.package_id,
  value: pkg.package_id,
})))
const inputDisabled = computed(() => (
  runtimeStore.isInputLocked || (isEvolutionRoute.value && !selectedEvolutionPackageId.value)
))
const emptyDescription = computed(() => {
  if (isEvolutionRoute.value) return selectedEvolutionPackageId.value ? '开始进化对话' : '选择进化对象'
  if (isManufacturingRoute.value) return '开始制造对话'
  return '开始对话'
})
const emptyHint = computed(() => {
  if (isEvolutionRoute.value) {
    return selectedEvolutionPackageId.value
      ? '在下方描述这次要进化的方向'
      : '先从上方选择一个已发布 Agent 包'
  }
  return '在下方输入框输入消息开始对话'
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
    .filter((stream) => stream.content.trim().length > 0)
    .map((stream) => ({
      id: stream.streamId,
      role: 'assistant',
      content: stream.content,
      timestamp: new Date().toISOString(),
      streamId: stream.streamId,
    }))
})
const thinkingMessages = computed<TranscriptItem[]>(() => {
  if (!runtimeStore.hasActiveRun || runtimeStore.isAwaitingUserInputInterrupt) return []
  const activeTurn = runtimeStore.activeTurn
  if (!activeTurn?.userMessage) return []
  if (activeTurn.assistantMessages.some((message) => message.content.trim().length > 0)) return []
  if (activeStreams.value.some((stream) => stream.content.trim().length > 0)) return []
  return [
    {
      id: `thinking-${activeTurn.id}`,
      role: 'assistant',
      content: '',
      timestamp: activeTurn.startedAt || new Date().toISOString(),
      metadata: {
        thinking: true,
        request_id: activeTurn.requestId,
      },
    },
  ]
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

function handleEvolutionPackageSelect(packageId: string | null) {
  if (!packageId) return
  agentStore.leaveAgentChat()
  agentStore.selectPackage(packageId)
  runtimeStore.enterFactoryConversation('evolve_agent', packageId)
  workspaceStore.setScope('package')
  uiStore.openRightSidebar('workspace')
  void commands.selectAgentPackage(packageId, 'evolution')
}

function handleSend(message: string, attachments: any[]) {
  const packageId = agentStore.activeChatPackageId
  if (packageId) {
    const agentSessionId = agentStore.selectedSessionId || undefined
    const command = commands.sendAgentPackageMessage(packageId, message, agentSessionId)
    runtimeStore.addUserMessage(message, command.request_id, {
      mode: 'agent_package',
      package_id: packageId,
      agent_session_id: agentSessionId || null,
    })
  } else {
    const mode = currentFactoryMessageMode.value
    if (mode === 'evolve_agent' && !runtimeStore.isAwaitingUserInputInterrupt) {
      const evolutionPackageId = selectedEvolutionPackageId.value
      if (!evolutionPackageId) {
        uiStore.addNotification({
          type: 'warning',
          title: '请选择进化对象',
          message: '进化前需要先选择一个已发布 Agent 包。',
          duration: 3000,
        })
        return
      }
      const command = commands.runAgentEvolution(evolutionPackageId, message)
      runtimeStore.addUserMessage(message, command.request_id, {
        mode,
        package_id: evolutionPackageId,
      })
      nextTick(() => {
        scrollToBottom()
      })
      return
    }
    const command = runtimeStore.isAwaitingUserInputInterrupt
      ? commands.answerInterrupt(message)
      : commands.sendMessage(message, mode, attachments.length > 0 ? attachments : undefined)
    runtimeStore.addUserMessage(message, command.request_id, {
      mode,
      package_id: mode === 'evolve_agent' ? selectedEvolutionPackageId.value : undefined,
      interrupt_resume: runtimeStore.isAwaitingUserInputInterrupt,
    })
  }

  // 滚动到底部
  nextTick(() => {
    scrollToBottom()
  })
}

function handleCancel() {
  commands.cancelRequest('user_cancelled')
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
  () => [activeStreams.value.map((s) => s.content).join(''), toolActivityHint.value, thinkingMessages.value.length].join(''),
  () => {
    nextTick(() => {
      scrollToBottom()
    })
  }
)

onMounted(() => {
  applyRouteMode()

  // 聚焦输入框
  nextTick(() => {
    inputRef.value?.focus()
  })
})

watch(
  () => route.name,
  () => {
    applyRouteMode()
  }
)

function applyRouteMode() {
  if (isManufacturingRoute.value) {
    agentStore.leaveAgentChat()
    const shouldSwitchSession = runtimeStore.currentMode !== 'create_agent'
    runtimeStore.enterFactoryConversation('create_agent')
    if (runtimeStore.activeFactorySessionId && shouldSwitchSession) {
      commands.startSession(true, 'create_agent')
    }
    return
  }
  if (isEvolutionRoute.value) {
    agentStore.leaveAgentChat()
    const shouldSwitchSession = runtimeStore.currentMode !== 'evolve_agent'
    runtimeStore.enterFactoryConversation('evolve_agent', agentStore.selectedPackageId)
    if (runtimeStore.activeFactorySessionId && shouldSwitchSession) {
      commands.startSession(true, 'evolve_agent')
    }
    if (agentStore.agentPackages.length === 0) {
      commands.listAgentPackages()
    }
    return
  }
  if (isAgentChatActive.value) return
  if (route.name === 'Factory' && runtimeStore.currentMode !== 'chat') {
    const shouldSwitchSession = runtimeStore.currentMode !== 'chat'
    runtimeStore.enterFactoryConversation('chat')
    if (runtimeStore.activeFactorySessionId && shouldSwitchSession) {
      commands.startSession(true, 'chat')
    }
  }
}
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

.evolution-target-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  background: var(--n-color);
}

.evolution-target-label {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-2);
}

.evolution-target-select {
  min-width: 0;
  flex: 1;
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
