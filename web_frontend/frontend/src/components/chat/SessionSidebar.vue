<template>
  <div class="session-panel">
    <div class="sidebar-header">
      <n-text strong>{{ panelTitle }}</n-text>
      <n-button size="small" :disabled="runtimeStore.hasActiveRun" @click="handleNewSession">
        <template #icon>
          <n-icon><Add /></n-icon>
        </template>
        {{ t('sessions.new') }}
      </n-button>
    </div>

    <div class="sidebar-search">
      <n-input
        v-model:value="searchQuery"
        :placeholder="t('common.searchSessions')"
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
            <div class="session-title-row">
              <div class="session-title">
                {{ sessionTitle(session) }}
              </div>
              <n-button
                size="tiny"
                quaternary
                circle
                :aria-label="t('sessions.delete')"
                @click.stop="confirmDeleteSession(session)"
              >
                <template #icon>
                  <n-icon><TrashOutline /></n-icon>
                </template>
              </n-button>
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
                {{ t('sessions.turns', { count: sessionTurnCount(session) }) }}
              </n-text>
            </div>
          </div>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="filteredSessions.length === 0"
        :description="t('sessions.empty')"
        size="small"
        class="sessions-empty"
      />
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon, NText, NInput, NScrollbar, NList, NListItem, NTag, NEmpty, useDialog } from 'naive-ui'
import { Add, ChatbubbleEllipses, Search, TrashOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useSessionStore } from '@/stores/session'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import { useConversationSessionNavigation } from '@/composables/useConversationSessionNavigation'
import type { SessionView } from '@/stores/session'

const props = withDefaults(
  defineProps<{
    title?: string
  }>(),
  {
    title: '',
  }
)

const sessionStore = useSessionStore()
const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const commands = useCommand()
const { startNewConversationSession } = useConversationSessionNavigation()
const { locale, t } = useI18n()
const searchQuery = ref('')
const dialog = useDialog()

const panelTitle = computed(() => props.title || t('sessions.main'))

const activeSessionMode = computed<'chat' | 'create_agent' | 'evolve_agent'>(() => {
  if (runtimeStore.currentMode === 'create_agent') return 'create_agent'
  if (runtimeStore.currentMode === 'evolve_agent') return 'evolve_agent'
  return 'chat'
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
  void startNewConversationSession()
}

function handleSelectSession(session: SessionView) {
  commands.switchSession(session.session_id, activeSessionMode.value)
}

function confirmDeleteSession(session: SessionView) {
  dialog.warning({
    title: t('sessions.deleteTitle'),
    content: t('sessions.deleteContent', { title: sessionTitle(session) }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      commands.deleteSession(session.session_id, activeSessionMode.value)
    },
  })
}

function sessionBelongsToActiveMode(session: SessionView): boolean {
  if (activeSessionMode.value === 'evolve_agent') {
    const packageId = agentStore.selectedPackageId
    if (packageId && session.evolve_agent_package_id !== packageId) return false
  }
  if (session.session_id === sessionStore.currentSessionId && runtimeStore.currentMode === activeSessionMode.value) {
    return true
  }
  if (session.current_mode === activeSessionMode.value) return true
  if (sessionTurnCount(session) > 0) return true
  if (activeSessionMode.value === 'chat') return Boolean(session.chat_agent_package_session_id)
  if (activeSessionMode.value === 'create_agent') return Boolean(session.create_agent_session_id)
  return Boolean(session.evolve_agent_package_id)
}

function sessionTurnCount(session: SessionView): number {
  const modeCounts = session.mode_turn_counts || {}
  const count = modeCounts[activeSessionMode.value]
  if (typeof count === 'number') return count
  if (activeSessionMode.value === 'create_agent') return session.create_agent_turn_count
  if (activeSessionMode.value === 'evolve_agent') return session.evolve_agent_turn_count || 0
  return session.chat_turn_count
}

function sessionTitle(session: SessionView): string {
  const modeTitle = session.mode_titles?.[activeSessionMode.value]
  return modeTitle || session.display_title || session.first_user_input || t('sessions.newSession')
}

function modeLabel(mode: string): string {
  const labels: Record<string, string> = {
    chat: t('sessions.modeChat'),
    create_agent: t('sessions.modeCreate'),
    evolve_agent: t('sessions.modeEvolve'),
    agent_package: t('sessions.modeAgent'),
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
    return new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }).format(-minutes, 'minute')
  }

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
  }

  return date.toLocaleDateString(locale.value, { month: '2-digit', day: '2-digit' })
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
  background: var(--app-surface);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.sidebar-search {
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.session-list {
  flex: 1;
  min-height: 0;
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  padding: var(--app-space-xs) 0;
  width: 100%;
  min-width: 0;
}

.session-title-row {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-xs);
}

.session-panel :deep(.n-list-item) {
  transition: background-color var(--app-transition-fast);
  border-radius: var(--app-radius-md);
  animation: app-fade-in 0.2s ease both;
}

.session-panel :deep(.n-list-item__main) {
  min-width: 0;
  width: 100%;
}

.session-panel :deep(.n-list-item.active) {
  background: var(--app-surface-pressed);
  position: relative;
}

.session-panel :deep(.n-list-item.active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: var(--app-radius-pill);
  background: var(--app-text);
}

.session-title {
  font-size: var(--app-font-lg);
  font-weight: 500;
  color: var(--app-text);
  flex: 1;
  min-width: 0;
  line-height: 1.35;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
}

.session-title-row :deep(.n-button) {
  flex: 0 0 auto;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
}

.session-stats {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
}

.session-stats :deep(.n-text) {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
}

.sessions-empty {
  margin-top: var(--app-space-xxl);
  animation: app-fade-in 0.24s ease both;
}
</style>
