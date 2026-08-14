<template>
  <div class="agent-session-panel">
    <div class="panel-header">
      <div class="header-title">
        <n-text strong>{{ t('agentSessions.title') }}</n-text>
        <n-text depth="3" class="package-name">
          {{ packageTitle }}
        </n-text>
      </div>
      <div class="header-actions">
        <n-button size="small" type="primary" @click="requestNewSession">
          {{ t('agentSessions.newChat') }}
        </n-button>
        <n-button size="small" @click="refreshSessions">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
        </n-button>
      </div>
    </div>

    <div class="panel-search">
      <n-input
        v-model:value="searchQuery"
        :placeholder="t('agentSessions.searchPlaceholder')"
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
      :empty-description="t('agentSessions.empty')"
      show-agent-tag
      @select="enterExistingSession"
      @delete="confirmDeleteSession"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NIcon, NInput, NText, useDialog } from 'naive-ui'
import { Refresh, Search } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import SessionHistoryList, { type SessionHistoryItem } from '@/components/chat/SessionHistoryList.vue'
import type { AgentSessionView } from '@/stores/agent'

const props = defineProps<{
  packageId: string
}>()
const emit = defineEmits<{
  requestNewSession: [packageId: string, initialWorkspaceId: string | null]
  interactionLock: [locked: boolean]
}>()

const agentStore = useAgentStore()
const commands = useCommand()
const { openAgentSession } = useAgentSessionNavigation()
const { t } = useI18n()
const searchQuery = ref('')
const dialog = useDialog()

const currentPackage = computed(() => {
  return agentStore.agentPackages.find((pkg) => pkg.package_id === props.packageId) || null
})

const packageTitle = computed(() => {
  const pkg = currentPackage.value
  return pkg?.agent_name || pkg?.name || t('common.unnamedAgent')
})

const sessions = computed(() => agentStore.agentSessions.filter((session) => (
  session.package_id === props.packageId
)))

function refreshSessions() {
  commands.listAgentPackageSessions(props.packageId)
}

function requestNewSession() {
  emit('requestNewSession', props.packageId, null)
}

function enterExistingSession(session: SessionHistoryItem) {
  void openAgentSession(session as AgentSessionView)
}

function confirmDeleteSession(session: SessionHistoryItem) {
  const title = session.display_title || session.first_user_input || t('sessions.newSession')
  emit('interactionLock', true)
  dialog.warning({
    title: t('agentSessions.deleteTitle'),
    content: t('agentSessions.deleteContent', { title }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => commands.deleteAgentPackageSession(props.packageId, session.session_id),
    onAfterLeave: () => emit('interactionLock', false),
  })
}

onMounted(() => {
  refreshSessions()
})

watch(
  () => props.packageId,
  () => {
    refreshSessions()
  }
)
</script>

<style scoped>
.agent-session-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.header-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xxs);
}

.package-name {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  flex-shrink: 0;
}

.panel-search {
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}
</style>
