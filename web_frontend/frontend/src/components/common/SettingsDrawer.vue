<template>
  <n-drawer v-model:show="show" :width="400" placement="right">
    <n-drawer-content title="设置">
      <n-space vertical :size="20">
        <div>
          <n-text strong>主题</n-text>
          <n-radio-group v-model:value="themeMode" style="margin-top: 8px">
            <n-radio-button value="light">浅色</n-radio-button>
            <n-radio-button value="dark">深色</n-radio-button>
            <n-radio-button value="auto">自动</n-radio-button>
          </n-radio-group>
        </div>

        <div>
          <n-text strong>界面</n-text>
          <n-space vertical style="margin-top: 8px">
            <n-checkbox>紧凑模式</n-checkbox>
            <n-checkbox>显示侧边栏</n-checkbox>
          </n-space>
        </div>

        <div>
          <n-text strong>关于</n-text>
          <n-text depth="3" style="display: block; margin-top: 8px">
            FastAgentFactory v2.0.0
          </n-text>
          <n-text depth="3" style="display: block">
            现代化 Web 前端
          </n-text>
        </div>
      </n-space>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NDrawer, NDrawerContent, NSpace, NText, NRadioGroup, NRadioButton, NCheckbox } from 'naive-ui'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const uiStore = useUiStore()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const themeMode = computed({
  get: () => uiStore.themeMode,
  set: (value: any) => uiStore.setThemeMode(value),
})
</script>
