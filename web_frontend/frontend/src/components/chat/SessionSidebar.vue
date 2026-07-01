<template>
  <div class="session-panel">
    <div class="sidebar-header">
      <n-text strong>{{ title }}</n-text>
      <n-button size="small" @click="handleNewSession">
        <template #icon>
          <n-icon><Add /></n-icon>
        </template>
        新建
      </n-button>
    </div>

    <div class="sidebar-search">
      <n-input
        v-model:value="searchQuery"
        placeholder="搜索会话..."
        clearable
      >
        <template #prefix>
          <n-icon><Search /></n-icon>
        </template>
      </n-input>
    </div>

    <n-scrollbar class="session-list">
      <n-list hoverable clickable>
        <n-list-item
          v-for="session in filteredSessions"
          :key="session.session_id"
          :class="{ active: session.session_id === sessionStore.currentSessionId }"
          @click="handleSelectSession(session)"
        >
          <div class="session-item">
            <div class="session-title">
              {{ sessionTitle(session) }}
            </div>
            <div class="session-meta">
              <n-tag size="tiny" :type="modeTagType(activeSessionMode)">
                {{ modeLabel(activeSessionMode) }}
              </n-tag>
              <n-text depth="3" style="font-size: 11px">
                {{ formatTime(session.updated_at) }}
              </n-text>
            </div>
            <div class="session-stats">
              <n-text depth="3" style="font-size: 11px">
                <n-icon size="12">
                  <ChatbubbleEllipses />
                </n-icon>
                {{ sessionTurnCount(session) }} 轮
              </n-text>
            </div>
          </div>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="filteredSessions.length === 0"
        description="没有会话"
        size="small"
        style="margin-top: 40px"
      />
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NButton, NIcon, NText, NInput, NScrollbar, NList, NListItem, NTag, NEmpty } from 'naive-ui'
import { Add, ChatbubbleEllipses, Search } from '@vicons/ionicons5'
import { useSessionStore } from '@/stores/session'
import { useRuntimeStore } from '@/stores/runtime'
import { useCommand } from '@/composables/useCommand'
import type { SessionView } from '@/stores/session'

withDefaults(
  defineProps<{
    title?: string
  }>(),
  {
    title: '主会话',
  }
)

const sessionStore = useSessionStore()
const runtimeStore = useRuntimeStore()
const commands = useCommand()
const searchQuery = ref('')

const activeSessionMode = computed<'chat' | 'create_agent'>(() => {
  return runtimeStore.currentMode === 'create_agent' ? 'create_agent' : 'chat'
})

const filteredSessions = computed(() => {
  const query = searchQuery.value.toLowerCase()
  return sessionStore.sessions.filter((session) => {
    if (!sessionBelongsToActiveMode(session)) return false
    if (!query) return true
    return (
      sessionTitle(session).toLowerCase().includes(query) ||
      Boolean(session.first_user_input?.toLowerCase().includes(query))
    )
  })
})

function handleNewSession() {
  commands.newSession(activeSessionMode.value)
}

function handleSelectSession(session: SessionView) {
  commands.switchSession(session.session_id, activeSessionMode.value)
}

function sessionBelongsToActiveMode(session: SessionView): boolean {
  if (session.session_id === sessionStore.currentSessionId && runtimeStore.currentMode === activeSessionMode.value) {
    return true
  }
  if (session.current_mode === activeSessionMode.value) return true
  if (sessionTurnCount(session) > 0) return true
  if (activeSessionMode.value === 'chat') return Boolean(session.chat_agent_package_session_id)
  return Boolean(session.create_agent_session_id)
}

function sessionTurnCount(session: SessionView): number {
  const modeCounts = session.mode_turn_counts || {}
  const count = modeCounts[activeSessionMode.value]
  if (typeof count === 'number') return count
  return activeSessionMode.value === 'create_agent'
    ? session.create_agent_turn_count
    : session.chat_turn_count
}

function sessionTitle(session: SessionView): string {
  const modeTitle = session.mode_titles?.[activeSessionMode.value]
  return modeTitle || session.display_title || session.first_user_input || '新会话'
}

function modeLabel(mode: string): string {
  const labels: Record<string, string> = {
    chat: '对话',
    create_agent: '创建',
    evolve_agent: '进化',
    agent_package: 'Agent',
  }
  return labels[mode] || mode
}

function modeTagType(mode: string): 'default' | 'success' | 'info' | 'warning' {
  const types: Record<string, any> = {
    chat: 'default',
    create_agent: 'info',
    evolve_agent: 'warning',
    agent_package: 'success',
  }
  return types[mode] || 'default'
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return `${minutes}分钟前`
  }

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }

  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

onMounted(() => {
  commands.listSessions()
})
</script>

<style scoped>
.session-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--n-color);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.sidebar-search {
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.session-list {
  flex: 1;
  min-height: 0;
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.session-panel :deep(.n-list-item.active) {
  background: var(--n-color-pressed);
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-stats {
  display: flex;
  align-items: center;
  gap: 12px;
}

.session-stats :deep(.n-text) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
