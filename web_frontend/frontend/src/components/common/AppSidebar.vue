<template>
  <aside class="app-sidebar" :style="{ width: `${uiStore.leftSidebarWidth}px` }">
    <n-menu
      class="main-menu"
      :value="activeKey"
      :options="menuOptions"
      @update:value="handleMenuSelect"
    />

    <section class="recent-agent-section">
      <div class="recent-agent-header">
        <button
          class="recent-agent-main"
          type="button"
          :disabled="!mostRecentAgentSession"
          @click="openMostRecentAgentSession"
        >
          <span class="recent-agent-kicker">最近使用</span>
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
          暂无最近 Agent 会话
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NMenu, NIcon } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import {
  ChatbubbleEllipses,
  Build,
  GitCompare,
  Rocket,
  FolderOpen,
  Library,
  Time,
  ExtensionPuzzle,
  CaretDown,
  CaretUp,
} from '@vicons/ionicons5'
import { useUiStore } from '@/stores/ui'
import { useAgentStore, type AgentRecentSessionView } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import { formatTime } from '@/utils/format'

const router = useRouter()
const route = useRoute()
const uiStore = useUiStore()
const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const recentAgentExpanded = ref(false)

const activeKey = computed(() => route.path)
const recentAgentSessions = computed(() => agentStore.recentAgentSessions)
const mostRecentAgentSession = computed(() => recentAgentSessions.value[0] || null)
const mostRecentAgentLabel = computed(() => (
  mostRecentAgentSession.value
    ? agentSessionPackageLabel(mostRecentAgentSession.value)
    : '暂无 Agent 会话'
))

const menuOptions = computed<MenuOption[]>(() => [
  {
    label: '闲聊',
    key: '/factory',
    icon: renderIcon(ChatbubbleEllipses),
  },
  {
    label: 'Agent 制造',
    key: '/manufacturing',
    icon: renderIcon(Build),
  },
  {
    label: 'Agent 进化',
    key: '/evolution',
    icon: renderIcon(GitCompare),
  },
  {
    label: '已发布 Agent',
    key: '/agents',
    icon: renderIcon(Rocket),
  },
  {
    type: 'divider',
    key: 'd1',
  },
  {
    label: '资源管理',
    key: 'resources',
    children: [
      {
        label: '工作区',
        key: '/workspace',
        icon: renderIcon(FolderOpen),
      },
      {
        label: '知识库',
        key: '/knowledge',
        icon: renderIcon(Library),
      },
      {
        label: '定时任务',
        key: '/scheduler',
        icon: renderIcon(Time),
      },
      {
        label: '扩展管理',
        key: '/extensions',
        icon: renderIcon(ExtensionPuzzle),
      },
    ],
  },
])

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function handleMenuSelect(key: string) {
  if (key.startsWith('/')) {
    if (key === '/factory') {
      agentStore.leaveAgentChat()
      runtimeStore.enterFactoryConversation('chat')
      commands.startSession(true, 'chat')
    } else if (key === '/manufacturing') {
      agentStore.leaveAgentChat()
      runtimeStore.enterFactoryConversation('create_agent')
      commands.startSession(true, 'create_agent')
    } else if (key === '/evolution') {
      agentStore.leaveAgentChat()
      runtimeStore.enterFactoryConversation('evolve_agent', agentStore.selectedPackageId)
      commands.startSession(true, 'evolve_agent')
    }
    router.push(key)
  }
}

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
  return session.display_title || session.first_user_input || '新会话'
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
.app-sidebar {
  height: 100%;
  background-color: var(--n-color);
  border-right: 1px solid var(--n-border-color);
  transition: width 0.3s ease;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.main-menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.app-sidebar :deep(.n-menu-item-content) {
  color: #111111;
}

.app-sidebar :deep(.n-menu-item-content .n-menu-item-content__icon),
.app-sidebar :deep(.n-menu-item-content .n-menu-item-content-header) {
  color: inherit;
}

.app-sidebar :deep(.n-menu-item-content:not(.n-menu-item-content--selected):hover) {
  background-color: #f5f5f5;
}

.app-sidebar :deep(.n-menu-item-content--selected) {
  background-color: #eeeeee;
  color: #000000;
}

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
