<template>
  <div class="conversation-view">
    <ComputerUseCapsule />
    <div
      class="chat-container"
      :style="{ '--composer-occlusion': `${composerOcclusion}px` }"
    >
      <!-- 消息列表 -->
      <div class="messages-section">
        <n-scrollbar
          ref="scrollbarRef"
          class="messages-scrollbar"
          @scroll="handleMessagesScroll"
          @wheel="markUserScrollIntent"
          @touchmove="markUserScrollIntent"
          @keydown="markUserScrollIntent"
        >
          <div ref="messagesListRef" class="messages-list">
            <div v-if="runtimeStore.historyBefore" class="history-navigation">
              <n-button
                quaternary
                :loading="loadingHistoryScope === runtimeStore.activeConversationScope"
                @click="loadEarlierTurns"
              >{{ t('chat.loadEarlier') }}</n-button>
            </div>
            <div
              v-if="
                timelineItems.length === 0
                && !hasActiveStreams
                && !currentActivity
              "
              class="chat-empty"
            >
              <ComboMascot state="idle" :size="148" />
            </div>

            <ViewportContent
              v-for="item in timelineItems"
              :key="item.id"
              :data-anchor-id="item.id"
              :active="isTimelineItemRunning(item) || isTimelineItemStreaming(item)"
            >
              <MessageItem
                :message="item.message"
                :messages="item.messages"
                :streaming="isTimelineItemStreaming(item)"
                :running="isTimelineItemRunning(item)"
                quoteable
                :workspace-context="messageWorkspaceContext"
                :git-changes="gitChangesStore.changesFor(item.message.metadata?.request_id)"
                @quote="addMessageReference"
              />
            </ViewportContent>

            <CurrentActivitySummary
              v-if="currentActivity"
              :activity="currentActivity"
            />

          </div>
        </n-scrollbar>
        <n-button
          v-if="showScrollToLatest"
          class="scroll-latest-button"
          circle
          size="small"
          :aria-label="t('chat.scrollToLatest')"
          :title="t('chat.scrollToLatest')"
          @click="jumpToLatest"
        >
          <template #icon>
            <n-icon><ArrowDownOutline /></n-icon>
          </template>
        </n-button>
      </div>

      <div ref="composerDockRef" class="conversation-bottom-dock">
        <QuestionInterruptPanel
          v-if="hasUserQuestionInterrupt"
          class="approval-section"
        />
        <ToolApprovalPanel
          v-else-if="hasApprovalRequests"
          class="approval-section"
        />

        <div class="input-section">
          <MessageInput
            ref="inputRef"
            :placeholder="inputPlaceholder"
            :disabled="inputDisabled"
            :disabled-hint="modelConfigurationMissing ? t('chat.configureModelLink') : ''"
            :disabled-hint-route="{ name: 'ModelPool', query: { tab: 'credentials' } }"
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
    </div>
    <ConversationFloatingDock
      :session-id="backgroundTaskSessionId"
      :workspace-id="runtimeStore.activeWorkspaceId"
      :show-outline="showOutlineToggle"
      :outline-entries="outlineEntries"
      :active-anchor-id="activeAnchorId"
      @request-new-agent-session="requestNewAgentSession"
      @outline-jump="jumpFromOutline"
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
import { NButton, NIcon, NScrollbar } from 'naive-ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import { useConversation } from '@/composables/conversation/useConversation'
import { useConversationMessageProjection } from '@/composables/conversation/useConversationMessageProjection'
import { useCommand } from '@/composables/useCommand'
import MessageItem from '@/components/chat/MessageItem.vue'
import ViewportContent from '@/components/chat/ViewportContent.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ComputerUseCapsule from '@/components/chat/ComputerUseCapsule.vue'
import CurrentActivitySummary from '@/components/chat/CurrentActivitySummary.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import QuestionInterruptPanel from '@/components/chat/QuestionInterruptPanel.vue'
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
import { useGitChangesStore } from '@/stores/gitChanges'
import { workspaceApi } from '@/api/workspace'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'
import { agentPackageConversationScope } from '@/stores/runtime/scopes'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { ArrowDownOutline } from '@/components/icons'
import { buildConversationOutline } from '@/utils/conversationOutline'
import { useConversationOutlineNavigation } from '@/composables/conversation/useConversationOutlineNavigation'

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const uiStore = useUiStore()
const commands = useCommand()
const workspaceStore = useWorkspaceStore()
const gitChangesStore = useGitChangesStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const scrollbarRef = ref()
const messagesListRef = ref<HTMLElement | null>(null)
const loadingHistoryScope = ref<string | null>(null)
const composerDockRef = ref<HTMLElement | null>(null)
const composerOcclusion = ref(88)
const inputRef = ref()
const referenceStore = useContextReferenceStore()
const resourceContext = useResourceContext()
const { startNewAgentSession } = useAgentSessionNavigation()
let followBottomFrame: number | null = null
let followBottomScheduled = false
let messagesResizeObserver: ResizeObserver | null = null
let composerResizeObserver: ResizeObserver | null = null
const followsLatestMessage = ref(true)
const showScrollToLatest = computed(() => (
  !followsLatestMessage.value && runtimeStore.transcript.length > 0
))
const latestScrollTop = ref<number | null>(null)
const bottomLockEpsilonPx = 1
const upwardScrollEpsilonPx = 0.5
let userScrollIntentUntil = 0
const outlineTurnCount = computed(() => timelineItems.value.filter(item => item.message.role === 'user').length)
const outlineEntries = computed(() => (
  uiStore.conversationDockPanel === 'outline'
    ? buildConversationOutline(timelineItems.value)
    : []
))
const outlineNavigation = useConversationOutlineNavigation({
  messageList: messagesListRef,
  scrollContainer,
  scrollTo: top => scrollbarRef.value?.scrollTo({ top, behavior: 'smooth' }),
  stopFollowingLatest: () => { followsLatestMessage.value = false },
})
const {
  activeAnchorId,
  anchors: timelineAnchors,
  scheduleUpdate: scheduleActiveAnchorUpdate,
} = outlineNavigation
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
  'conversation',
  runtimeStore.currentMode,
  runtimeStore.activeMainSessionId || runtimeStore.activeAgentSessionId || 'new',
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
} = useConversation()

const {
  activeStreamContentKey,
  currentActivity,
  hasActiveStreams,
  hasApprovalRequests,
  hasUserQuestionInterrupt,
  isTimelineItemStreaming,
  isTimelineItemRunning,
  timelineItems,
} = useConversationMessageProjection()

const backgroundTaskSessionId = computed(() => (
  runtimeStore.activeAgentSessionId || runtimeStore.activeMainSessionId || null
))

const showOutlineToggle = computed(() => outlineTurnCount.value > 1)


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
  resumeLatestMessageFollow()
  nextTick(() => {
    followBottomIfNeeded()
  })
  return true
}

function handleCancel() {
  cancelRequest()
}

function handleSteer(requestId: string) {
  steerQueuedRequest(requestId)
}

const cancelledDrafts = ref<Record<string, { content: string; scope: string | null }>>({})

function handleCancelQueued(message: { requestId: string; content: string }) {
  if (!cancelQueuedRequest(message.requestId)) return
  cancelledDrafts.value[message.requestId] = {
    content: message.content,
    scope: runtimeStore.activeConversationScope,
  }
}

watch(() => Object.entries(cancelledDrafts.value).map(([requestId, draft]) => ({
  requestId,
  draft,
  request: runtimeStore.activeRequests[requestId],
  cancelling: runtimeStore.activeRequests[requestId]?.payload?.cancel_pending,
  withdrawn: runtimeStore.activeRequests[requestId]?.payload?.message_status === 'cancelled',
  scope: runtimeStore.activeConversationScope,
})), entries => {
  for (const { requestId, draft, request, cancelling, withdrawn, scope } of entries) {
    if (scope !== draft.scope || !request || !cancelling) {
      delete cancelledDrafts.value[requestId]
      if (scope !== draft.scope) continue
      if (withdrawn) {
        inputRef.value?.restoreCancelledDraft(draft.content)
      } else if (request?.payload?.cancel_rejected) {
        uiStore.addNotification({
          type: 'warning',
          title: t('common.cancel'),
          message: t('chat.messageCancelRejected'),
        })
      }
    }
  }
})

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

function isAtBottom(): boolean {
  const container = scrollContainer()
  if (!container) return true
  return container.scrollHeight - container.scrollTop - container.clientHeight <= bottomLockEpsilonPx
}

function handleMessagesScroll() {
  const container = scrollContainer()
  if (!container) return

  const currentScrollTop = container.scrollTop
  const previousScrollTop = latestScrollTop.value
  latestScrollTop.value = currentScrollTop
  scheduleActiveAnchorUpdate()
  const userInitiated = Date.now() <= userScrollIntentUntil
  const movedUp = previousScrollTop !== null
    && currentScrollTop < previousScrollTop - upwardScrollEpsilonPx

  // Content growth and layout changes can emit scroll events without user input.
  // A real upward movement wins immediately, even inside the former bottom
  // tolerance area. Following resumes only after the viewport truly reaches
  // the bottom again.
  if (movedUp && (userInitiated || followsLatestMessage.value)) {
    followsLatestMessage.value = false
    return
  }
  if (isAtBottom()) {
    followsLatestMessage.value = true
  }
}

function markUserScrollIntent(event: Event) {
  // Reading an expanded detail also suspends main-chat following. Native
  // scroll chaining decides which viewport moves when a detail hits its edge.
  if (event.type === 'keydown') {
    const key = (event as KeyboardEvent).key
    if (!['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(key)) return
    if (['ArrowUp', 'PageUp', 'Home'].includes(key) || (key === ' ' && (event as KeyboardEvent).shiftKey)) {
      followsLatestMessage.value = false
    }
  } else if (event instanceof WheelEvent && event.deltaY < 0) {
    // Detach before the next animation frame so an already-scheduled stream
    // follow cannot override a small upward wheel or trackpad gesture.
    followsLatestMessage.value = false
  } else if (event.type === 'touchmove') {
    followsLatestMessage.value = false
  }
  userScrollIntentUntil = Date.now() + 500
}

function resumeLatestMessageFollow() {
  followsLatestMessage.value = true
  latestScrollTop.value = null
}

function jumpToLatest() {
  resumeLatestMessageFollow()
  nextTick(() => scrollToBottom('smooth'))
}

async function loadEarlierTurns() {
  const scope = runtimeStore.activeConversationScope
  const sessionId = runtimeStore.activeAgentSessionId
  const before = runtimeStore.historyBefore
  if (!scope || !sessionId || !before || loadingHistoryScope.value === scope) return
  loadingHistoryScope.value = scope
  followsLatestMessage.value = false
  try {
    await commands.loadEarlierAgentPackageTurns(SYSTEM_CHAT_PACKAGE_ID, sessionId, before)
  } finally {
    if (loadingHistoryScope.value === scope) loadingHistoryScope.value = null
  }
}

function jumpFromOutline(anchorId: string) {
  outlineNavigation.jump(anchorId)
}

function followBottomIfNeeded() {
  if (!followsLatestMessage.value || followBottomScheduled) return
  followBottomScheduled = true
  nextTick(() => {
    followBottomFrame = window.requestAnimationFrame(() => {
      followBottomFrame = null
      if (!followsLatestMessage.value) {
        followBottomScheduled = false
        return
      }
      scrollToBottom()
      followBottomFrame = window.requestAnimationFrame(() => {
        followBottomFrame = null
        followBottomScheduled = false
        if (followsLatestMessage.value) {
          scrollToBottom()
          latestScrollTop.value = scrollContainer()?.scrollTop ?? null
        }
      })
    })
  })
}

function observeMessagesSize() {
  messagesResizeObserver?.disconnect()
  messagesResizeObserver = null
  const target = messagesListRef.value
  if (!target || typeof ResizeObserver === 'undefined') return
  messagesResizeObserver = new ResizeObserver(() => followBottomIfNeeded())
  messagesResizeObserver.observe(target)
}

function observeComposerSize() {
  composerResizeObserver?.disconnect()
  composerResizeObserver = null
  const target = composerDockRef.value
  if (!target || typeof ResizeObserver === 'undefined') return
  const update = () => {
    composerOcclusion.value = Math.ceil(target.getBoundingClientRect().height)
    followBottomIfNeeded()
  }
  composerResizeObserver = new ResizeObserver(update)
  composerResizeObserver.observe(target)
  update()
}

onBeforeUnmount(() => {
  if (followBottomFrame !== null) window.cancelAnimationFrame(followBottomFrame)
  followBottomFrame = null
  followBottomScheduled = false
  messagesResizeObserver?.disconnect()
  messagesResizeObserver = null
  composerResizeObserver?.disconnect()
  composerResizeObserver = null
})

watch(
  () => runtimeStore.conversationTurns.map(turn => `${turn.requestId || ''}:${turn.status}`).join('|'),
  () => void captureCompletedGitTurns(),
)

async function captureCompletedGitTurns() {
  const workspaceId = runtimeStore.activeWorkspaceId
  if (!workspaceId) return
  const workspace = (await workspaceApi.projects()).workspaces
    .find(item => item.workspace_id === workspaceId)
  if (!workspace?.workdir_root) return
  const terminal = new Set(['completed', 'stopped', 'cancelled', 'failed'])
  runtimeStore.conversationTurns.forEach((turn) => {
    if (turn.requestId && terminal.has(turn.status)) {
      void gitChangesStore.captureCompletedTurn(workspace.workdir_root, turn.requestId)
    }
  })
}

// 思考、正文、工具状态和活动摘要共用一个渲染变化源；尺寸观察器负责
// 补充 Markdown、图片和折叠面板完成异步布局后的变化。
watch(
  () => activeStreamContentKey.value,
  () => {
    followBottomIfNeeded()
    scheduleActiveAnchorUpdate()
  },
)

watch(
  () => [
    runtimeStore.activeConversationScope,
    runtimeStore.activeMainSessionId,
    runtimeStore.activeAgentSessionId,
  ].join('|'),
  () => {
    // 切换会话时从“最新位置”开始，不继承上一个会话的阅读状态。
    resumeLatestMessageFollow()
    outlineNavigation.reset()
    if (uiStore.conversationDockPanel === 'outline') uiStore.setConversationDockPanel(null)
    nextTick(() => {
      followBottomIfNeeded()
      scheduleActiveAnchorUpdate()
    })
  },
)

watch(messagesListRef, observeMessagesSize, { flush: 'post' })
watch(composerDockRef, observeComposerSize, { flush: 'post' })

watch(
  () => [runtimeStore.activeConversationScope, runtimeStore.historyBefore] as const,
  async ([scope], [previousScope, previousCursor]) => {
    if (scope !== previousScope || !previousCursor) return
    const container = scrollContainer()
    if (!container) return
    const viewportTop = container.getBoundingClientRect().top
    const anchor = timelineAnchors().find(element => element.getBoundingClientRect().bottom > viewportTop)
    if (!anchor) return
    const top = anchor.getBoundingClientRect().top
    await nextTick()
    if (scope !== runtimeStore.activeConversationScope || !anchor.isConnected) return
    // Apply only the remaining displacement, including on engines without
    // native scroll anchoring. Growth at the live tail doesn't move this anchor.
    container.scrollTop += anchor.getBoundingClientRect().top - top
    latestScrollTop.value = container.scrollTop
  },
  { flush: 'pre' },
)

let routeActivationVersion = 0

onMounted(async () => {
  // Model availability controls the input state and must not wait for session restoration.
  void loadRuntimeMainModelProfiles()
  await activateCurrentRoute()
  await nextTick()
  observeMessagesSize()
  observeComposerSize()
  scheduleActiveAnchorUpdate()

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
    await ensureAgentPackageSelected(packageId)
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
  const scopeIsCached = Boolean(runtimeStore.conversationScopes[routedScope])
  agentStore.enterAgentChat(packageId, sessionId)
  runtimeStore.expectAgentPackageSession(packageId, sessionId)
  await ensureAgentPackageSelected(packageId)
  if (version !== routeActivationVersion || !routeMatchesAgentSession(packageId, sessionId)) return true
  if (scopeIsCached) return true
  await commands.loadAgentPackageSession(
    packageId,
    sessionId,
  )
  return true
}

async function ensureAgentPackageSelected(packageId: string): Promise<void> {
  if (runtimeStore.selectedAgentPackage?.package_id === packageId) return
  await commands.selectAgentPackage(packageId)
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
.conversation-view {
  height: 100%;
  display: flex;
  flex-direction: row;
  background: var(--app-surface);
  position: relative;
}

.chat-container {
  --chat-horizontal-gutter: clamp(54px, 6vw, 80px);
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  position: relative;
  box-sizing: border-box;
  padding: var(--app-space-xl) var(--chat-horizontal-gutter) var(--app-space-lg);
  max-width: var(--app-chat-max-width);
  margin: 0 auto;
  width: min(100%, var(--app-chat-max-width));
  transition: width .24s var(--app-transition-spring), max-width .24s var(--app-transition-spring);
}

.messages-section {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.messages-scrollbar {
  height: 100%;
}

.messages-list {
  --conversation-tail-room: clamp(180px, 34vh, 360px);
  padding:
    var(--app-space-lg)
    var(--app-space-lg)
    calc(var(--composer-occlusion, 88px) + var(--conversation-tail-room) + 24px);
}

.history-navigation {
  display: flex;
  justify-content: center;
  overflow-anchor: none;
}

.messages-list > .viewport-content + .viewport-content {
  margin-top: 2px;
}

.scroll-latest-button {
  position: absolute;
  right: 18px;
  bottom: calc(var(--composer-occlusion, 88px) + 26px);
  z-index: 4;
  border: 1px solid var(--app-border);
  background: var(--app-surface-elevated);
  color: var(--app-text-secondary);
  box-shadow: none;
  transition: color var(--app-transition-base), border-color var(--app-transition-base), transform var(--app-transition-spring);
}

.scroll-latest-button:hover {
  border-color: var(--app-text);
  color: var(--app-text);
  transform: translateY(-2px);
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
  margin: 0 8px;
}

.conversation-bottom-dock {
  position: absolute;
  right: var(--chat-horizontal-gutter);
  bottom: var(--app-space-lg);
  left: var(--chat-horizontal-gutter);
  z-index: 6;
  display: grid;
  gap: 8px;
}

.input-section {
  min-width: 0;
}


/* 窄屏适配 */
@media (max-width: 768px) {
  .chat-container {
    --chat-horizontal-gutter: var(--app-space-md);
    padding: var(--app-space-md);
  }

  .conversation-bottom-dock {
    bottom: var(--app-space-md);
  }
}

/* 超宽屏（>1600）保留呼吸感，稍微放宽 */
@media (min-width: 1600px) {
  .chat-container {
    max-width: 1100px;
  }
}
</style>
