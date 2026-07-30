<template>
  <n-modal
    :show="show"
    preset="card"
    :title="t('sessions.createTitle')"
    class="new-agent-session-modal"
    @update:show="emit('update:show', $event)"
  >
    <div class="new-session-options">
      <button type="button" class="new-session-option" @click="selectWorkspace(null)">
        <strong>{{ t('sessions.newIndependentTask') }}</strong>
        <span>{{ t('sessions.newIndependentTaskDescription') }}</span>
      </button>
      <section class="new-session-option shared-workspace-option">
        <div>
          <strong>{{ t('sessions.newInWorkspace') }}</strong>
          <span>{{ t('sessions.newInWorkspaceDescription') }}</span>
        </div>
        <n-select
          v-model:value="selectedWorkspaceId"
          :options="workspaceOptions"
          filterable
          :placeholder="t('sessions.selectWorkspace')"
        />
        <div class="shared-workspace-actions">
          <n-button secondary @click="showDirectoryPicker = true">
            {{ t('sessions.selectLocalFolder') }}
          </n-button>
          <n-button
            type="primary"
            :disabled="!selectedWorkspaceId"
            @click="selectedWorkspaceId && selectWorkspace(selectedWorkspaceId)"
          >
            {{ t('sessions.createInWorkspace') }}
          </n-button>
        </div>
      </section>
    </div>
  </n-modal>
  <WorkspaceDirectoryPicker
    v-model:show="showDirectoryPicker"
    @select="registerLinkedWorkspace"
  />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NModal, NSelect, useMessage } from 'naive-ui'
import { workspaceApi, type WorkspaceProjectView } from '@/api/workspace'
import WorkspaceDirectoryPicker from '@/components/workspace/WorkspaceDirectoryPicker.vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  show: boolean
  packageId: string
  initialWorkspaceId?: string | null
}>()
const emit = defineEmits<{
  'update:show': [show: boolean]
  create: [workspaceId: string | null]
}>()
const { t } = useI18n()
const message = useMessage()
const workspaces = ref<WorkspaceProjectView[]>([])
const selectedWorkspaceId = ref<string | null>(null)
const showDirectoryPicker = ref(false)
const workspaceOptions = computed(() => workspaces.value
  .filter(workspace => workspace.mode === 'project')
  .map(workspace => ({
    label: `${workspace.title} — ${workspace.workdir_root}`,
    value: workspace.workspace_id,
  })))

watch(() => props.show, show => {
  if (!show) return
  selectedWorkspaceId.value = props.initialWorkspaceId || null
  void refreshWorkspaces()
})

async function refreshWorkspaces() {
  try {
    workspaces.value = (await workspaceApi.projects()).workspaces
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  }
}

function selectWorkspace(workspaceId: string | null) {
  emit('create', workspaceId)
  emit('update:show', false)
}

async function registerLinkedWorkspace(sourcePath: string) {
  try {
    const response = await workspaceApi.createProject({
      title: sourcePath.split(/[\\/]/).filter(Boolean).at(-1) || t('sessions.sharedWorkspace'),
      mode: 'project',
      root_kind: 'linked',
      workdir_root: sourcePath,
      owner_package_id: props.packageId,
    })
    workspaces.value = [
      response.workspace,
      ...workspaces.value.filter(
        workspace => workspace.workspace_id !== response.workspace.workspace_id,
      ),
    ]
    selectedWorkspaceId.value = response.workspace.workspace_id
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  }
}
</script>

<style scoped>
:global(.new-agent-session-modal) {
  width: min(560px, calc(100vw - 32px));
}
.new-session-options { display: grid; gap: var(--app-space-md); }
.new-session-option {
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  color: var(--app-text);
  padding: var(--app-space-lg);
  display: grid;
  gap: var(--app-space-xs);
  text-align: left;
}
button.new-session-option { cursor: pointer; }
button.new-session-option:hover { border-color: var(--app-text); }
.new-session-option span { color: var(--app-text-muted); font-size: var(--app-font-sm); }
.shared-workspace-option { gap: var(--app-space-md); }
.shared-workspace-option > div:first-child { display: grid; gap: var(--app-space-xs); }
.shared-workspace-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-sm);
}
</style>
