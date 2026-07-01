<template>
  <section class="recent-agent-section">
    <div class="recent-agent-header">
      <button
        class="recent-agent-main"
        type="button"
        :disabled="!mostRecentAgentSession"
        @click="openMostRecentAgentSession"
      >
        <span class="recent-agent-kicker">{{ t('sidebar.recent') }}</span>
        <span class="recent-agent-title">
          {{ mostRecentAgentLabel }}
        </span>
      </button>
      <button
        class="recent-agent-toggle"
        type="button"
        :disabled="recentAgentSessions.length === 0"
        :aria-expanded="recentAgentExpanded"
        @click="recentAgentExpanded = !recentAgentExpanded"
      >
        <n-icon size="14">
          <component :is="recentAgentExpanded ? CaretUp : CaretDown" />
        </n-icon>
      </button>
    </div>

    <div v-if="recentAgentExpanded" class="recent-agent-list">
      <button
        v-for="session in recentAgentSessions"
        :key="`${session.package_id}:${session.session_id}`"
        class="recent-agent-item"
        :class="{ active: isActiveRecentSession(session) }"
        type="button"
        @click="openRecentAgentSession(session)"
      >
        <span class="recent-agent-item-name">{{ agentSessionPackageLabel(session) }}</span>
        <span class="recent-agent-item-title">{{ agentSessionTitle(session) }}</span>
        <span class="recent-agent-item-time">{{ formatTime(session.updated_at || session.created_at) }}</span>
      </button>

      <div v-if="recentAgentSessions.length === 0" class="recent-agent-empty">
        {{ t('sidebar.noRecentAgentSessions') }}
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { CaretDown, CaretUp } from '@vicons/ionicons5'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore, type AgentRecentSessionView } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { formatTime } from '@/utils/format'

const router = useRouter()
const uiStore = useUiStore()
const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const { t } = useI18n()
const recentAgentExpanded = ref(false)

const recentAgentSessions = computed(() => agentStore.recentAgentSessions)
const mostRecentAgentSession = computed(() => recentAgentSessions.value[0] || null)
const mostRecentAgentLabel = computed(() => (
  mostRecentAgentSession.value
    ? agentSessionPackageLabel(mostRecentAgentSession.value)
    : t('sidebar.noRecentAgent')
))

function openMostRecentAgentSession() {
  if (!mostRecentAgentSession.value) return
  openRecentAgentSession(mostRecentAgentSession.value)
}

function openRecentAgentSession(session: AgentRecentSessionView) {
  agentStore.enterAgentChat(session.package_id, session.session_id)
  workspaceStore.setScope('workdir')
  uiStore.openRightSidebar('workspace')
  void router.push({ name: 'Factory' })
  void commands.selectAgentPackage(session.package_id, 'run').then(() => {
    void commands.loadAgentPackageSession(session.package_id, session.session_id)
  })
}

function isActiveRecentSession(session: AgentRecentSessionView): boolean {
  return (
    agentStore.activeChatPackageId === session.package_id &&
    agentStore.selectedSessionId === session.session_id
  )
}

function agentSessionPackageLabel(session: AgentRecentSessionView): string {
  const packageInfo = agentStore.agentPackages.find((pkg) => pkg.package_id === session.package_id)
  return (
    session.agent_name ||
    session.package_name ||
    packageInfo?.agent_name ||
    packageInfo?.name ||
    session.package_id
  )
}

function agentSessionTitle(session: AgentRecentSessionView): string {
  return session.display_title || session.first_user_input || t('sessions.newSession')
}

function refreshRecentAgentSessions() {
  void commands.listRecentAgentSessions(5)
}

onMounted(() => {
  refreshRecentAgentSessions()
})

watch(
  () => `${runtimeStore.currentMode}:${runtimeStore.runStatus}:${runtimeStore.activeAgentSessionId || ''}`,
  () => {
    if (runtimeStore.currentMode === 'agent_package' && runtimeStore.runStatus === 'completed') {
      refreshRecentAgentSessions()
    }
  }
)
</script>

<style scoped>
.recent-agent-section {
  flex-shrink: 0;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--n-border-color);
  background: var(--n-color);
}

.recent-agent-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 32px;
  gap: 6px;
  align-items: stretch;
}

.recent-agent-main,
.recent-agent-toggle,
.recent-agent-item {
  border: 1px solid var(--n-border-color);
  background: var(--n-color);
  color: var(--n-text-color-1);
  cursor: pointer;
}

.recent-agent-main:disabled,
.recent-agent-toggle:disabled {
  color: var(--n-text-color-disabled);
  cursor: default;
}

.recent-agent-main:not(:disabled):hover,
.recent-agent-toggle:not(:disabled):hover,
.recent-agent-item:hover {
  background: #f5f5f5;
}

.recent-agent-main {
  min-width: 0;
  height: 52px;
  padding: 7px 9px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  text-align: left;
}

.recent-agent-toggle {
  width: 32px;
  min-width: 32px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.recent-agent-kicker {
  font-size: 11px;
  line-height: 1.2;
  color: var(--n-text-color-3);
}

.recent-agent-title {
  width: 100%;
  margin-top: 3px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-agent-list {
  max-height: min(360px, 42vh);
  overflow-y: auto;
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.recent-agent-item {
  width: 100%;
  min-height: 58px;
  border-radius: 6px;
  padding: 7px 9px;
  display: grid;
  grid-template-rows: auto auto auto;
  gap: 2px;
  text-align: left;
}

.recent-agent-item.active {
  background: #eeeeee;
  border-color: #d0d0d0;
}

.recent-agent-item-name,
.recent-agent-item-title,
.recent-agent-item-time {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-agent-item-name {
  font-size: 12px;
  font-weight: 600;
}

.recent-agent-item-title {
  font-size: 12px;
  color: var(--n-text-color-2);
}

.recent-agent-item-time,
.recent-agent-empty {
  font-size: 11px;
  color: var(--n-text-color-3);
}

.recent-agent-empty {
  padding: 8px 2px 0;
}
</style>
