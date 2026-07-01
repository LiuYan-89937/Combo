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
import { ref, onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { NScrollbar, NEmpty, NIcon, NText, NSelect } from 'naive-ui'
import { ChatbubbleEllipses } from '@vicons/ionicons5'
import { useRuntimeStore } from '@/stores/runtime'
import { useFactoryConversation } from '@/composables/factory/useFactoryConversation'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'

const runtimeStore = useRuntimeStore()
const route = useRoute()
const scrollbarRef = ref()
const inputRef = ref()

const {
  isAgentChatActive,
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
  toolActivityHint,
  untrackedActiveStreamMessages,
} = useFactoryMessageProjection()

function handleSend(message: string, attachments: any[]) {
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
