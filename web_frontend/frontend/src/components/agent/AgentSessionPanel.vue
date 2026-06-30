<template>
  <div class="agent-session-panel">
    <div class="panel-header">
      <div class="header-title">
        <n-text strong>子 Agent 会话</n-text>
        <n-text depth="3" class="package-name">
          {{ packageTitle }}
        </n-text>
      </div>
      <div class="header-actions">
        <n-button size="small" type="primary" @click="enterNewSession">
          新对话
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
        placeholder="搜索子 Agent 会话..."
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
          :class="{ active: session.session_id === agentStore.selectedSessionId }"
          @click="enterExistingSession(session.session_id)"
        >
          <div class="session-item">
            <div class="session-title">
              {{ session.display_title || session.first_user_input || '新会话' }}
            </div>
            <div class="session-meta">
              <n-tag size="tiny" type="success">
                子 Agent
              </n-tag>
              <n-text depth="3" class="meta-text">
                {{ formatTime(session.updated_at) }}
              </n-text>
            </div>
            <div class="session-stats">
              <n-text depth="3" class="meta-text">
                <n-icon size="12">
                  <ChatbubbleEllipses />
                </n-icon>
                {{ session.turn_count }} 轮
              </n-text>
            </div>
          </div>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="filteredSessions.length === 0"
        description="没有子 Agent 会话"
        size="small"
        style="margin-top: 40px"
      />
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NEmpty, NIcon, NInput, NList, NListItem, NScrollbar, NTag, NText } from 'naive-ui'
import { ChatbubbleEllipses, Refresh, Search } from '@vicons/ionicons5'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'

const props = defineProps<{
  packageId: string
}>()

const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const router = useRouter()
const searchQuery = ref('')

const currentPackage = computed(() => {
  return agentStore.agentPackages.find((pkg) => pkg.package_id === props.packageId) || null
})

const packageTitle = computed(() => {
  const pkg = currentPackage.value
  return pkg?.agent_name || pkg?.name || '未命名 Agent'
})

const filteredSessions = computed(() => {
  if (!searchQuery.value) return agentStore.agentSessions
  const query = searchQuery.value.toLowerCase()
  return agentStore.agentSessions.filter((session) => (
    session.display_title?.toLowerCase().includes(query) ||
    session.first_user_input?.toLowerCase().includes(query)
  ))
})

function refreshSessions() {
  commands.listAgentPackageSessions(props.packageId)
}

function enterSession(sessionId: string | null) {
  if (runtimeStore.hasActiveRun) {
    uiStore.addNotification({
      type: 'warning',
      title: '当前会话正在运行',
      message: '等当前回复结束后再切换子 Agent 会话。',
      duration: 3000,
    })
    return false
  }
  agentStore.enterAgentChat(props.packageId, sessionId)
  workspaceStore.setScope('workdir')
  uiStore.openRightSidebar('workspace')
  void router.push({ name: 'Factory' })
  return true
}

function enterNewSession() {
  if (!enterSession(null)) return
  runtimeStore.showEmptyAgentPackageSession(props.packageId)
}

function enterExistingSession(sessionId: string) {
  if (!enterSession(sessionId)) return
  commands.loadAgentPackageSession(props.packageId, sessionId)
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
  refreshSessions()
})

watch(
  () => props.packageId,
  () => {
    agentStore.selectSession(null)
    refreshSessions()
  }
)
</script>

<style scoped>
.agent-session-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--n-color);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.header-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.package-name {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.panel-search {
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.session-list {
  flex: 1;
  min-height: 0;
}

.agent-session-panel :deep(.n-list-item.active) {
  background: var(--n-color-pressed);
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta,
.session-stats {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta-text {
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
