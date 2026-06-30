<template>
  <n-modal v-model:show="show" preset="card" title="MCP 服务器配置" style="width: 600px">
    <n-form ref="formRef" :model="formData">
      <n-form-item label="显示名称">
        <n-input v-model:value="formData.display_name" placeholder="服务器名称" />
      </n-form-item>

      <n-form-item label="命令">
        <n-input v-model:value="formData.command" placeholder="node" />
      </n-form-item>

      <n-form-item label="参数">
        <n-input v-model:value="formData.args" placeholder="server.js" />
      </n-form-item>

      <n-form-item label="工作目录">
        <n-input v-model:value="formData.cwd" placeholder="/path/to/server" />
      </n-form-item>

      <n-form-item label="环境变量">
        <n-input
          v-model:value="formData.env"
          type="textarea"
          :rows="3"
          placeholder='{"KEY": "value"}'
        />
      </n-form-item>

      <n-form-item label="超时（秒）">
        <n-input-number v-model:value="formData.timeout_seconds" :min="1" :max="300" />
      </n-form-item>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" @click="handleSubmit">保存</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NForm, NFormItem, NInput, NInputNumber, NSpace, NButton } from 'naive-ui'

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

const formRef = ref()
const formData = ref({
  display_name: '',
  transport: 'stdio',
  command: '',
  args: '',
  cwd: '',
  env: '{}',
  timeout_seconds: 60,
  enabled: true,
})

function handleSubmit() {
  emit('submit', {
    ...formData.value,
    source: {
      type: 'local',
      name: formData.value.display_name,
    },
  })
}
</script>
