<template>
  <div class="session-panel">
    <div class="sidebar-header">
      <n-text strong>{{ panelTitle }}</n-text>
      <n-button
        v-if="activeAgentPackageId"
        size="small"
        :disabled="!canStartNewConversationSession"
        @click="openNewSessionDialog"
      >
          <template #icon>
            <n-icon><Add /></n-icon>
          </template>
          {{ t('sessions.new') }}
      </n-button>
      <n-button v-else size="small" :disabled="!canStartNewConversationSession" @click="handleNewSession">
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

    <SessionHistoryList
      :sessions="sessions"
      :active-session-id="agentStore.selectedSessionId"
      :search-query="searchQuery"
      :empty-description="t('sessions.empty')"
      @select="handleSelectSession"
      @delete="confirmDeleteSession"
    />

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NIcon, NInput, NText, useDialog } from 'naive-ui'
import { Add, Search } from '@/components/icons'
import SessionHistoryList, { type SessionHistoryItem } from '@/components/chat/SessionHistoryList.vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import { useConversationSessionNavigation } from '@/composables/useConversationSessionNavigation'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import type { AgentSessionView } from '@/stores/agent'

const props = withDefaults(
  defineProps<{
    title?: string
  }>(),
  {
    title: '',
  }
)
const emit = defineEmits<{
  requestNewAgentSession: [packageId: string, initialWorkspaceId: string | null]
  interactionLock: [locked: boolean]
}>()

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const commands = useCommand()
const { canStartNewConversationSession, startNewConversationSession } = useConversationSessionNavigation()
const { openAgentSession } = useAgentSessionNavigation()
const { t } = useI18n()
const searchQuery = ref('')
const dialog = useDialog()

const panelTitle = computed(() => props.title || t('sessions.main'))

const activeAgentPackageId = computed(() => agentStore.activeChatPackageId)
const sessions = computed<AgentSessionView[]>(() => {
  return activeAgentPackageId.value
    ? agentStore.agentSessions.filter((session) => session.package_id === activeAgentPackageId.value)
    : []
})

function handleNewSession() {
  void startNewConversationSession()
}

function openNewSessionDialog() {
  const packageId = activeAgentPackageId.value
  if (!packageId) return
  emit('requestNewAgentSession', packageId, runtimeStore.activeWorkspaceId)
}

function handleSelectSession(session: SessionHistoryItem) {
  void openAgentSession(session as AgentSessionView)
}

function confirmDeleteSession(session: SessionHistoryItem) {
  const packageId = session.package_id || activeAgentPackageId.value
  if (!packageId) return
  emit('interactionLock', true)
  dialog.warning({
    title: t('sessions.deleteTitle'),
    content: t('sessions.deleteContent', { title: sessionTitle(session) }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => commands.deleteAgentPackageSession(packageId, session.session_id),
    onAfterLeave: () => emit('interactionLock', false),
  })
}

function sessionTitle(session: SessionHistoryItem): string {
  return session.display_title || session.first_user_input || t('sessions.newSession')
}

onMounted(() => {
  refreshSessions()
})

watch(activeAgentPackageId, refreshSessions)

function refreshSessions() {
  const packageId = activeAgentPackageId.value
  if (packageId) {
    void commands.listAgentPackageSessions(packageId)
    return
  }
}

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
</style>
