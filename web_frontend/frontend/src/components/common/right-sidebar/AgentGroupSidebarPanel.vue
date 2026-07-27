<template>
  <div class="agent-group-sidebar">
    <!-- 群聊列表 -->
    <section class="sidebar-section">
      <div class="section-header">
        <h3>群聊列表</h3>
        <n-button size="small" @click="showCreateDialog = true">新建</n-button>
      </div>
      <n-list v-if="store.groups.length > 0" bordered clickable>
        <n-list-item
          v-for="group in store.groups"
          :key="group.group_id"
          :class="{ active: store.activeGroup?.group_id === group.group_id }"
          @click="store.loadGroup(group.group_id)"
        >
          <div class="group-item">
            <div class="group-title">{{ group.title }}</div>
            <div class="group-meta">
              <n-tag size="tiny" :type="statusTagType(group.status)">
                {{ group.status }}
              </n-tag>
              <span class="member-count">{{ group.members.length }} 成员</span>
            </div>
          </div>
          <template #suffix>
            <n-popconfirm
              @positive-click="handleDeleteGroup(group.group_id)"
              @click.stop
            >
              <template #trigger>
                <n-button size="tiny" quaternary circle @click.stop>
                  <template #icon>
                    <n-icon><TrashOutline /></n-icon>
                  </template>
                </n-button>
              </template>
              确定删除群聊？
            </n-popconfirm>
          </template>
        </n-list-item>
      </n-list>
      <n-empty v-else description="暂无群聊" size="small" />
    </section>

    <!-- 参与者状态 -->
    <section v-if="store.activeGroup" class="sidebar-section">
      <div class="section-header">
        <h3>参与者</h3>
        <n-button size="small" @click="showAddMemberDialog = true">添加</n-button>
      </div>
      <n-list bordered>
        <n-list-item v-for="participant in store.participants" :key="participant.package_id">
          <div class="participant-item">
            <div class="participant-name">{{ participant.agent_name }}</div>
            <div class="participant-stats">
              <n-tag v-if="participant.statuses.includes('cancelling')" type="warning" size="tiny">
                {{ t('agentGroup.runCancelling') }}
              </n-tag>
              <n-tag v-else-if="participant.active_run_count > 0" type="info" size="tiny">
                运行中: {{ participant.active_run_count }}
              </n-tag>
              <span class="run-count">{{ participant.run_count }} 次运行</span>
            </div>
          </div>
          <template #suffix>
            <n-button
              size="tiny"
              quaternary
              circle
              @click="handleRemoveMember(participant.package_id)"
            >
              <template #icon>
                <n-icon><CloseOutline /></n-icon>
              </template>
            </n-button>
          </template>
        </n-list-item>
      </n-list>
    </section>

    <!-- 工作区文件 -->
    <section v-if="store.activeGroup" class="sidebar-section">
      <div class="section-header">
        <h3>共享工作区</h3>
      </div>
      <div class="workspace-info">版本: {{ store.activeGroup.current_workspace_revision }}</div>
      <FilePreview v-if="runtimeStore.workspaceFile" :file="runtimeStore.workspaceFile" @close="closePreview" />
      <WorkspaceExplorer
        v-show="!runtimeStore.workspaceFile"
        :workspace-context="workspaceContext"
        @select-file="previewFile"
      />
    </section>

    <!-- 创建群聊对话框 -->
    <n-modal v-model:show="showCreateDialog" preset="card" title="创建群聊" style="width: 500px">
      <n-form ref="createFormRef" :model="createForm" :rules="createFormRules">
        <n-form-item label="群聊名称" path="title">
          <n-input v-model:value="createForm.title" placeholder="输入群聊名称" />
        </n-form-item>
        <n-form-item label="选择成员" path="member_package_ids">
          <n-select
            v-model:value="createForm.member_package_ids"
            :options="agentOptions"
            multiple
            filterable
            placeholder="选择 Agent"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 12px">
          <n-button @click="showCreateDialog = false">取消</n-button>
          <n-button type="primary" :loading="store.saving" @click="handleCreate">创建</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 添加成员对话框 -->
    <n-modal v-model:show="showAddMemberDialog" preset="card" title="添加成员" style="width: 400px">
      <n-form ref="addMemberFormRef" :model="addMemberForm" :rules="addMemberFormRules">
        <n-form-item label="选择 Agent" path="package_id">
          <n-select
            v-model:value="addMemberForm.package_id"
            :options="availableAgentOptions"
            filterable
            placeholder="选择 Agent"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 12px">
          <n-button @click="showAddMemberDialog = false">取消</n-button>
          <n-button
            type="primary"
            :loading="store.saving"
            @click="handleAddMember"
          >
            添加
          </n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NButton,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NList,
  NListItem,
  NModal,
  NPopconfirm,
  NSelect,
  NTag,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { TrashOutline, CloseOutline } from '@vicons/ionicons5'
import { useAgentGroupStore } from '@/stores/agentGroup'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import FilePreview from '@/components/workspace/FilePreview.vue'
import { useResourceContext } from '@/composables/useResourceContext'
import { useCommand } from '@/composables/useCommand'
import { useRuntimeStore } from '@/stores/runtime'
import { useWorkspaceStore } from '@/stores/workspace'
import type { WorkspaceEntry } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'
import {
  requiredArrayRule,
  requiredTextRule,
  validateForm,
} from '@/utils/formValidation'

const store = useAgentGroupStore()
const resourceContext = useResourceContext()
const commands = useCommand()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const { t } = useI18n()
const workspaceContext = computed(() => resourceContext.workspaceContext.value)

// State
const showCreateDialog = ref(false)
const showAddMemberDialog = ref(false)
const createFormRef = ref<FormInst | null>(null)
const addMemberFormRef = ref<FormInst | null>(null)
const createForm = ref({
  title: '',
  member_package_ids: [] as string[],
})
const addMemberForm = ref({
  package_id: null as string | null,
})
const createFormRules = computed<FormRules>(() => ({
  title: [requiredTextRule(t('validation.required'))],
  member_package_ids: [requiredArrayRule(t('validation.selectionRequired'))],
}))
const addMemberFormRules = computed<FormRules>(() => ({
  package_id: [requiredTextRule(t('validation.selectionRequired'), 'change')],
}))

// Computed
const agentOptions = computed(() => {
  return store.agents.map(a => ({
    label: a.agent_name,
    value: a.package_id,
  }))
})

const availableAgentOptions = computed(() => {
  if (!store.activeGroup) return agentOptions.value
  const memberIds = new Set(store.members.map(m => m.package_id))
  return agentOptions.value.filter(opt => !memberIds.has(opt.value))
})

const statusTagType = (status: string) => {
  if (status === 'active') return 'success'
  if (status === 'archived') return 'default'
  return 'info'
}

// Methods
const handleCreate = async () => {
  if (!await validateForm(createFormRef.value)) return

  try {
    await store.createGroup({
      ...createForm.value,
      title: createForm.value.title.trim(),
    })
    showCreateDialog.value = false
    createForm.value = { title: '', member_package_ids: [] }
  } catch (e) {
    console.error('Failed to create group:', e)
  }
}

const handleDeleteGroup = async (groupId: string) => {
  try {
    await store.deleteGroup(groupId)
  } catch (e) {
    console.error('Failed to delete group:', e)
  }
}

const handleAddMember = async () => {
  if (!await validateForm(addMemberFormRef.value)) return
  const packageId = addMemberForm.value.package_id
  if (!packageId) return

  try {
    await store.addMember(packageId)
    showAddMemberDialog.value = false
    addMemberForm.value.package_id = null
  } catch (e) {
    console.error('Failed to add member:', e)
  }
}

const handleRemoveMember = async (packageId: string) => {
  try {
    await store.removeMember(packageId)
  } catch (e) {
    console.error('Failed to remove member:', e)
  }
}

async function previewFile(entry: WorkspaceEntry) {
  runtimeStore.workspaceFile = null
  await commands.readFile(workspaceStore.currentScope, entry.path, workspaceContext.value, 1_000_000)
}

function closePreview() {
  runtimeStore.workspaceFile = null
}

</script>

<style scoped>
.agent-group-sidebar {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 16px;
  height: 100%;
  overflow-y: auto;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--n-text-color);
}

.group-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.group-title {
  font-weight: 500;
}

.group-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--n-text-color-disabled);
}

.member-count {
  font-size: 12px;
}

.n-list-item.active {
  background: var(--n-color-primary-hover);
}

.participant-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.participant-name {
  font-weight: 500;
}

.participant-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.run-count {
  color: var(--n-text-color-disabled);
}

.workspace-info {
  padding: 12px;
  background: var(--n-color-modal);
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.workspace-info p {
  margin: 0;
  font-size: 13px;
  color: var(--n-text-color-disabled);
}
</style>
