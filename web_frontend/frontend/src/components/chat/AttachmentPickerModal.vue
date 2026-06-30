<template>
  <n-modal v-model:show="show" preset="card" title="添加附件" style="width: 600px">
    <n-tabs type="line" animated>
      <!-- 本地文件 -->
      <n-tab-pane name="file" tab="本地文件">
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
                <n-text>点击或拖拽文件到此处上传</n-text>
                <n-text depth="3" style="font-size: 12px">
                  支持任意文件类型，最大 10MB
                </n-text>
              </div>
            </n-upload-dragger>
          </n-upload>
        </div>
      </n-tab-pane>

      <!-- 工作区文件 -->
      <n-tab-pane name="workspace" tab="工作区文件">
        <div class="tab-content">
          <n-input
            v-model:value="workspaceSearch"
            placeholder="搜索工作区文件..."
            clearable
          />
          <div class="file-list">
            <n-empty v-if="workspaceFiles.length === 0" description="暂无文件" size="small" />
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
      <n-tab-pane name="url" tab="URL 链接">
        <div class="tab-content">
          <n-form>
            <n-form-item label="URL 地址">
              <n-input v-model:value="urlInput" placeholder="https://example.com/doc.pdf" />
            </n-form-item>
            <n-form-item label="显示名称">
              <n-input v-model:value="urlName" placeholder="文档名称（可选）" />
            </n-form-item>
            <n-button type="primary" @click="handleAddUrl" :disabled="!isValidUrl">
              添加
            </n-button>
          </n-form>
        </div>
      </n-tab-pane>

      <!-- 文本片段 -->
      <n-tab-pane name="text" tab="文本片段">
        <div class="tab-content">
          <n-form>
            <n-form-item label="文本内容">
              <n-input
                v-model:value="textContent"
                type="textarea"
                :rows="6"
                placeholder="粘贴或输入文本内容..."
              />
            </n-form-item>
            <n-form-item label="名称">
              <n-input v-model:value="textName" placeholder="文本片段名称" />
            </n-form-item>
            <n-button type="primary" @click="handleAddText" :disabled="!textContent.trim()">
              添加
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
import { CloudUploadOutline, Document } from '@vicons/ionicons5'

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

function handleFileUpload({ file }: UploadCustomRequestOptions) {
  const reader = new FileReader()
  reader.onload = (e) => {
    const content = e.target?.result as string
    emit('attach', {
      kind: 'file',
      name: file.name,
      content: content.split(',')[1], // Base64
      mime_type: file.type,
    })
    show.value = false
  }
  reader.readAsDataURL(file.file as File)
}

function handleSelectWorkspaceFile(file: any) {
  emit('attach', {
    kind: 'file',
    name: file.name,
    content: file.path, // 工作区文件路径
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
    name: textName.value || '文本片段',
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
  gap: 8px;
  padding: 8px 12px;
  background: var(--n-color-embedded);
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.file-item:hover {
  background: var(--n-color-hover);
}
</style>
