<template>
  <div class="workspace-view">
    <div class="workspace-container">
      <WorkspaceExplorer
        class="workspace-explorer"
        @select-file="handleSelectFile"
      />
      <div v-if="runtimeStore.workspaceFile || previewLoading" class="file-preview-panel">
        <div v-if="previewLoading && !runtimeStore.workspaceFile" class="preview-loading">
          <n-spin size="small" />
          <n-text depth="3">正在读取文件</n-text>
        </div>
        <FilePreview v-else-if="runtimeStore.workspaceFile" :file="runtimeStore.workspaceFile" @close="closePreview" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { NSpin, NText } from 'naive-ui'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import FilePreview from '@/components/workspace/FilePreview.vue'
import { useCommand } from '@/composables/useCommand'
import { useRuntimeStore } from '@/stores/runtime'
import { useWorkspaceStore } from '@/stores/workspace'
import type { WorkspaceEntry } from '@/types/protocol'

const commands = useCommand()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const previewLoading = ref(false)

function handleSelectFile(entry: WorkspaceEntry) {
  previewLoading.value = true
  runtimeStore.workspaceFile = null
  commands.readFile(workspaceStore.currentScope, entry.path)
}

function closePreview() {
  previewLoading.value = false
  runtimeStore.workspaceFile = null
}

watch(
  () => runtimeStore.workspaceFile,
  (file) => {
    if (file) previewLoading.value = false
  }
)
</script>

<style scoped>
.workspace-view {
  height: 100%;
  background: var(--n-color);
}

.workspace-container {
  height: 100%;
  display: flex;
}

.workspace-explorer {
  width: 320px;
  border-right: 1px solid var(--n-border-color);
}

.file-preview-panel {
  flex: 1;
  min-width: 0;
}

.preview-loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
</style>
