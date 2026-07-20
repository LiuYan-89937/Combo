<template>
  <div class="factory-view">
    <div class="chat-container">
      <div v-if="isEvolutionRoute" class="evolution-target-bar">
        <span class="evolution-target-label">{{ t('factory.evolutionTarget') }}</span>
        <n-select
          class="evolution-target-select"
          :value="selectedEvolutionPackageId"
          :options="evolutionPackageOptions"
          :placeholder="t('factory.evolutionTargetPlaceholder')"
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
              class="chat-empty"
            >
              <template #icon>
                <n-icon size="56" class="chat-empty-icon">
                  <ChatbubbleEllipses />
                </n-icon>
              </template>
              <template #extra>
                <n-text depth="3" class="chat-empty-hint">
                  {{ emptyHint }}
                </n-text>
              </template>
            </n-empty>

            <template v-for="item in timelineItems" :key="`${item.kind}-${item.id}`">
              <MessageItem
                :message="item.message"
                :streaming="isMessageStreaming(item.message.streamId)"
                quoteable
                :tip-context="tipContextFor(item.message)"
                :workspace-context="messageWorkspaceContext"
                @quote="addMessageReference"
              />
            </template>

            <SchedulerRunStatusCard
              v-for="notice in activeSchedulerRunCards"
              :key="`scheduler-${notice.id}`"
              :notice="notice"
              dismissible
              @details="uiStore.openSchedulerActivityDrawer"
              @dismiss="runtimeStore.dismissSchedulerNoticeFromConversation(notice.id)"
            />

            <MessageItem
              v-for="message in thinkingMessages"
              :key="message.id"
              :message="message"
              thinking
              :workspace-context="messageWorkspaceContext"
            />
          </div>
        </n-scrollbar>
      </div>

      <ToolApprovalPanel
        v-if="hasApprovalRequests"
        class="approval-section"
      />
      <PublishConfirmationPanel
        v-if="runtimeStore.isPublishConfirmationPending"
        class="approval-section"
      />
      <ResourceRequestPanel
        v-if="resourceRequests.length && runtimeStore.activeFactorySessionId"
        :session-id="runtimeStore.activeFactorySessionId"
        :requests="resourceRequests"
        @configured="handleResourceConfigured"
        @skip="handleResourceSkipped"
      />

      <!-- 输入区 -->
      <div class="input-section">
        <MessageInput
          ref="inputRef"
          :placeholder="inputPlaceholder"
          :disabled="inputDisabled"
          :is-running="runtimeStore.hasActiveRun"
          attachments-enabled
          model-selector-enabled
          :model-options="runtimeMainModelOptions"
          :selected-model-profile-id="selectedMainModelProfileId"
          reasoning-control-enabled
          :reasoning-intensity="reasoningIntensity"
          :reference-scope="referenceScope"
          @update:selected-model-profile-id="setSelectedMainModelProfileId"
          @update:reasoning-intensity="setReasoningIntensity"
          @send="handleSend"
          @cancel="handleCancel"
        >
          <template v-if="agentStore.activeChatPackageId" #auxiliary-action>
            <n-button
              text
              :disabled="runtimeStore.hasActiveRun"
              @click="createNewAgentSession"
            >
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              {{ t('agentSessions.newChat') }}
            </n-button>
          </template>
        </MessageInput>
      </div>
    </div>
    <TipPanel v-if="tipScopeId" :scope-type="tipScopeType" :scope-id="tipScopeId" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NScrollbar, NEmpty, NIcon, NText, NSelect } from 'naive-ui'
import { Add, ChatbubbleEllipses } from '@/components/icons'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import { useFactoryConversation } from '@/composables/factory/useFactoryConversation'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import { useCommand } from '@/composables/useCommand'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import PublishConfirmationPanel from '@/components/chat/PublishConfirmationPanel.vue'
import ResourceRequestPanel from '@/components/chat/ResourceRequestPanel.vue'
import SchedulerRunStatusCard from '@/components/scheduler/SchedulerRunStatusCard.vue'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import type { TranscriptItem } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { messageContextReference } from '@/utils/contextReferences'
import TipPanel from '@/components/chat/TipPanel.vue'
import type { TipMessageContext } from '@/stores/tips'
import { useResourceContext } from '@/composables/useResourceContext'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const uiStore = useUiStore()
const commands = useCommand()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const scrollbarRef = ref()
const inputRef = ref()
const referenceStore = useContextReferenceStore()
const resourceContext = useResourceContext()
const { startNewAgentSession } = useAgentSessionNavigation()
const messageWorkspaceContext = computed(() => resourceContext.workspaceContext.value)
const referenceScope = computed(() => [
  'factory',
  runtimeStore.currentMode,
  runtimeStore.activeFactorySessionId || runtimeStore.activeAgentSessionId || 'new',
].join(':'))
const tipAllowed = computed(() => !['Manufacturing', 'Evolution'].includes(String(route.name || '')))
const tipScopeType = computed(() => agentStore.activeChatPackageId ? 'agent-session' : 'factory-session')
const tipScopeId = computed(() => {
  if (!tipAllowed.value) return ''
  return agentStore.activeChatPackageId
    ? runtimeStore.activeAgentSessionId || ''
    : runtimeStore.activeFactorySessionId || ''
})

const {
  isEvolutionRoute,
  selectedEvolutionPackageId,
  evolutionPackageOptions,
  inputPlaceholder,
  inputDisabled,
  loadRuntimeMainModelProfiles,
  runtimeMainModelOptions,
  reasoningIntensity,
  selectedMainModelProfileId,
  setSelectedMainModelProfileId,
  setReasoningIntensity,
  emptyDescription,
  emptyHint,
  applyRouteMode,
  cancelRequest,
  handleEvolutionPackageSelect,
  sendMessage,
} = useFactoryConversation()

const {
  activeStreamContentKey,
  hasActiveStreams,
  hasApprovalRequests,
  isMessageStreaming,
  thinkingMessages,
  timelineItems,
} = useFactoryMessageProjection()

const resourceRequests = computed(() => {
  const values = runtimeStore.pendingInterrupt?.payload?.resource_requests
  return Array.isArray(values) ? values.filter((item): item is { resource_id: string; description?: string; secret?: boolean } => Boolean(item && typeof item.resource_id === 'string')) : []
})

const activeSchedulerRunCards = computed(() => {
  const scope = runtimeStore.activeConversationScope
  if (!scope) return []
  return runtimeStore.schedulerRunNotices.filter((notice) => notice.conversationScope === scope)
})

function handleSend(message: string, attachments: RuntimeAttachmentInput[]) {
  if (!sendMessage(message, attachments)) return
  nextTick(() => {
    scrollToBottom('smooth')
  })
}

function handleCancel() {
  cancelRequest()
}

function createNewAgentSession() {
  const packageId = agentStore.activeChatPackageId
  if (!packageId || runtimeStore.hasActiveRun) return
  void startNewAgentSession(packageId)
}

function addMessageReference(message: TranscriptItem) {
  referenceStore.add(messageContextReference(message), referenceScope.value)
  nextTick(() => inputRef.value?.focus())
}

function tipContextFor(message: TranscriptItem): Omit<TipMessageContext, 'sourceMessageId' | 'sourceRole' | 'sourceContent'> | null {
  if (!tipScopeId.value || message.role !== 'assistant') return null
  return {
    scopeType: tipScopeType.value,
    scopeId: tipScopeId.value,
    agentPackageId: String(message.metadata?.package_id || agentStore.activeChatPackageId || 'factory_chat'),
    modelProfileId: selectedMainModelProfileId.value || null,
    reasoningIntensity: reasoningIntensity.value,
  }
}

function handleResourceConfigured(resourceId: string) {
  handleSend(`运行时资源 ${resourceId} 已安全配置。`, [])
}

function handleResourceSkipped() {
  handleSend('该运行时资源暂不配置，请继续完成可实现部分；发布后可在包详情中填写。', [])
}

function scrollToBottom(behavior: ScrollBehavior = 'auto') {
  scrollbarRef.value?.scrollTo({ position: 'bottom', behavior })
}

function scrollContainer(): HTMLElement | null {
  const scrollbar = scrollbarRef.value as any
  return scrollbar?.scrollbarInstRef?.containerRef
    || scrollbar?.containerRef
    || scrollbar?.$el?.querySelector?.('.n-scrollbar-container')
    || null
}

function isNearBottom(): boolean {
  const container = scrollContainer()
  if (!container) return true
  return container.scrollHeight - container.scrollTop - container.clientHeight < 96
}

function followBottomIfNeeded() {
  const shouldFollow = isNearBottom()
  nextTick(() => {
    if (shouldFollow) scrollToBottom()
  })
}

// 监听消息变化，自动滚动
watch(
  () => runtimeStore.transcript.length,
  followBottomIfNeeded,
)

watch(
  () => runtimeStore.tools.map((tool) => `${tool.activityKey}:${tool.status}:${tool.timestamp}`).join('|'),
  followBottomIfNeeded,
)

watch(
  () => activeSchedulerRunCards.value.map((notice) => `${notice.id}:${notice.status}`).join('|'),
  followBottomIfNeeded,
)

// 监听流式输出，自动滚动
watch(
  () => activeStreamContentKey.value,
  followBottomIfNeeded,
)

onMounted(async () => {
  if (!await openRoutedAgentSession()) applyRouteMode()
  void loadRuntimeMainModelProfiles()

  // 聚焦输入框
  nextTick(() => {
    inputRef.value?.focus()
  })
})

watch(
  () => route.fullPath,
  async () => {
    if (!await openRoutedAgentSession()) applyRouteMode()
  },
)

watch(
  () => `${agentStore.activeChatPackageId || ''}:${runtimeStore.activeAgentSessionId || ''}`,
  () => {
    const packageId = agentStore.activeChatPackageId
    const sessionId = runtimeStore.activeAgentSessionId
    if (route.name !== 'Factory' || !packageId || !sessionId) return
    if (
      routeQueryText(route.query.package_id) === packageId
      && routeQueryText(route.query.session_id) === sessionId
    ) return
    void router.replace({ name: 'Factory', query: { package_id: packageId, session_id: sessionId } })
  },
)

async function openRoutedAgentSession(): Promise<boolean> {
  if (route.name !== 'Factory') return false
  const packageId = routeQueryText(route.query.package_id)
  const sessionId = routeQueryText(route.query.session_id)
  if (!packageId) return false
  if (!sessionId && routeQueryText(route.query.new) === '1') {
    if (
      agentStore.activeChatPackageId === packageId
      && agentStore.selectedSessionId === null
      && runtimeStore.activeAgentSessionId === null
      && runtimeStore.currentMode === 'agent_package'
    ) return true
    agentStore.enterAgentChat(packageId, null)
    runtimeStore.showEmptyAgentPackageSession(packageId)
    await commands.selectAgentPackage(packageId, 'run')
    return true
  }
  if (!sessionId) return false
  if (
    agentStore.activeChatPackageId === packageId
    && agentStore.selectedSessionId === sessionId
    && runtimeStore.activeAgentSessionId === sessionId
    && runtimeStore.currentMode === 'agent_package'
  ) return true
  const collaborationId = routeQueryText(route.query.collaboration_id)
  const collaborationTaskId = routeQueryText(route.query.collaboration_task_id)
  agentStore.enterAgentChat(packageId, sessionId)
  if (collaborationId) {
    runtimeStore.enterCollaborationConversation(
      collaborationId,
      packageId,
      sessionId,
      collaborationTaskId,
    )
  } else {
    runtimeStore.expectAgentPackageSession(packageId, sessionId)
  }
  await commands.selectAgentPackage(packageId, 'run')
  await commands.loadAgentPackageSession(
    packageId,
    sessionId,
    collaborationId,
    collaborationTaskId,
  )
  return true
}

function routeQueryText(value: unknown): string | null {
  const raw = Array.isArray(value) ? value[0] : value
  const text = String(raw || '').trim()
  return text || null
}
</script>

<style scoped>
.factory-view {
  height: 100%;
  display: flex;
  flex-direction: row;
  background: var(--app-surface);
  position: relative;
}

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--app-space-xl) var(--app-space-xl) var(--app-space-lg);
  max-width: var(--app-chat-max-width);
  margin: 0 auto;
  width: min(100%, var(--app-chat-max-width));
  transition: width .24s var(--app-transition-spring), max-width .24s var(--app-transition-spring);
}

.evolution-target-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
}

.evolution-target-label {
  flex-shrink: 0;
  font-size: var(--app-font-md);
  font-weight: 600;
  color: var(--app-text-secondary);
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
  padding: var(--app-space-lg) var(--app-space-lg) var(--app-space-xxl);
}

.chat-empty {
  margin-top: 15vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.chat-empty-icon {
  display: block;
  color: var(--app-text-muted);
  opacity: 0.6;
  line-height: 1;
  animation: app-pulse-soft 2.4s ease-in-out infinite;
}

.chat-empty-hint {
  display: block;
  margin-top: var(--app-space-sm);
  font-size: var(--app-font-md);
  text-align: center;
  line-height: var(--app-leading-relaxed);
  max-width: 360px;
}

.approval-section {
  margin-top: var(--app-space-md);
}

.input-section {
  margin-top: var(--app-space-lg);
  padding-top: var(--app-space-md);
  border-top: 1px solid var(--app-divider);
}

/* 窄屏适配 */
@media (max-width: 768px) {
  .chat-container {
    padding: var(--app-space-md);
  }
  .evolution-target-bar {
    flex-direction: column;
    align-items: stretch;
    gap: var(--app-space-sm);
  }
}

/* 超宽屏（>1600）保留呼吸感，稍微放宽 */
@media (min-width: 1600px) {
  .chat-container {
    max-width: 1100px;
  }
}
</style>
