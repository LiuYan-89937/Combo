<template>
  <div class="workspace-explorer">
    <div class="explorer-header">
      <div class="header-title">
        <n-text strong>{{ t('workspace.explorer') }}</n-text>
        <n-text depth="3" class="header-subtitle">{{ workspaceStore.currentScope }}</n-text>
      </div>
      <n-space :size="6">
        <n-select
          v-model:value="workspaceStore.currentScope"
          :options="scopeOptions"
          size="small"
          class="scope-select"
          @update:value="handleScopeChange"
        />
        <n-button size="small" quaternary circle @click="refreshTree">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
        </n-button>
      </n-space>
    </div>

    <n-scrollbar class="tree-scrollbar">
      <div class="tree-root">
        <div
          v-for="row in visibleRows"
          :key="row.key"
          class="tree-row"
          :class="{ selected: selectedPath === row.entry.path }"
          :style="{ paddingLeft: `${8 + row.depth * 16}px` }"
          @click="handleEntryClick(row.entry)"
        >
          <button
            v-if="row.entry.kind === 'directory'"
            class="twisty"
            type="button"
            @click.stop="toggleDirectory(row.entry)"
          >
            <n-icon size="13" :class="{ expanded: row.expanded }"><ChevronForward /></n-icon>
          </button>
          <span v-else class="twisty-placeholder"></span>

          <n-icon size="17" :color="entryIconColor(row.entry)" class="entry-icon">
            <component :is="entryIcon(row.entry)" />
          </n-icon>

          <span class="entry-name" :title="row.entry.path">{{ row.entry.name }}</span>
          <span v-if="row.entry.kind === 'file' && row.entry.sizeBytes" class="entry-size">
            {{ formatFileSize(row.entry.sizeBytes) }}
          </span>
        </div>

        <div v-if="rootLoading" class="tree-hint">{{ t('workspace.loading') }}</div>
        <n-empty
          v-else-if="visibleRows.length === 0"
          :description="t('workspace.emptyDirectory')"
          size="small"
          class="empty-tree"
        />
      </div>
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NEmpty,
  NIcon,
  NScrollbar,
  NSelect,
  NSpace,
  NText,
} from 'naive-ui'
import {
  ChevronForward,
  CodeSlash,
  DocumentOutline,
  FolderOpenOutline,
  FolderOutline,
  ImageOutline,
  Refresh,
} from '@/components/icons'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { workspaceEntryView } from '@/stores/runtime/viewMappers'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import type { FactoryFrontendEvent, WorkspaceEntry, WorkspaceScope } from '@/types/protocol'

interface TreeRow {
  key: string
  entry: WorkspaceEntry
  depth: number
  expanded: boolean
}

const emit = defineEmits<{
  selectFile: [entry: WorkspaceEntry]
}>()

const props = defineProps<{
  packageId?: string | null
  workspaceContext?: WorkspaceRequestContext | null
}>()

const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const { t } = useI18n()
const entriesByPath = ref<Record<string, WorkspaceEntry[]>>({})
const loadingPaths = ref<Set<string>>(new Set())
const expandedDirs = ref<Set<string>>(new Set())
const selectedPath = ref('')
const rootLoading = computed(() => loadingPaths.value.has('') && !entriesByPath.value[''])
const requestContext = computed<WorkspaceRequestContext | string | undefined>(() => (
  props.workspaceContext || props.packageId || undefined
))

const scopeOptions = computed(() => [
  { label: t('workspace.scope.package'), value: 'package' },
  { label: t('workspace.scope.workdir'), value: 'workdir' },
  { label: t('workspace.scope.runtime'), value: 'runtime' },
  { label: t('workspace.scope.artifacts'), value: 'artifacts' },
  { label: t('workspace.scope.extensions'), value: 'extensions' },
])

const visibleRows = computed<TreeRow[]>(() => {
  const rows: TreeRow[] = []
  appendRows('', 0, rows)
  return rows
})

function appendRows(path: string, depth: number, rows: TreeRow[]) {
  const entries = sortedEntries(entriesByPath.value[path] || [])
  for (const entry of entries) {
    const expanded = isExpanded(entry.path)
    rows.push({
      key: `${workspaceStore.currentScope}:${entry.path}`,
      entry,
      depth,
      expanded,
    })
    if (entry.kind === 'directory' && expanded) {
      appendRows(entry.path, depth + 1, rows)
    }
  }
}

function sortedEntries(entries: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...entries].sort((left, right) => {
    if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1
    return left.name.localeCompare(right.name, 'zh-CN')
  })
}

async function loadDirectory(path: string) {
  if (loadingPaths.value.has(path)) return
  const nextLoading = new Set(loadingPaths.value)
  nextLoading.add(path)
  loadingPaths.value = nextLoading
  try {
    const event = await commands.refreshWorkspace(
      workspaceStore.currentScope,
      path,
      requestContext.value,
    )
    entriesByPath.value = {
      ...entriesByPath.value,
      [path]: entriesFromEvent(event),
    }
  } finally {
    const done = new Set(loadingPaths.value)
    done.delete(path)
    loadingPaths.value = done
  }
}

function entriesFromEvent(event: FactoryFrontendEvent | null | undefined): WorkspaceEntry[] {
  const entries = event?.payload?.entries
  if (!Array.isArray(entries)) return []
  return entries.map(workspaceEntryView)
}

function handleScopeChange(scope: WorkspaceScope) {
  workspaceStore.setScope(scope)
  resetTree()
  void loadDirectory('')
}

function refreshTree() {
  const expanded = Array.from(expandedDirs.value)
  entriesByPath.value = {}
  void loadDirectory('')
  expanded.forEach((path) => {
    void loadDirectory(path)
  })
}

function resetTree() {
  selectedPath.value = ''
  entriesByPath.value = {}
  expandedDirs.value = new Set()
}

function handleEntryClick(entry: WorkspaceEntry) {
  if (entry.kind === 'directory') {
    void toggleDirectory(entry)
    return
  }
  selectedPath.value = entry.path
  emit('selectFile', entry)
}

async function toggleDirectory(entry: WorkspaceEntry) {
  toggleExpanded(entry.path)
  if (isExpanded(entry.path) && !entriesByPath.value[entry.path]) {
    await loadDirectory(entry.path)
  }
}

function entryIcon(entry: WorkspaceEntry) {
  if (entry.kind === 'directory') {
    return isExpanded(entry.path) ? FolderOpenOutline : FolderOutline
  }

  const ext = entry.name.split('.').pop()?.toLowerCase()
  const codeExts = ['js', 'ts', 'tsx', 'jsx', 'py', 'java', 'go', 'rs', 'cpp', 'c', 'h', 'sql', 'json', 'yaml', 'yml']
  const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp']

  if (ext && codeExts.includes(ext)) return CodeSlash
  if (ext && imageExts.includes(ext)) return ImageOutline
  return DocumentOutline
}

function isExpanded(path: string): boolean {
  return expandedDirs.value.has(path)
}

function toggleExpanded(path: string): void {
  const next = new Set(expandedDirs.value)
  if (next.has(path)) {
    next.delete(path)
  } else {
    next.add(path)
  }
  expandedDirs.value = next
}

function entryIconColor(entry: WorkspaceEntry): string {
  if (entry.kind === 'directory') return 'var(--app-text)'
  return 'var(--app-text-muted)'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

onMounted(() => {
  void loadDirectory('')
})

watch(
  () => workspaceContextKey(requestContext.value),
  () => {
    resetTree()
    void loadDirectory('')
  },
)

function workspaceContextKey(context: WorkspaceRequestContext | string | undefined): string {
  if (typeof context === 'string') return `package:${context}`
  if (!context) return ''
  return [
    context.resourceMode || '',
    context.packageId || '',
    context.factorySessionId || '',
    context.createAgentSessionId || '',
  ].join(':')
}
</script>

<style scoped>
.workspace-explorer {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
}

.explorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  border-bottom: 1px solid var(--app-divider);
  background: var(--app-surface-muted);
}

.header-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-subtitle {
  font-size: 12px;
}

.scope-select {
  width: 116px;
}

.tree-scrollbar {
  flex: 1;
  min-height: 0;
}

.tree-root {
  padding: 6px 0;
}

.tree-row {
  height: 28px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding-right: 8px;
  cursor: pointer;
  color: var(--app-text);
  font-size: 13px;
  user-select: none;
  border-radius: var(--app-radius-sm);
  transition: background-color 0.12s ease;
}

.tree-row:hover {
  background: var(--app-surface-muted);
}

.tree-row.selected {
  background: var(--app-surface-pressed);
  font-weight: 500;
}

.twisty,
.twisty-placeholder {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
}

.twisty {
  border: 0;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: var(--app-text-muted);
  cursor: pointer;
}

.twisty :deep(.n-icon) {
  transition: transform 0.12s ease;
}

.twisty :deep(.n-icon.expanded) {
  transform: rotate(90deg);
}

.entry-icon {
  flex: 0 0 17px;
}

.entry-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-size {
  flex-shrink: 0;
  color: var(--app-text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.tree-hint {
  padding: 16px;
  color: var(--app-text-muted);
  font-size: 13px;
}

.empty-tree {
  margin-top: 40px;
}
</style>
