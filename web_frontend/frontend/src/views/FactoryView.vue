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
                v-if="item.kind === 'message'"
                :message="item.message"
                :streaming="isMessageStreaming(item.message.streamId)"
              />
              <ToolActivityCard
                v-else
                :tool="item.tool"
              />
            </template>

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
          @update:selected-model-profile-id="setSelectedMainModelProfileId"
          @send="handleSend"
          @cancel="handleCancel"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { NScrollbar, NEmpty, NIcon, NText, NSelect } from 'naive-ui'
import { ChatbubbleEllipses } from '@vicons/ionicons5'
import { useRuntimeStore } from '@/stores/runtime'
import { useI18n } from '@/composables/useI18n'
import { useFactoryConversation } from '@/composables/factory/useFactoryConversation'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolActivityCard from '@/components/chat/ToolActivityCard.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import PublishConfirmationPanel from '@/components/chat/PublishConfirmationPanel.vue'
import type { RuntimeAttachmentInput } from '@/types/protocol'

const runtimeStore = useRuntimeStore()
const route = useRoute()
const { t } = useI18n()
const scrollbarRef = ref()
const inputRef = ref()

const {
  isEvolutionRoute,
  selectedEvolutionPackageId,
  evolutionPackageOptions,
  inputPlaceholder,
  inputDisabled,
  loadRuntimeMainModelProfiles,
  runtimeMainModelOptions,
  selectedMainModelProfileId,
  setSelectedMainModelProfileId,
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
  untrackedActiveStreamMessages,
} = useFactoryMessageProjection()

function handleSend(message: string, attachments: RuntimeAttachmentInput[]) {
  if (!sendMessage(message, attachments)) return
  nextTick(() => {
    scrollToBottom()
  })
}

function handleCancel() {
  cancelRequest()
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

watch(
  () => runtimeStore.tools.map((tool) => `${tool.activityKey}:${tool.status}:${tool.timestamp}`).join('|'),
  () => {
    nextTick(() => {
      scrollToBottom()
    })
  }
)

// 监听流式输出，自动滚动
watch(
  () => activeStreamContentKey.value,
  () => {
    nextTick(() => {
      scrollToBottom()
    })
  }
)

onMounted(() => {
  applyRouteMode()
  void loadRuntimeMainModelProfiles()

  // 聚焦输入框
  nextTick(() => {
    inputRef.value?.focus()
  })
})

watch(() => route.name, applyRouteMode)
</script>

<style scoped>
.factory-view {
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
