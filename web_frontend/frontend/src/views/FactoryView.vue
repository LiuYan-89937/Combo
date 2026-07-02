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

            <template
              v-for="message in runtimeStore.transcript"
              :key="message.id"
            >
              <MessageItem
                :message="message"
                :streaming="isMessageStreaming(message.streamId)"
              />
              <ToolActivityCard
                v-for="tool in toolsAfterMessage(message)"
                :key="`${message.id}-${tool.activityKey}`"
                :tool="tool"
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

      <!-- 输入区 -->
      <div class="input-section">
        <MessageInput
          ref="inputRef"
          :placeholder="inputPlaceholder"
          :disabled="inputDisabled"
          :is-running="runtimeStore.hasActiveRun"
          attachments-enabled
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
import type { RuntimeAttachmentInput, ToolActivity, TranscriptItem } from '@/types/protocol'

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
  untrackedActiveStreamMessages,
} = useFactoryMessageProjection()

function toolsAfterMessage(message: TranscriptItem): ToolActivity[] {
  if (message.role !== 'user') return []
  const turn = runtimeStore.conversationTurns.find((item) => item.userMessage?.id === message.id)
  return turn?.tools || []
}

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

.approval-section {
  margin-top: 12px;
}

.input-section {
  margin-top: 16px;
}
</style>
