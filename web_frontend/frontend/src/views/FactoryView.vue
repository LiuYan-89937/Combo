<template>
  <div class="factory-view">
    <div class="chat-container">
      <!-- 消息列表 -->
      <div class="messages-section">
        <n-scrollbar
          ref="scrollbarRef"
          class="messages-scrollbar"
          @scroll="handleMessagesScroll"
        >
          <div class="messages-list">
            <div
              v-if="
                timelineItems.length === 0
                && !hasActiveStreams
              "
              class="chat-empty"
            >
              <ComboMascot state="idle" :size="148" />
            </div>

            <template v-for="item in timelineItems" :key="item.id">
              <MessageItem
                :message="item.message"
                :messages="item.messages"
                :streaming="isMessageStreaming(item.message.streamId)"
                :thinking="item.thinking"
                quoteable
                :workspace-context="messageWorkspaceContext"
                @quote="addMessageReference"
              />
            </template>

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
          :disabled-hint="modelConfigurationMissing ? t('chat.configureModelLink') : ''"
          :disabled-hint-route="{ name: 'ModelPool' }"
          :is-running="runtimeStore.hasActiveRun"
          :queued-count="runtimeStore.queuedRequestCount"
          :queued-messages="runtimeStore.queuedMessages"
          :running-message-mode="runningMessageMode"
          attachments-enabled
          model-selector-enabled
          :model-options="runtimeMainModelOptions"
          :selected-model-profile-id="selectedMainModelProfileId"
          reasoning-control-enabled
          :reasoning-intensity="reasoningIntensity"
          execution-control-enabled
          :execution-preference="executionPreference"
          :force-collaboration="forceCollaboration"
          approval-control-enabled
          :approval-mode="approvalMode"
          :reference-scope="referenceScope"
          :draft-scope="referenceScope"
          @update:selected-model-profile-id="setSelectedMainModelProfileId"
          @update:reasoning-intensity="setReasoningIntensity"
          @update:execution-preference="setExecutionPreference"
          @update:force-collaboration="setForceCollaboration"
          @update:approval-mode="setApprovalMode"
          @send="handleSend"
          @cancel="handleCancel"
          @steer="handleSteer"
          @cancel-queued="handleCancelQueued"
        >
          <template #before-send><ContextProgressControl /></template>
        </MessageInput>
      </div>
    </div>
    <ConversationFloatingDock
      :session-id="backgroundTaskSessionId"
      :workspace-id="runtimeStore.activeWorkspaceId"
      @request-new-agent-session="requestNewAgentSession"
    />
    <NewAgentSessionDialog
      v-if="pendingWorkspaceAction"
      :show="true"
      :package-id="pendingWorkspaceAction.packageId"
      :initial-workspace-id="pendingWorkspaceAction.initialWorkspaceId"
      @update:show="handleWorkspaceDialogVisibility"
      @create="completeWorkspaceSelection"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onBeforeUnmount, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NScrollbar } from 'naive-ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useI18n } from '@/composables/useI18n'
import { useFactoryConversation } from '@/composables/factory/useFactoryConversation'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import { useCommand } from '@/composables/useCommand'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import ConversationFloatingDock from '@/components/chat/ConversationFloatingDock.vue'
import NewAgentSessionDialog from '@/components/agent/NewAgentSessionDialog.vue'
import ContextProgressControl from '@/components/chat/ContextProgressControl.vue'
import ComboMascot from '@/components/brand/ComboMascot.vue'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import type { TranscriptItem } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { messageContextReference } from '@/utils/contextReferences'
import { useResourceContext } from '@/composables/useResourceContext'
import { useWorkspaceStore } from '@/stores/workspace'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'
import { agentPackageConversationScope } from '@/stores/runtime/scopes'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const commands = useCommand()
const workspaceStore = useWorkspaceStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const scrollbarRef = ref()
const inputRef = ref()
const referenceStore = useContextReferenceStore()
const resourceContext = useResourceContext()
const { startNewAgentSession } = useAgentSessionNavigation()
let followBottomFrame: number | null = null
let followBottomScheduled = false
const followsLatestMessage = ref(true)
type PendingWorkspaceAction = {
  kind: 'new_session'
  packageId: string
  initialWorkspaceId: string | null
} | {
  kind: 'first_message'
  packageId: string
  initialWorkspaceId: null
  message: string
  attachments: RuntimeAttachmentInput[]
}
const pendingWorkspaceAction = ref<PendingWorkspaceAction | null>(null)
const messageWorkspaceContext = computed(() => resourceContext.workspaceContext.value)
const referenceScope = computed(() => [
  'factory',
  runtimeStore.currentMode,
  runtimeStore.activeFactorySessionId || runtimeStore.activeAgentSessionId || 'new',
].join(':'))

const {
  inputPlaceholder,
  inputDisabled,
  modelConfigurationMissing,
  loadRuntimeMainModelProfiles,
  runtimeMainModelOptions,
  reasoningIntensity,
  executionPreference,
  forceCollaboration,
  runningMessageMode,
  approvalMode,
  selectedMainModelProfileId,
  setSelectedMainModelProfileId,
  setReasoningIntensity,
  setExecutionPreference,
  setForceCollaboration,
  setApprovalMode,
  cancelRequest,
  sendMessage,
  steerQueuedRequest,
  cancelQueuedRequest,
} = useFactoryConversation()

const {
  activeStreamContentKey,
  hasActiveStreams,
  hasApprovalRequests,
  isMessageStreaming,
  timelineItems,
} = useFactoryMessageProjection()

const backgroundTaskSessionId = computed(() => (
  runtimeStore.activeAgentSessionId || runtimeStore.activeFactorySessionId || null
))


function handleSend(message: string, attachments: RuntimeAttachmentInput[]) {
  const packageId = agentStore.activeChatPackageId
  if (
    packageId
    && !agentStore.selectedSessionId
    && !runtimeStore.activeWorkspaceId
  ) {
    pendingWorkspaceAction.value = {
      kind: 'first_message',
      packageId,
      initialWorkspaceId: null,
      message,
      attachments,
    }
    return
  }
  sendAndFollow(message, attachments)
}

function requestNewAgentSession(packageId: string, initialWorkspaceId: string | null) {
  pendingWorkspaceAction.value = {
    kind: 'new_session',
    packageId,
    initialWorkspaceId,
  }
}

function handleWorkspaceDialogVisibility(show: boolean) {
  if (show) return
  restorePendingDraft()
  pendingWorkspaceAction.value = null
}

async function completeWorkspaceSelection(workspaceId: string | null) {
  const action = pendingWorkspaceAction.value
  if (!action) return
  pendingWorkspaceAction.value = null
  await startNewAgentSession(action.packageId, workspaceId)
  if (action.kind === 'first_message' && !sendAndFollow(action.message, action.attachments, workspaceId)) {
    inputRef.value?.restoreDraft(action.message, action.attachments)
  }
}

function restorePendingDraft() {
  const action = pendingWorkspaceAction.value
  if (action?.kind === 'first_message') {
    inputRef.value?.restoreDraft(action.message, action.attachments)
  }
}

function sendAndFollow(
  message: string,
  attachments: RuntimeAttachmentInput[],
  workspaceId?: string | null,
): boolean {
  if (!sendMessage(message, attachments, workspaceId)) return false
  followsLatestMessage.value = true
  nextTick(() => {
    scrollToBottom()
  })
  return true
}

function handleCancel() {
  cancelRequest()
}

function handleSteer(requestId: string) {
  steerQueuedRequest(requestId)
}

function handleCancelQueued(message: { requestId: string; content: string }) {
  cancelQueuedRequest(message.requestId)
  inputRef.value?.restoreDraft(message.content, [])
  nextTick(() => inputRef.value?.focus())
}

function addMessageReference(message: TranscriptItem) {
  referenceStore.add(messageContextReference(message), referenceScope.value)
  nextTick(() => inputRef.value?.focus())
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
  return container.scrollHeight - container.scrollTop - container.clientHeight < 48
}

function handleMessagesScroll() {
  followsLatestMessage.value = isNearBottom()
}

function followBottomIfNeeded() {
  if (!followsLatestMessage.value || followBottomScheduled) return
  followBottomScheduled = true
  nextTick(() => {
    followBottomFrame = window.requestAnimationFrame(() => {
      followBottomFrame = null
      followBottomScheduled = false
      if (!followsLatestMessage.value) return
      scrollToBottom()
    })
  })
}

onBeforeUnmount(() => {
  if (followBottomFrame !== null) window.cancelAnimationFrame(followBottomFrame)
  followBottomFrame = null
  followBottomScheduled = false
})

// 监听消息变化，自动滚动
watch(
  () => runtimeStore.transcript.length,
  followBottomIfNeeded,
)

watch(
  () => runtimeStore.tools.map((tool) => `${tool.activityKey}:${tool.status}:${tool.timestamp}`).join('|'),
  followBottomIfNeeded,
)

// 监听流式输出，自动滚动
watch(
  () => activeStreamContentKey.value,
  followBottomIfNeeded,
)

let routeActivationVersion = 0

onMounted(async () => {
  // Model availability controls the input state and must not wait for session restoration.
  void loadRuntimeMainModelProfiles()
  await activateCurrentRoute()

  if (!route.meta.showcaseMode) {
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
})

watch(
  () => route.fullPath,
  () => void activateCurrentRoute(),
)

watch(
  () => `${agentStore.activeChatPackageId || ''}:${runtimeStore.activeAgentSessionId || ''}`,
  () => {
    const sessionId = runtimeStore.activeAgentSessionId
    if (route.name !== 'ChatNew' && route.name !== 'ChatSession') return
    if (
      !sessionId
      && agentStore.selectedSessionId === null
      && route.name === 'ChatSession'
      && runtimeStore.currentMode === 'agent_package'
    ) {
      void router.replace({ name: 'ChatNew' })
      return
    }
    if (!sessionId) return
    if (route.name !== 'ChatNew') return
    void router.replace({ name: 'ChatSession', params: { sessionId } })
  },
)

async function activateCurrentRoute(): Promise<void> {
  const version = ++routeActivationVersion
  await openRoutedAgentSession(version)
}

async function openRoutedAgentSession(version: number): Promise<boolean> {
  if (route.name !== 'ChatNew' && route.name !== 'ChatSession') return false
  const packageId = SYSTEM_CHAT_PACKAGE_ID
  const sessionId = routeParamText(route.params.sessionId)
  activateAgentWorkspace()
  if (route.name === 'ChatNew') {
    const workspaceId = routeQueryText(route.query.workspace)
    if (emptyAgentRouteIsActive(packageId, workspaceId)) return true
    agentStore.enterAgentChat(packageId, null)
    runtimeStore.showEmptyAgentPackageSession(packageId, workspaceId)
    await commands.selectAgentPackage(packageId)
    return true
  }
  if (!sessionId) return false
  const routedScope = agentPackageConversationScope(packageId, sessionId)
  if (
    agentStore.activeChatPackageId === packageId
    && runtimeStore.currentMode === 'agent_package'
    && runtimeStore.activeAgentSessionId === sessionId
    && runtimeStore.activeConversationScope === routedScope
  ) {
    return true
  }
  agentStore.enterAgentChat(packageId, sessionId)
  runtimeStore.expectAgentPackageSession(packageId, sessionId)
  await commands.selectAgentPackage(packageId)
  if (version !== routeActivationVersion || !routeMatchesAgentSession(packageId, sessionId)) return true
  await commands.loadAgentPackageSession(
    packageId,
    sessionId,
  )
  return true
}

function activateAgentWorkspace(): void {
  workspaceStore.setScope('workdir')
}

function routeMatchesAgentSession(packageId: string, sessionId: string): boolean {
  return packageId === SYSTEM_CHAT_PACKAGE_ID
    && route.name === 'ChatSession'
    && routeParamText(route.params.sessionId) === sessionId
}

function emptyAgentRouteIsActive(packageId: string, workspaceId: string | null): boolean {
  return agentStore.activeChatPackageId === packageId
    && agentStore.selectedSessionId === null
    && runtimeStore.activeAgentSessionId === null
    && runtimeStore.currentMode === 'agent_package'
    && runtimeStore.activeWorkspaceId === workspaceId
}

function routeQueryText(value: unknown): string | null {
  const raw = Array.isArray(value) ? value[0] : value
  const text = String(raw || '').trim()
  return text || null
}

function routeParamText(value: unknown): string | null {
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
  padding: var(--app-space-xl) clamp(54px, 6vw, 80px) var(--app-space-lg);
  max-width: var(--app-chat-max-width);
  margin: 0 auto;
  width: min(100%, var(--app-chat-max-width));
  transition: width .24s var(--app-transition-spring), max-width .24s var(--app-transition-spring);
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
  display: grid;
  place-items: center;
  margin-top: 12vh;
  pointer-events: none;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.approval-section {
  margin-top: var(--app-space-md);
}

.input-section {
  margin-top: var(--app-space-lg);
  padding-top: var(--app-space-sm);
}


/* 窄屏适配 */
@media (max-width: 768px) {
  .chat-container {
    padding: var(--app-space-md);
  }
}

/* 超宽屏（>1600）保留呼吸感，稍微放宽 */
@media (min-width: 1600px) {
  .chat-container {
    max-width: 1100px;
  }
}
</style>
