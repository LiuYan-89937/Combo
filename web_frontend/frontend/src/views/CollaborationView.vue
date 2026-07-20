<template>
  <div class="collaboration-view">
    <div class="chat-container">
      <div
        v-if="runtimeStatus"
        class="runtime-status-banner"
        :data-status="runtimeStatus"
        role="status"
        aria-live="polite"
      >
        <span class="runtime-status-dot" aria-hidden="true"></span>
        <div class="runtime-status-copy">
          <strong>{{ runtimeStatusTitle }}</strong>
          <span>{{ runtimeStatusDescription }}</span>
        </div>
      </div>
      <section class="conversation-panel">
        <n-empty
          v-if="runtimeStore.transcript.length === 0 && !hasActiveStreams"
          class="collaboration-empty"
          :description="t('collaboration.noMessages')"
          size="small"
        />
        <n-scrollbar ref="scrollbarRef" class="messages-scrollbar">
          <div class="message-list">
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

            <MessageItem
              v-for="message in thinkingMessages"
              :key="message.id"
              :message="message"
              thinking
              :workspace-context="messageWorkspaceContext"
            />
          </div>
        </n-scrollbar>
      </section>

      <section
        v-if="collaborationStatistics && store.activeSession?.status === 'completed'"
        class="collaboration-statistics"
        aria-label="collaboration statistics"
      >
        <div class="statistic-item">
          <span>{{ t('collaboration.stats.totalTokens') }}</span>
          <strong>{{ formatCount(collaborationStatistics.model_usage.totals.total_tokens) }}</strong>
        </div>
        <div class="statistic-item">
          <span>{{ t('collaboration.stats.cacheHit') }}</span>
          <strong>{{ formatPercent(collaborationStatistics.model_usage.totals.cache_hit_ratio) }}</strong>
        </div>
        <div class="statistic-item">
          <span>{{ t('collaboration.stats.wallDuration') }}</span>
          <strong>{{ formatDuration(collaborationStatistics.wall_duration_ms) }}</strong>
        </div>
        <div class="statistic-item">
          <span>{{ t('collaboration.stats.taskDuration') }}</span>
          <strong>{{ formatDuration(collaborationStatistics.cumulative_task_duration_ms) }}</strong>
        </div>
        <div class="statistic-item">
          <span>{{ t('collaboration.stats.tasks') }}</span>
          <strong>{{ collaborationStatistics.task_count }}</strong>
        </div>
      </section>

      <ToolApprovalPanel
        v-if="hasApprovalRequests"
        class="approval-section"
      />
      <PublishConfirmationPanel
        v-if="runtimeStore.isPublishConfirmationPending"
        class="approval-section"
      />

      <footer class="composer">
        <MessageInput
          ref="inputRef"
          :placeholder="t('collaboration.inputPlaceholder')"
          :disabled="inputDisabled"
          :is-running="isMainAgentRunning"
          attachments-enabled
          model-selector-enabled
          :model-options="modelOptions"
          :selected-model-profile-id="selectedModelProfileId"
          :reasoning-control-enabled="reasoningControlEnabled"
          :reasoning-intensity="reasoningIntensity"
          :reference-scope="referenceScope"
          @update:selected-model-profile-id="updateModelProfile"
          @update:reasoning-intensity="updateReasoningIntensity"
          @send="sendMessage"
          @cancel="cancelRequest"
        />
      </footer>
    </div>
    <TipPanel v-if="tipScopeId" scope-type="collaboration" :scope-id="tipScopeId" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  NEmpty,
  NScrollbar,
} from 'naive-ui'
import { useCollaborationStore } from '@/stores/collaboration'
import { useModelPoolStore } from '@/stores/modelPool'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import { useCollaborationRuntime } from '@/composables/collaboration/useCollaborationRuntime'
import MessageInput from '@/components/chat/MessageInput.vue'
import MessageItem from '@/components/chat/MessageItem.vue'
import PublishConfirmationPanel from '@/components/chat/PublishConfirmationPanel.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import type { CollaborationRuntimeStatus } from '@/api/collaboration'
import type { RuntimeAttachmentInput, TranscriptItem } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { messageContextReference } from '@/utils/contextReferences'
import TipPanel from '@/components/chat/TipPanel.vue'
import type { TipMessageContext } from '@/stores/tips'

const store = useCollaborationStore()
const runtimeStore = useRuntimeStore()
const modelPoolStore = useModelPoolStore()
const uiStore = useUiStore()
const { t } = useI18n()
const scrollbarRef = ref()
const inputRef = ref()
const referenceStore = useContextReferenceStore()
const referenceScope = computed(() => `collaboration:${store.activeSession?.collaboration_id || 'new'}`)
const messageWorkspaceContext = computed(() => ({
  resourceMode: 'collaboration' as const,
  collaborationId: store.activeSession?.collaboration_id || null,
}))
const selectedModelProfileId = computed(() => store.activeSession?.execution_config?.model_profile_id || '')
const reasoningIntensity = computed(() => store.activeSession?.execution_config?.reasoning_intensity ?? null)
const selectedModelProfile = computed(() => (
  modelPoolStore.profile(selectedModelProfileId.value)
))
const reasoningControlEnabled = computed(() => (
  selectedModelProfile.value?.capabilities.reasoning_supported !== false
))
const modelOptions = computed(() => [
  { label: t('chat.defaultMainModel'), value: '' },
  ...modelPoolStore.profiles
    .filter(profile => profile.kind === 'chat' && profile.enabled && profile.credential?.enabled !== false)
    .map(profile => ({
      label: profile.display_name || profile.model_name || profile.profile_id,
      value: profile.profile_id,
    })),
])
const tipScopeId = computed(() => store.activeSession?.collaboration_id || '')
const collaborationStatistics = computed(() => store.activeSession?.statistics || null)
const {
  activeStreamContentKey,
  cancelMainAgentRequest,
  enterActiveMainAgentContext,
  hasActiveStreams,
  hasApprovalRequests,
  inputDisabled,
  isMainAgentRunning,
  isMessageStreaming,
  sendMainAgentMessage,
  thinkingMessages,
  timelineItems,
} = useCollaborationRuntime()
const runtimeStatus = computed<CollaborationRuntimeStatus | null>(() => {
  if (runtimeStore.runStatus === 'interrupted' && hasApprovalRequests.value) {
    return 'waiting_for_approval'
  }
  const sessionStatus = store.activeSession?.runtime_status || null
  if (isMainAgentRunning.value) {
    return sessionStatus === 'resuming_from_event' ? sessionStatus : null
  }
  if (runtimeStore.runStatus === 'waiting_for_workers') {
    return 'waiting_for_workers'
  }
  return sessionStatus
})
const runtimeStatusTitle = computed(() => (
  runtimeStatus.value ? t(`collaboration.runtimeStatus.${runtimeStatus.value}`) : ''
))
const runtimeStatusDescription = computed(() => (
  runtimeStatus.value ? t(`collaboration.runtimeStatus.${runtimeStatus.value}.description`) : ''
))

onMounted(() => {
  uiStore.openRightSidebar('status')
  void store.bootstrap().then(() => {
    enterActiveMainAgentContext()
    nextTick(() => inputRef.value?.focus())
  })
  void modelPoolStore.ensureLoaded()
})

function updateModelProfile(value: string) {
  const nextProfile = modelPoolStore.profile(value)
  void store.updateSession({
    execution_config: {
      ...(store.activeSession?.execution_config || {}),
      model_profile_id: value || null,
      ...(nextProfile?.capabilities.reasoning_supported === false ? { reasoning_intensity: null } : {}),
    },
  })
}

function updateReasoningIntensity(value: number | null) {
  void store.updateSession({
    execution_config: {
      ...(store.activeSession?.execution_config || {}),
      reasoning_intensity: value,
    },
  })
}

async function sendMessage(message: string, attachments: RuntimeAttachmentInput[]) {
  if (!await sendMainAgentMessage(message, attachments)) return
  if (store.activeSession?.status === 'draft') {
    await store.updateSession({ status: 'running' })
  }
  scrollToBottom('smooth')
}

function cancelRequest() {
  cancelMainAgentRequest()
}

function addMessageReference(message: TranscriptItem) {
  referenceStore.add(messageContextReference(message), referenceScope.value)
  nextTick(() => inputRef.value?.focus())
}

function tipContextFor(message: TranscriptItem): Omit<TipMessageContext, 'sourceMessageId' | 'sourceRole' | 'sourceContent'> | null {
  if (!tipScopeId.value || message.role !== 'assistant') return null
  return {
    scopeType: 'collaboration',
    scopeId: tipScopeId.value,
    agentPackageId: String(message.metadata?.package_id || store.mainAgentId || 'factory_chat'),
  }
}

function scrollToBottom(behavior: ScrollBehavior = 'auto') {
  nextTick(() => {
    scrollbarRef.value?.scrollTo({ position: 'bottom', behavior })
  })
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

function formatCount(value: number): string {
  return new Intl.NumberFormat().format(Number(value || 0))
}

function formatPercent(value: number | null): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}

function formatDuration(value: number | null): string {
  if (value == null) return '—'
  const totalSeconds = Math.max(0, Math.round(value / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

watch(
  () => runtimeStore.transcript.length,
  followBottomIfNeeded,
)

watch(
  () => runtimeStore.tools.map((tool) => `${tool.activityKey}:${tool.status}:${tool.timestamp}`).join('|'),
  followBottomIfNeeded,
)

watch(
  () => activeStreamContentKey.value,
  followBottomIfNeeded,
)

</script>

<style scoped>
.collaboration-view {
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

.runtime-status-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 16px 0;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--app-primary) 24%, var(--app-border));
  border-radius: 10px;
  background: color-mix(in srgb, var(--app-primary) 7%, var(--app-surface));
}

.collaboration-statistics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--app-space-sm);
  margin: var(--app-space-sm) var(--app-space-md);
  padding: var(--app-space-sm) var(--app-space-md);
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.statistic-item {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.statistic-item span {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

.statistic-item strong {
  color: var(--app-text-strong);
  font-size: var(--app-font-sm);
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .collaboration-statistics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.runtime-status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--app-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-primary) 14%, transparent);
  animation: runtime-status-pulse 1.8s ease-in-out infinite;
}

.runtime-status-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.runtime-status-copy strong {
  color: var(--app-text);
  font-size: 13px;
  font-weight: 600;
}

.runtime-status-copy span {
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

@keyframes runtime-status-pulse {
  0%, 100% { opacity: 0.55; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1); }
}

.conversation-panel {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.messages-scrollbar {
  height: 100%;
}

.messages-scrollbar :deep(.n-scrollbar-content) {
  height: 100%;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  min-height: 100%;
  padding: 0 0 var(--app-space-lg);
}

.collaboration-empty {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  pointer-events: none;
}

.composer {
  flex-shrink: 0;
  padding-top: var(--app-space-md);
  background: var(--app-surface);
}

.approval-section {
  flex-shrink: 0;
  margin-bottom: var(--app-space-sm);
}
</style>
