<template>
  <div class="tool-trace-message" :class="{ embedded }">
    <div v-if="!embedded" class="assistant-avatar" aria-hidden="true">
      <ComboFrameAnimation character="companion" action="idle" :size="34" paused />
    </div>
    <div class="trace-content">
      <div v-if="!embedded" class="trace-header">
        <strong>Combo</strong>
        <span>{{ formattedTime }}</span>
      </div>
      <!--
        工具调用是 AI 回合里的活动节点，不是聊天气泡。这里只渲染活动流本身：
        折叠交给消息层的「工作区」（回合结束后折成一行摘要），再套一层 caption
        只会让同一段工作同时有两个折叠入口。
      -->
      <ToolExecutionChain
        :executions="executions"
        :bounded="bounded"
        :workspace-context="workspaceContext"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolExecutionChain from '@/components/chat/ToolExecutionChain.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import { useI18n } from '@/composables/useI18n'
import type { ToolExecutionMessagePart } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'

const props = withDefaults(defineProps<{
  executions: ToolExecutionMessagePart[]
  timestamp?: string
  workspaceContext?: WorkspaceRequestContext | null
  embedded?: boolean
  bounded?: boolean
}>(), {
  timestamp: '',
  workspaceContext: null,
  embedded: false,
  bounded: true,
})

const { locale } = useI18n()
const formattedTime = computed(() => new Date(props.timestamp || Date.now()).toLocaleTimeString(locale.value, {
  hour: '2-digit',
  minute: '2-digit',
}))
</script>

<style scoped>
.tool-trace-message {
  display: flex;
  gap: var(--app-space-md);
  padding: 8px var(--app-space-md);
}

.tool-trace-message.embedded {
  padding: 0;
}

.assistant-avatar {
  display: grid;
  width: 40px;
  height: 36px;
  flex: 0 0 40px;
  place-items: center;
}

.trace-content {
  min-width: 0;
  flex: 1;
}

.trace-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 5px;
  font-size: 13px;
}

.trace-header strong {
  font-family: 'Avenir Next', 'SF Pro Display', 'Arial Rounded MT Bold', sans-serif;
  font-size: 16px;
  font-weight: 780;
  letter-spacing: -.055em;
}

.trace-header span {
  color: var(--app-text-muted);
  font-size: 11px;
}
</style>
