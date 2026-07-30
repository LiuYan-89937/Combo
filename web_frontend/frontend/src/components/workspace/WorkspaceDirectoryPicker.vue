<template>
  <n-modal
    :show="show"
    preset="card"
    :title="t('workspace.selectServerDirectory')"
    class="workspace-directory-picker"
    @update:show="emit('update:show', $event)"
  >
    <div class="directory-picker-toolbar">
      <n-button
        quaternary
        :disabled="!parentPath || loading"
        @click="parentPath && loadDirectory(parentPath)"
      >
        {{ t('workspace.parentDirectory') }}
      </n-button>
      <n-text class="directory-picker-path" :title="currentPath">
        {{ currentPath || t('workspace.selectDirectoryRoot') }}
      </n-text>
    </div>

    <n-spin :show="loading">
      <n-list bordered clickable class="directory-picker-list">
        <n-list-item
          v-for="directory in visibleDirectories"
          :key="directory.path"
          @dblclick="loadDirectory(directory.path)"
        >
          <button
            type="button"
            class="directory-row"
            @click="selectedPath = directory.path"
            @dblclick.stop="loadDirectory(directory.path)"
          >
            <n-icon><FolderOutline /></n-icon>
            <span>{{ directory.name }}</span>
          </button>
        </n-list-item>
      </n-list>
    </n-spin>

    <template #footer>
      <div class="directory-picker-actions">
        <n-button @click="emit('update:show', false)">
          {{ t('common.cancel') }}
        </n-button>
        <n-button
          type="primary"
          :disabled="!selectedPath && !currentPath"
          @click="selectDirectory"
        >
          {{ t('workspace.selectThisDirectory') }}
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NIcon, NList, NListItem, NModal, NSpin, NText, useMessage } from 'naive-ui'
import { FolderOutline } from '@/components/icons'
import { workspaceApi, type WorkspaceDirectoryView } from '@/api/workspace'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  'update:show': [show: boolean]
  select: [path: string]
}>()
const { t } = useI18n()
const message = useMessage()
const roots = ref<WorkspaceDirectoryView[]>([])
const directories = ref<WorkspaceDirectoryView[]>([])
const currentPath = ref('')
const parentPath = ref<string | null>(null)
const selectedPath = ref('')
const loading = ref(false)
const visibleDirectories = computed(() => currentPath.value ? directories.value : roots.value)

watch(
  () => props.show,
  show => {
    if (show) void loadRoots()
  },
)

async function loadRoots() {
  loading.value = true
  selectedPath.value = ''
  currentPath.value = ''
  parentPath.value = null
  try {
    roots.value = (await workspaceApi.directoryRoots()).roots
    directories.value = []
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    loading.value = false
  }
}

async function loadDirectory(path: string) {
  loading.value = true
  selectedPath.value = ''
  try {
    const listing = await workspaceApi.directories(path)
    currentPath.value = listing.path
    parentPath.value = listing.parent
    directories.value = listing.directories
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    loading.value = false
  }
}

function selectDirectory() {
  const path = selectedPath.value || currentPath.value
  if (!path) return
  emit('select', path)
  emit('update:show', false)
}
</script>

<style scoped>
:global(.workspace-directory-picker) {
  width: min(620px, calc(100vw - 32px));
}

.directory-picker-toolbar {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-md);
}

.directory-picker-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.directory-picker-list {
  height: min(420px, 55vh);
  overflow: auto;
}

.directory-row {
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--app-text);
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  text-align: left;
  cursor: pointer;
}

.directory-picker-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-sm);
}
</style>
