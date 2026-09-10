<template>
  <n-scrollbar class="session-history">
    <div v-if="visibleEntries.length" class="history-entries">
      <template v-for="entry in visibleEntries" :key="entry.key">
        <button
          v-if="entry.kind === 'workspace'"
          class="workspace-group"
          type="button"
          :aria-expanded="entry.expanded"
          @click="toggleWorkspace(entry.workspaceId)"
        >
          <span class="workspace-folder-icon">
            <n-icon size="16"><FolderOpenOutline /></n-icon>
          </span>
          <span class="workspace-group-copy">
            <span class="workspace-group-name">{{ entry.name }}</span>
            <span class="workspace-group-meta">
              {{ t('sessions.workspaceSessionCount', { count: entry.count }) }}
            </span>
          </span>
          <n-icon class="workspace-chevron" size="14">
            <ChevronDownOutline v-if="entry.expanded" />
            <ChevronForwardOutline v-else />
          </n-icon>
        </button>

        <div
          v-else
          class="session-row"
          :class="{ active: entry.session.session_id === activeSessionId, nested: entry.nested }"
          role="button"
          tabindex="0"
          @click="emit('select', entry.session)"
          @keydown.enter.prevent="emit('select', entry.session)"
          @keydown.space.prevent="emit('select', entry.session)"
        >
          <span class="session-copy">
            <span class="session-title">{{ sessionTitle(entry.session) }}</span>
            <span class="session-meta">
              <n-tag v-if="showAgentTag" size="tiny" :bordered="false">
                {{ t('agentSessions.tag') }}
              </n-tag>
              <n-tag
                v-if="!entry.nested && entry.session.workspace"
                size="tiny"
                :bordered="false"
              >
                {{ workspaceKind(entry.session) }}
              </n-tag>
              <span>{{ formatTime(entry.session.updated_at) }}</span>
              <span class="turn-count">
                <n-icon size="12"><ChatbubbleEllipses /></n-icon>
                {{ t('sessions.turns', { count: entry.session.turn_count }) }}
              </span>
            </span>
          </span>
          <span class="session-actions" @click.stop @keydown.stop>
            <ControlHint
              v-if="canRevealSession(entry.session)"
              :label="t('workspace.revealInFileManager')"
            >
              <button
                type="button"
                :aria-label="t('workspace.revealInFileManager')"
                @click="revealSessionWorkspace(entry.session)"
              >
                <n-icon size="15"><FolderOpenOutline /></n-icon>
              </button>
            </ControlHint>
            <ControlHint :label="t('sessions.delete')">
              <button
                type="button"
                :aria-label="t('sessions.delete')"
                @click="emit('delete', entry.session)"
              >
                <n-icon size="15"><TrashOutline /></n-icon>
              </button>
            </ControlHint>
          </span>
        </div>
      </template>
    </div>

    <n-empty
      v-else
      :description="emptyDescription"
      size="small"
      class="sessions-empty"
    >
      <template #icon><ComboPngIcon name="empty-session" :size="56" /></template>
    </n-empty>
  </n-scrollbar>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NEmpty, NIcon, NScrollbar, NTag, useMessage } from 'naive-ui'
import {
  ChatbubbleEllipses,
  ChevronDownOutline,
  ChevronForwardOutline,
  FolderOpenOutline,
  TrashOutline,
} from '@/components/icons'
import ComboPngIcon from '@/components/icons/ComboPngIcon.vue'
import ControlHint from '@/components/common/ControlHint.vue'
import { useI18n } from '@/composables/useI18n'
import {
  desktopWorkspaceFileActionsAvailable,
  revealNativePath,
} from '@/api/desktopWorkspaceFiles'
import {
  groupSessionsByWorkspace,
  type WorkspaceGroupedSession,
  type SessionWorkspaceSummary,
} from '@/utils/sessionWorkspaceGrouping'

export interface SessionHistoryItem extends WorkspaceGroupedSession {
  package_id?: string
  display_title: string | null
  first_user_input: string | null
  turn_count: number
  created_at: string
  updated_at: string
  workspace?: SessionWorkspaceSummary | null
}

type VisibleEntry =
  | {
      kind: 'workspace'
      key: string
      workspaceId: string
      name: string
      count: number
      expanded: boolean
    }
  | {
      kind: 'session'
      key: string
      session: SessionHistoryItem
      nested: boolean
    }

const props = withDefaults(defineProps<{
  sessions: SessionHistoryItem[]
  activeSessionId?: string | null
  searchQuery?: string
  emptyDescription: string
  showAgentTag?: boolean
}>(), {
  activeSessionId: null,
  searchQuery: '',
  showAgentTag: false,
})

const emit = defineEmits<{
  select: [session: SessionHistoryItem]
  delete: [session: SessionHistoryItem]
}>()

const { locale, t } = useI18n()
const message = useMessage()
const expandedWorkspaceIds = ref<Set<string>>(new Set())

const filteredSessions = computed(() => {
  const query = props.searchQuery.trim().toLocaleLowerCase(locale.value)
  if (!query) return props.sessions
  return props.sessions.filter((session) => (
    sessionTitle(session).toLocaleLowerCase(locale.value).includes(query)
    || session.workspace?.title.toLocaleLowerCase(locale.value).includes(query)
    || session.workspace?.workdir_root.toLocaleLowerCase(locale.value).includes(query)
  ))
})

const groupedSessions = computed(() => groupSessionsByWorkspace(filteredSessions.value))

const visibleEntries = computed<VisibleEntry[]>(() => {
  const searching = Boolean(props.searchQuery.trim())
  return groupedSessions.value.flatMap((entry): VisibleEntry[] => {
    if (entry.kind === 'session') {
      return [{ kind: 'session', key: entry.key, session: entry.session, nested: false }]
    }

    const expanded = searching || expandedWorkspaceIds.value.has(entry.workspaceId)
    const header: VisibleEntry = {
      kind: 'workspace',
      key: entry.key,
      workspaceId: entry.workspaceId,
      name: entry.name,
      count: entry.sessions.length,
      expanded,
    }
    if (!expanded) return [header]
    return [
      header,
      ...entry.sessions.map((session) => ({
        kind: 'session' as const,
        key: `workspace-session:${session.session_id}`,
        session,
        nested: true,
      })),
    ]
  })
})

function sessionTitle(session: SessionHistoryItem): string {
  return session.display_title || session.first_user_input || t('sessions.newSession')
}

function workspaceKind(session: SessionHistoryItem): string {
  return session.workspace?.mode === 'project'
    ? t('sessions.sharedWorkspace')
    : t('sessions.isolatedWorkspace')
}

function canRevealSession(session: SessionHistoryItem): boolean {
  return desktopWorkspaceFileActionsAvailable() && Boolean(session.workspace?.workdir_root)
}

async function revealSessionWorkspace(session: SessionHistoryItem) {
  const path = session.workspace?.workdir_root
  if (!path) return
  try {
    await revealNativePath(path)
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  }
}

function toggleWorkspace(workspaceId: string) {
  const next = new Set(expandedWorkspaceIds.value)
  if (next.has(workspaceId)) next.delete(workspaceId)
  else next.add(workspaceId)
  expandedWorkspaceIds.value = next
}

function expandActiveWorkspace() {
  if (!props.activeSessionId) return
  const group = groupedSessions.value.find((entry) => (
    entry.kind === 'workspace'
    && entry.sessions.some((session) => session.session_id === props.activeSessionId)
  ))
  if (group?.kind !== 'workspace' || expandedWorkspaceIds.value.has(group.workspaceId)) return
  expandedWorkspaceIds.value = new Set([...expandedWorkspaceIds.value, group.workspaceId])
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  if (diff < 3_600_000) {
    const minutes = Math.floor(diff / 60_000)
    return new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }).format(-minutes, 'minute')
  }
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString(locale.value, { month: '2-digit', day: '2-digit' })
}

watch([() => props.activeSessionId, groupedSessions], expandActiveWorkspace, { immediate: true })
</script>

<style scoped>
.session-history {
  flex: 1;
  min-height: 0;
}

.history-entries {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
}

.workspace-group,
.session-row {
  width: 100%;
  border: 0;
  color: var(--app-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.workspace-group {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 52px;
  padding: 8px 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
  box-shadow: 0 5px 14px color-mix(in srgb, var(--app-text) 5%, transparent);
  transition: transform var(--app-transition-fast), border-color var(--app-transition-fast);
}

.workspace-group:hover {
  border-color: color-mix(in srgb, var(--app-text) 42%, var(--app-border));
  transform: translateY(-1px);
}

.workspace-folder-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-muted);
}

.workspace-group-copy,
.session-copy {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
}

.workspace-group-name,
.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-group-name {
  font-size: 13px;
  font-weight: 650;
}

.workspace-group-meta,
.session-meta {
  color: var(--app-text-muted);
  font-size: 11px;
}

.workspace-chevron {
  flex: 0 0 auto;
  color: var(--app-text-muted);
}

.session-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 64px;
  padding: 10px 72px 10px 12px;
  border-radius: var(--app-radius-md);
  background: transparent;
  transition: background-color var(--app-transition-fast);
}

.session-row.nested {
  width: calc(100% - 14px);
  margin-left: 14px;
  padding-left: 18px;
  border-left: 1px solid var(--app-divider);
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}

.session-row:hover,
.session-row.active {
  background: var(--app-surface-pressed);
}

.session-row.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: var(--app-radius-pill);
  background: var(--app-text);
}

.session-title {
  font-size: 13px;
  font-weight: 560;
  line-height: 1.4;
}

.session-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px 8px;
  margin-top: 4px;
}

.turn-count {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.session-actions {
  position: absolute;
  right: 10px;
  top: 50%;
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity var(--app-transition-fast);
}

.session-actions button {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-pill);
  color: var(--app-text-muted);
  background: transparent;
  cursor: pointer;
}

.session-row:hover .session-actions,
.session-row:focus-within .session-actions {
  opacity: 1;
}

.session-actions button:hover {
  color: var(--app-text);
  background: var(--app-surface-muted);
}

.sessions-empty {
  margin-top: var(--app-space-xxl);
  animation: app-fade-in 0.24s ease both;
}

@media (prefers-reduced-motion: reduce) {
  .workspace-group,
  .session-row,
  .session-actions {
    transition: none;
  }
}
</style>
