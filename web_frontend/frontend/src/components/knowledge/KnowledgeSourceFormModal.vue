<template>
  <n-modal v-model:show="show" preset="card" :title="t('knowledge.formTitle')" style="width: 640px">
    <n-form ref="formRef" :model="formData" :rules="rules">
      <n-form-item :label="t('knowledge.kind')" path="kind">
        <n-select v-model:value="formData.kind" :options="kindOptions" @update:value="handleKindChange" />
      </n-form-item>

      <n-form-item :label="t('knowledge.displayName')" path="display_name">
        <n-input v-model:value="formData.display_name" :placeholder="t('knowledge.displayNamePlaceholder')" />
      </n-form-item>

      <n-form-item v-if="usesUpload" :label="t('knowledge.fileContent')">
        <div
          class="upload-zone"
          @dragover.prevent
          @drop.prevent="handleDrop"
        >
          <n-text>{{ uploadTitle }}</n-text>
          <n-text depth="3" class="upload-hint">
            {{ t('knowledge.uploadHint') }}
          </n-text>
          <n-space>
            <n-button @click="openFilePicker">{{ t('knowledge.selectFile') }}</n-button>
            <n-button @click="openFolderPicker">{{ t('knowledge.selectFolder') }}</n-button>
          </n-space>
        </div>
        <input
          ref="fileInputRef"
          class="native-input"
          type="file"
          multiple
          @change="handleFileInput"
        />
        <input
          ref="folderInputRef"
          class="native-input"
          type="file"
          multiple
          webkitdirectory
          directory
          @change="handleFileInput"
        />
        <div v-if="selectedFiles.length" class="selected-files">
          <n-text depth="3">{{ t('knowledge.filesSelected', { count: selectedFiles.length }) }}</n-text>
          <div v-for="item in selectedFiles.slice(0, 8)" :key="item.relativePath" class="selected-file">
            {{ item.relativePath }}
          </div>
          <n-text v-if="selectedFiles.length > 8" depth="3" class="upload-hint">
            {{ t('knowledge.moreFiles', { count: selectedFiles.length - 8 }) }}
          </n-text>
        </div>
      </n-form-item>

      <n-form-item v-if="formData.kind === 'url'" :label="t('knowledge.urlAddress')" path="uri">
        <n-input v-model:value="formData.uri" placeholder="https://example.com/docs" />
      </n-form-item>

      <n-form-item v-if="formData.kind === 'note'" :label="t('knowledge.content')" path="content">
        <n-input
          v-model:value="formData.content"
          type="textarea"
          :rows="6"
          :placeholder="t('knowledge.notePlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('knowledge.mountMode')" path="mount_mode">
        <n-radio-group v-model:value="formData.mount_mode">
          <n-radio value="index_only">{{ t('knowledge.indexOnly') }}</n-radio>
          <n-radio value="rag">{{ t('knowledge.rag') }}</n-radio>
        </n-radio-group>
      </n-form-item>

      <n-collapse-transition :show="formData.mount_mode === 'rag'">
        <div class="rag-options">
          <n-form-item :label="t('knowledge.chunkingStrategy')">
            <n-select v-model:value="chunking.splitter" :options="splitterOptions" />
          </n-form-item>
          <div class="chunk-grid">
            <n-form-item :label="t('knowledge.chunkSize')">
              <n-input-number v-model:value="chunking.chunkSize" :min="100" :max="8000" :step="100" />
            </n-form-item>
            <n-form-item :label="t('knowledge.chunkOverlap')">
              <n-input-number v-model:value="chunking.chunkOverlap" :min="0" :max="2000" :step="20" />
            </n-form-item>
          </div>
        </div>
      </n-collapse-transition>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :disabled="!canSubmit" @click="handleSubmit">{{ t('common.add') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton,
  NCollapseTransition,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NRadio,
  NRadioGroup,
  NSelect,
  NSpace,
  NText,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import type { KnowledgeSourceInput, KnowledgeUploadFile } from '@/api/resourceTypes'
import { useI18n } from '@/composables/useI18n'

type SourceKind = 'folder' | 'file' | 'url' | 'note'
type SplitterKind = 'recursive' | 'markdown' | 'code' | 'json'

interface FileSystemEntryLike {
  isFile: boolean
  isDirectory: boolean
  name: string
}

interface FileSystemFileEntryLike extends FileSystemEntryLike {
  file: (callback: (file: File) => void) => void
}

interface FileSystemDirectoryEntryLike extends FileSystemEntryLike {
  createReader: () => {
    readEntries: (callback: (entries: FileSystemEntryLike[]) => void) => void
  }
}

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: KnowledgeSourceInput]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const formRef = ref<FormInst | null>(null)
const { t } = useI18n()
const fileInputRef = ref<HTMLInputElement | null>(null)
const folderInputRef = ref<HTMLInputElement | null>(null)
const selectedFiles = ref<KnowledgeUploadFile[]>([])
const formData = ref({
  kind: 'folder' as SourceKind,
  display_name: '',
  uri: '',
  content: '',
  mount_mode: 'rag' as 'index_only' | 'rag',
})
const chunking = ref({
  splitter: 'recursive' as SplitterKind,
  chunkSize: 800,
  chunkOverlap: 120,
})

const kindOptions = computed(() => [
  { label: t('knowledge.uploadFolder'), value: 'folder' },
  { label: t('knowledge.uploadFile'), value: 'file' },
  { label: 'URL', value: 'url' },
  { label: t('knowledge.note'), value: 'note' },
])

const splitterOptions = computed(() => [
  { label: t('knowledge.splitterRecursive'), value: 'recursive' },
  { label: t('knowledge.splitterMarkdown'), value: 'markdown' },
  { label: t('knowledge.splitterCode'), value: 'code' },
  { label: t('knowledge.splitterJson'), value: 'json' },
])

const usesUpload = computed(() => formData.value.kind === 'folder' || formData.value.kind === 'file')
const uploadTitle = computed(() => (formData.value.kind === 'folder' ? t('knowledge.dropFolder') : t('knowledge.dropFile')))
const canSubmit = computed(() => {
  if (!formData.value.display_name.trim()) return false
  if (usesUpload.value) return selectedFiles.value.length > 0
  if (formData.value.kind === 'url') return isValidUrl(formData.value.uri)
  if (formData.value.kind === 'note') return formData.value.content.trim().length > 0
  return true
})

const rules = computed<FormRules>(() => ({
  display_name: [
    { required: true, message: t('knowledge.validateDisplayName'), trigger: 'blur' },
  ],
  uri: [
    {
      validator: (_rule, value) => {
        if (formData.value.kind !== 'url') return true
        return isValidUrl(value) ? true : new Error(t('knowledge.validateUrl'))
      },
      trigger: 'blur',
    },
  ],
  content: [
    {
      validator: () => {
        if (formData.value.kind !== 'note') return true
        return formData.value.content.trim() ? true : new Error(t('knowledge.validateNote'))
      },
      trigger: 'blur',
    },
  ],
}))

function handleKindChange() {
  selectedFiles.value = []
  formData.value.uri = ''
  formData.value.content = ''
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function openFolderPicker() {
  folderInputRef.value?.click()
}

function handleFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  addFiles(Array.from(input.files || []).map((file) => ({
    file,
    relativePath: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
  })))
  input.value = ''
}

async function handleDrop(event: DragEvent) {
  const items = Array.from(event.dataTransfer?.items || [])
  if (items.length) {
    const files = await filesFromDataTransferItems(items)
    addFiles(files)
    return
  }
  addFiles(Array.from(event.dataTransfer?.files || []).map((file) => ({ file, relativePath: file.name })))
}

function addFiles(files: KnowledgeUploadFile[]) {
  const next = new Map(selectedFiles.value.map((item) => [item.relativePath, item]))
  files.forEach((item) => {
    if (item.file.size >= 0 && item.relativePath) {
      next.set(item.relativePath, item)
    }
  })
  selectedFiles.value = Array.from(next.values())
}

async function filesFromDataTransferItems(items: DataTransferItem[]): Promise<KnowledgeUploadFile[]> {
  const collected: KnowledgeUploadFile[] = []
  for (const item of items) {
    const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => FileSystemEntryLike | null }).webkitGetAsEntry?.()
    if (entry) {
      collected.push(...await filesFromEntry(entry, ''))
      continue
    }
    const file = item.getAsFile()
    if (file) collected.push({ file, relativePath: file.name })
  }
  return collected
}

async function filesFromEntry(entry: FileSystemEntryLike, prefix: string): Promise<KnowledgeUploadFile[]> {
  if (entry.isFile) {
    const file = await fileFromEntry(entry as FileSystemFileEntryLike)
    return [{ file, relativePath: [prefix, file.name].filter(Boolean).join('/') }]
  }
  if (!entry.isDirectory) return []
  const directory = entry as FileSystemDirectoryEntryLike
  const entries = await readDirectoryEntries(directory)
  const nextPrefix = [prefix, directory.name].filter(Boolean).join('/')
  const groups = await Promise.all(entries.map((item) => filesFromEntry(item, nextPrefix)))
  return groups.flat()
}

function fileFromEntry(entry: FileSystemFileEntryLike): Promise<File> {
  return new Promise((resolve) => entry.file(resolve))
}

function readDirectoryEntries(entry: FileSystemDirectoryEntryLike): Promise<FileSystemEntryLike[]> {
  const reader = entry.createReader()
  const entries: FileSystemEntryLike[] = []
  return new Promise((resolve) => {
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries)
          return
        }
        entries.push(...batch)
        readBatch()
      })
    }
    readBatch()
  })
}

function handleSubmit() {
  if (!canSubmit.value) return
  formRef.value?.validate((errors) => {
    if (errors) return
    emit('submit', buildSourceInput())
    resetForm()
  })
}

function buildSourceInput(): KnowledgeSourceInput {
  const base: KnowledgeSourceInput = {
    kind: formData.value.kind,
    display_name: formData.value.display_name.trim(),
    uri: formData.value.uri.trim(),
    content: formData.value.content,
    mount_mode: formData.value.mount_mode,
    ingestion_plan: formData.value.mount_mode === 'rag'
      ? {
          planner: 'system_default',
          default_splitter: chunking.value.splitter,
          default_chunk_size: chunking.value.chunkSize,
          default_chunk_overlap: chunking.value.chunkOverlap,
          rules: [],
        }
      : undefined,
  }
  if (usesUpload.value) {
    base.uri = ''
    base.files = selectedFiles.value
  }
  if (formData.value.kind === 'note') {
    base.uri = formData.value.content
  }
  if (formData.value.kind === 'url') {
    base.kind = 'url'
  }
  return base
}

function resetForm() {
  formData.value = {
    kind: 'folder',
    display_name: '',
    uri: '',
    content: '',
    mount_mode: 'rag',
  }
  chunking.value = {
    splitter: 'recursive',
    chunkSize: 800,
    chunkOverlap: 120,
  }
  selectedFiles.value = []
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}
</script>

<style scoped>
.upload-zone {
  width: 100%;
  min-height: 150px;
  border: 1px dashed var(--app-border-hover);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--app-surface-muted);
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.upload-zone:hover {
  border-color: var(--app-text);
  background: var(--app-surface-hover);
}

.upload-hint {
  font-size: 12px;
}

.native-input {
  display: none;
}

.selected-files {
  width: 100%;
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.selected-file {
  font-size: 12px;
  color: var(--app-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-options {
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  margin-bottom: 12px;
  background: var(--app-surface-muted);
}

.chunk-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
</style>
