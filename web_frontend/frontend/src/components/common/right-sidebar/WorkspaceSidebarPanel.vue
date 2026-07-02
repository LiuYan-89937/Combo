<template>
  <div class="workspace-sidebar-content">
    <div v-if="previewLoading && !runtimeStore.workspaceFile" class="workspace-loading">
      <n-spin size="small" />
      <n-text depth="3">{{ t('workspace.readingFile') }}</n-text>
    </div>
    <FilePreview
      v-else-if="runtimeStore.workspaceFile"
      :file="runtimeStore.workspaceFile"
      @close="closeWorkspacePreview"
    />
    <div v-else class="workspace-browser">
      <div class="context-bar">
        <n-text depth="3">{{ t('workspace.context', { label: workspaceContextLabel }) }}</n-text>
      </div>
      <WorkspaceExplorer
        class="workspace-sidebar-explorer"
        :package-id="workspacePackageId"
        @select-file="handleWorkspaceFileSelect"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NSpin, NText } from 'naive-ui'
import { useCommand } from '@/composables/useCommand'
import { useResourceContext } from '@/composables/useResourceContext'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import type { WorkspaceEntry } from '@/types/protocol'
import FilePreview from '@/components/workspace/FilePreview.vue'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import { useI18n } from '@/composables/useI18n'

const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const resourceContext = useResourceContext()
const { t } = useI18n()
const previewLoading = ref(false)
const WORKSPACE_PREVIEW_MAX_CHARS = 1_000_000

const workspacePackageId = computed(() => resourceContext.packageIdForApi.value)
const workspaceContextLabel = computed(() => resourceContext.label.value)

async function handleWorkspaceFileSelect(entry: WorkspaceEntry) {
  uiStore.setRightSidebarTab('workspace')
  previewLoading.value = true
  runtimeStore.workspaceFile = null
  await commands.readFile(workspaceStore.currentScope, entry.path, workspacePackageId.value, WORKSPACE_PREVIEW_MAX_CHARS)
  if (!runtimeStore.workspaceFile) {
    previewLoading.value = false
  }
}

function closeWorkspacePreview() {
  previewLoading.value = false
  runtimeStore.workspaceFile = null
}

watch(
  () => runtimeStore.workspaceFile,
  (file) => {
    if (file) previewLoading.value = false
  }
)

watch(
  () => workspacePackageId.value,
  () => {
    closeWorkspacePreview()
  }
)
</script>

<style scoped>
.workspace-sidebar-content {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workspace-browser {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.context-bar {
  padding: var(--app-space-sm) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
  background: var(--app-surface-muted);
  font-size: var(--app-font-sm);
}

.workspace-sidebar-explorer {
  flex: 1;
  min-height: 0;
}

.workspace-loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-sm);
  color: var(--app-text-muted);
}
</style>
