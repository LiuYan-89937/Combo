<template>
  <n-modal v-model:show="show" preset="card" :title="t('attachments.title')" style="width: 600px">
    <n-tabs type="line" animated>
      <!-- 本地文件 -->
      <n-tab-pane name="file" :tab="t('attachments.localFile')">
        <div class="tab-content">
          <n-upload
            :custom-request="handleFileUpload"
            :show-file-list="false"
            accept="*/*"
          >
            <n-upload-dragger>
              <div class="upload-area">
                <n-icon size="48" :depth="3">
                  <CloudUploadOutline />
                </n-icon>
                <n-text>{{ t('attachments.uploadMain') }}</n-text>
                <n-text depth="3" style="font-size: 12px">
                  {{ t('attachments.uploadHint') }}
                </n-text>
              </div>
            </n-upload-dragger>
          </n-upload>
        </div>
      </n-tab-pane>

      <!-- 工作区文件 -->
      <n-tab-pane name="workspace" :tab="t('attachments.workspaceFile')">
        <div class="tab-content">
          <n-input
            v-model:value="workspaceSearch"
            :placeholder="t('attachments.workspaceSearchPlaceholder')"
            clearable
          />
          <div class="file-list">
            <n-empty v-if="workspaceFiles.length === 0" :description="t('attachments.noFiles')" size="small" />
            <div
              v-for="file in filteredWorkspaceFiles"
              :key="file.path"
              class="file-item"
              @click="handleSelectWorkspaceFile(file)"
            >
              <n-icon><Document /></n-icon>
              <span>{{ file.name }}</span>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <!-- URL -->
      <n-tab-pane name="url" :tab="t('attachments.url')">
        <div class="tab-content">
          <n-form>
            <n-form-item :label="t('attachments.urlAddress')">
              <n-input v-model:value="urlInput" placeholder="https://example.com/doc.pdf" />
            </n-form-item>
            <n-form-item :label="t('attachments.displayName')">
              <n-input v-model:value="urlName" :placeholder="t('attachments.urlNamePlaceholder')" />
            </n-form-item>
            <n-button type="primary" @click="handleAddUrl" :disabled="!isValidUrl">
              {{ t('common.add') }}
            </n-button>
          </n-form>
        </div>
      </n-tab-pane>

      <!-- 文本片段 -->
      <n-tab-pane name="text" :tab="t('attachments.text')">
        <div class="tab-content">
          <n-form>
            <n-form-item :label="t('attachments.textContent')">
              <n-input
                v-model:value="textContent"
                type="textarea"
                :rows="6"
                :placeholder="t('attachments.textPlaceholder')"
              />
            </n-form-item>
            <n-form-item :label="t('attachments.displayName')">
              <n-input v-model:value="textName" :placeholder="t('attachments.textName')" />
            </n-form-item>
            <n-button type="primary" @click="handleAddText" :disabled="!textContent.trim()">
              {{ t('common.add') }}
            </n-button>
          </n-form>
        </div>
      </n-tab-pane>
    </n-tabs>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NTabs, NTabPane, NUpload, NUploadDragger, NIcon, NText, NInput, NForm, NFormItem, NButton, NEmpty } from 'naive-ui'
import type { UploadCustomRequestOptions } from 'naive-ui'
import { CloudUploadOutline, Document } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { runtimeFileAttachmentFromFile } from '@/utils/attachments'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  attach: [attachment: any]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const { t } = useI18n()

// 工作区文件
const workspaceSearch = ref('')
const workspaceFiles = ref<any[]>([])

const filteredWorkspaceFiles = computed(() => {
  if (!workspaceSearch.value) return workspaceFiles.value
  const query = workspaceSearch.value.toLowerCase()
  return workspaceFiles.value.filter((f) => f.name.toLowerCase().includes(query))
})

// URL
const urlInput = ref('')
const urlName = ref('')

const isValidUrl = computed(() => {
  try {
    new URL(urlInput.value)
    return true
  } catch {
    return false
  }
})

// 文本
const textContent = ref('')
const textName = ref('')

async function handleFileUpload({ file }: UploadCustomRequestOptions) {
  emit('attach', await runtimeFileAttachmentFromFile(file.file as File, { name: file.name }))
  show.value = false
}

function handleSelectWorkspaceFile(file: any) {
  emit('attach', {
    kind: 'file',
    name: file.name,
    content: file.path, // 工作区文件路径
    source_kind: 'workspace_file',
  })
  show.value = false
}

function handleAddUrl() {
  if (!isValidUrl.value) return

  emit('attach', {
    kind: 'url',
    name: urlName.value || urlInput.value,
    content: urlInput.value,
  })

  urlInput.value = ''
  urlName.value = ''
  show.value = false
}

function handleAddText() {
  if (!textContent.value.trim()) return

  emit('attach', {
    kind: 'text',
    name: textName.value || t('attachments.defaultTextName'),
    content: textContent.value,
  })

  textContent.value = ''
  textName.value = ''
  show.value = false
}
</script>

<style scoped>
.tab-content {
  padding: 16px 0;
}

.upload-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px;
}

.file-list {
  margin-top: 12px;
  max-height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  background: var(--app-surface-muted);
  border: 1px solid transparent;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color var(--app-transition-fast), border-color var(--app-transition-fast);
}

.file-item:hover {
  background: var(--app-surface-hover);
  border-color: var(--app-border);
}
</style>
