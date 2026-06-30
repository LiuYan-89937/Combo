<template>
  <n-modal v-model:show="show" preset="card" title="添加知识源" style="width: 500px">
    <n-form ref="formRef" :model="formData" :rules="rules">
      <n-form-item label="类型" path="kind">
        <n-select v-model:value="formData.kind" :options="kindOptions" />
      </n-form-item>

      <n-form-item label="显示名称" path="display_name">
        <n-input v-model:value="formData.display_name" placeholder="给这个知识源起个名字" />
      </n-form-item>

      <n-form-item
        :label="uriLabel"
        path="uri"
      >
        <n-input v-model:value="formData.uri" :placeholder="uriPlaceholder" />
      </n-form-item>

      <n-form-item v-if="formData.kind === 'note'" label="内容" path="content">
        <n-input
          v-model:value="formData.content"
          type="textarea"
          :rows="6"
          placeholder="输入笔记内容..."
        />
      </n-form-item>

      <n-form-item label="挂载模式" path="mount_mode">
        <n-radio-group v-model:value="formData.mount_mode">
          <n-radio value="index_only">仅索引</n-radio>
          <n-radio value="rag">RAG 检索</n-radio>
        </n-radio-group>
      </n-form-item>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" @click="handleSubmit">添加</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NForm, NFormItem, NInput, NSelect, NRadioGroup, NRadio, NSpace, NButton } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: any]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const formRef = ref<FormInst | null>(null)
const formData = ref({
  kind: 'folder' as 'folder' | 'file' | 'url' | 'note',
  display_name: '',
  uri: '',
  content: '',
  mount_mode: 'rag' as 'index_only' | 'rag',
})

const kindOptions = [
  { label: '文件夹', value: 'folder' },
  { label: '文件', value: 'file' },
  { label: 'URL', value: 'url' },
  { label: '笔记', value: 'note' },
]

const uriLabel = computed(() => {
  const labels: Record<string, string> = {
    folder: '文件夹路径',
    file: '文件路径',
    url: 'URL 地址',
    note: '笔记 ID',
  }
  return labels[formData.value.kind] || 'URI'
})

const uriPlaceholder = computed(() => {
  const placeholders: Record<string, string> = {
    folder: '/path/to/folder',
    file: '/path/to/file.pdf',
    url: 'https://example.com/docs',
    note: 'note-id（自动生成）',
  }
  return placeholders[formData.value.kind] || ''
})

const rules: FormRules = {
  display_name: [
    { required: true, message: '请输入显示名称', trigger: 'blur' },
  ],
  uri: [
    {
      required: true,
      validator: (rule, value) => {
        if (!value && formData.value.kind !== 'note') {
          return new Error('请输入 URI')
        }
        if (formData.value.kind === 'url') {
          try {
            new URL(value)
          } catch {
            return new Error('请输入有效的 URL')
          }
        }
        return true
      },
      trigger: 'blur',
    },
  ],
}

function handleSubmit() {
  formRef.value?.validate((errors) => {
    if (!errors) {
      emit('submit', formData.value)
      // 重置表单
      formData.value = {
        kind: 'folder',
        display_name: '',
        uri: '',
        content: '',
        mount_mode: 'rag',
      }
    }
  })
}
</script>
