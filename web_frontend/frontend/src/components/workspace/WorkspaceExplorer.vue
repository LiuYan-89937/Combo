<template>
  <div class="workspace-explorer">
    <div class="explorer-header">
      <n-breadcrumb>
        <n-breadcrumb-item @click="workspaceStore.navigateTo('')">
          {{ workspaceStore.currentScope }}
        </n-breadcrumb-item>
        <n-breadcrumb-item
          v-for="(part, index) in workspaceStore.pathParts"
          :key="index"
          @click="navigateToPath(index)"
        >
          {{ part }}
        </n-breadcrumb-item>
      </n-breadcrumb>

      <n-space>
        <n-select
          v-model:value="workspaceStore.currentScope"
          :options="scopeOptions"
          size="small"
          style="width: 120px"
          @update:value="handleScopeChange"
        />
        <n-button size="small" @click="handleRefresh">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
        </n-button>
      </n-space>
    </div>

    <n-scrollbar class="file-list">
      <n-list hoverable clickable>
        <!-- 返回上级 -->
        <n-list-item
          v-if="workspaceStore.currentPath"
          @click="workspaceStore.navigateUp()"
        >
          <n-thing>
            <template #avatar>
              <n-icon size="20"><ArrowBack /></n-icon>
            </template>
            <template #header>
              <n-text>返回上级</n-text>
            </template>
          </n-thing>
        </n-list-item>

        <!-- 文件/文件夹列表 -->
        <n-list-item
          v-for="entry in sortedEntries"
          :key="entry.path"
          @click="handleEntryClick(entry)"
        >
          <n-thing>
            <template #avatar>
              <n-icon size="20" :color="entryIconColor(entry)">
                <component :is="entryIcon(entry)" />
              </n-icon>
            </template>
            <template #header>
              <n-text>{{ entry.name }}</n-text>
            </template>
            <template #description>
              <n-space align="center" :size="8">
                <n-text v-if="entry.kind === 'file' && entry.sizeBytes" depth="3" style="font-size: 12px">
                  {{ formatFileSize(entry.sizeBytes) }}
                </n-text>
                <n-text v-if="entry.updatedAt" depth="3" style="font-size: 12px">
                  {{ formatTime(entry.updatedAt) }}
                </n-text>
              </n-space>
            </template>
            <template #action>
              <n-dropdown :options="getEntryActions(entry)" @select="(key) => handleAction(key, entry)">
                <n-button size="small" quaternary circle>
                  <n-icon><EllipsisVertical /></n-icon>
                </n-button>
              </n-dropdown>
            </template>
          </n-thing>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="sortedEntries.length === 0"
        description="此目录为空"
        size="small"
        style="margin-top: 40px"
      />
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { NBreadcrumb, NBreadcrumbItem, NSelect, NButton, NSpace, NIcon, NScrollbar, NList, NListItem, NThing, NText, NDropdown, NEmpty } from 'naive-ui'
import { Refresh, ArrowBack, FolderOutline, DocumentOutline, CodeSlash, ImageOutline, EllipsisVertical } from '@vicons/ionicons5'
import { useWorkspaceStore } from '@/stores/workspace'
import { useRuntimeStore } from '@/stores/runtime'
import { useCommand } from '@/composables/useCommand'
import type { WorkspaceEntry, WorkspaceScope } from '@/types/protocol'

const emit = defineEmits<{
  selectFile: [entry: WorkspaceEntry]
}>()

const props = defineProps<{
  packageId?: string | null
}>()

const workspaceStore = useWorkspaceStore()
const runtimeStore = useRuntimeStore()
const commands = useCommand()

const scopeOptions = [
  { label: 'package', value: 'package' },
  { label: 'workdir', value: 'workdir' },
  { label: 'runtime', value: 'runtime' },
  { label: 'artifacts', value: 'artifacts' },
  { label: 'extensions', value: 'extensions' },
]

const sortedEntries = computed(() => {
  const dirs = runtimeStore.workspaceEntries.filter((e) => e.kind === 'directory')
  const files = runtimeStore.workspaceEntries.filter((e) => e.kind === 'file')
  return [...dirs, ...files]
})

function handleScopeChange(scope: WorkspaceScope) {
  workspaceStore.setScope(scope)
  handleRefresh()
}

function handleRefresh() {
  commands.refreshWorkspace(
    workspaceStore.currentScope,
    workspaceStore.currentPath,
    props.packageId || undefined
  )
}

function navigateToPath(index: number) {
  const parts = workspaceStore.pathParts.slice(0, index + 1)
  workspaceStore.navigateTo(parts.join('/'))
  handleRefresh()
}

function handleEntryClick(entry: WorkspaceEntry) {
  if (entry.kind === 'directory') {
    workspaceStore.navigateTo(entry.path)
    handleRefresh()
  } else {
    emit('selectFile', entry)
  }
}

function handleAction(key: string, entry: WorkspaceEntry) {
  switch (key) {
    case 'open':
      if (entry.kind === 'file') {
        emit('selectFile', entry)
      }
      break
    case 'download':
      // TODO: 下载文件
      break
  }
}

function getEntryActions(entry: WorkspaceEntry) {
  if (entry.kind === 'file') {
    return [
      { label: '打开', key: 'open' },
      { label: '下载', key: 'download' },
    ]
  }
  return []
}

function entryIcon(entry: WorkspaceEntry) {
  if (entry.kind === 'directory') return FolderOutline

  const ext = entry.name.split('.').pop()?.toLowerCase()
  const codeExts = ['js', 'ts', 'py', 'java', 'go', 'rs', 'cpp', 'c', 'h']
  const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp']

  if (ext && codeExts.includes(ext)) return CodeSlash
  if (ext && imageExts.includes(ext)) return ImageOutline
  return DocumentOutline
}

function entryIconColor(entry: WorkspaceEntry): string {
  if (entry.kind === 'directory') return '#f0a020'
  return 'inherit'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

onMounted(() => {
  handleRefresh()
})

watch(
  () => props.packageId,
  () => {
    workspaceStore.navigateTo('')
    handleRefresh()
  }
)
</script>

<style scoped>
.workspace-explorer {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--n-color);
}

.explorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.file-list {
  flex: 1;
  min-height: 0;
}
</style>
