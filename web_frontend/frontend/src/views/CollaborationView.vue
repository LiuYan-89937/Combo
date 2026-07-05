<template>
  <div class="collaboration-view">
    <div class="chat-container">
      <header class="collaboration-header">
        <div class="title-block">
          <n-tag size="small" :bordered="false" type="info">Beta</n-tag>
          <div>
            <h1>{{ store.activeSession?.title || t('collaboration.noActiveTitle') }}</h1>
            <p>{{ t('collaboration.subtitle') }}</p>
          </div>
        </div>
      </header>

      <section class="conversation-panel">
        <n-scrollbar ref="scrollbarRef" class="messages-scrollbar">
          <div class="message-list">
            <n-empty
              v-if="runtimeStore.transcript.length === 0 && !hasActiveStreams"
              :description="t('collaboration.noMessages')"
              size="small"
            />

            <template v-for="item in timelineItems" :key="`${item.kind}-${item.id}`">
              <MessageItem
                :message="item.message"
                :streaming="isMessageStreaming(item.message.streamId)"
              />
            </template>

            <MessageItem
              v-for="message in thinkingMessages"
              :key="message.id"
              :message="message"
              thinking
            />
          </div>
        </n-scrollbar>
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
          @send="sendMessage"
          @cancel="cancelRequest"
        />
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import {
  NEmpty,
  NScrollbar,
  NTag,
} from 'naive-ui'
import { useCollaborationStore } from '@/stores/collaboration'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import { useCollaborationRuntime } from '@/composables/collaboration/useCollaborationRuntime'
import MessageInput from '@/components/chat/MessageInput.vue'
import MessageItem from '@/components/chat/MessageItem.vue'
import PublishConfirmationPanel from '@/components/chat/PublishConfirmationPanel.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import type { RuntimeAttachmentInput } from '@/types/protocol'

const store = useCollaborationStore()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const { t } = useI18n()
const scrollbarRef = ref()
const inputRef = ref()
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

onMounted(() => {
  uiStore.openRightSidebar('status')
  void store.bootstrap().then(() => {
    enterActiveMainAgentContext()
    nextTick(() => inputRef.value?.focus())
  })
})

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
  flex-direction: column;
  background: var(--app-surface);
}

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: var(--app-space-xl) var(--app-space-xl) var(--app-space-lg);
  max-width: var(--app-chat-max-width);
  margin: 0 auto;
  width: 100%;
}

.collaboration-header {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
}

.title-block {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-md);
}

.title-block h1 {
  margin: 0;
  color: var(--app-text-strong);
  font-size: var(--app-font-xl);
}

.title-block p {
  margin: var(--app-space-xxs) 0 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-sm);
}

.conversation-panel {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.messages-scrollbar {
  height: 100%;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  padding: 0 0 var(--app-space-lg);
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
