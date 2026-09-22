<template>
  <section class="execution-settings">
    <n-form-item label="允许并发调用">
      <n-switch :value="policy.allow_parallel_calls" @update:value="setParallel" />
    </n-form-item>
    <n-form-item v-if="policy.allow_parallel_calls" label="最大并发请求数">
      <n-input-number :value="policy.max_parallel_calls" :min="1" :max="128" @update:value="setParallelCount" />
    </n-form-item>
    <n-form-item label="单次调用超时（秒）">
      <n-input-number :value="policy.timeout_seconds" :min="1" :max="3600" clearable placeholder="不限制" @update:value="value => update({ timeout_seconds: value })" />
    </n-form-item>
    <p class="execution-hint">留空表示不限制工具执行时长。MCP 服务的连接、请求超时仍独立生效。</p>
  </section>
</template>

<script setup lang="ts">
import { NFormItem, NInputNumber, NSwitch } from 'naive-ui'
import type { ToolRuntimePolicyInput } from '@/api/capabilityPools'
const props = defineProps<{ policy: ToolRuntimePolicyInput }>()
const emit = defineEmits<{ 'update:policy': [value: ToolRuntimePolicyInput] }>()
function update(patch: Partial<ToolRuntimePolicyInput>): void {
  emit('update:policy', { ...props.policy, ...patch })
}
function setParallel(value: boolean): void {
  update({ allow_parallel_calls: value, max_parallel_calls: value ? props.policy.max_parallel_calls : 1 })
}
function setParallelCount(value: number | null): void {
  if (value !== null) update({ max_parallel_calls: value })
}
</script>

<style scoped>
.execution-settings { min-width: 0; }
.execution-hint { margin: 0; color: var(--text-color-3); font-size: 12px; line-height: 1.6; }
</style>
