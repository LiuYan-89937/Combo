<template>
  <section class="tool-approval-panel">
    <div class="approval-header">
      <div class="approval-title">
        <n-icon size="18">
          <ShieldCheckmark />
        </n-icon>
        <span>工具调用待确认</span>
      </div>
      <n-tag size="small" :bordered="false">
        {{ requests.length }} 项
      </n-tag>
    </div>

    <div class="approval-list">
      <div
        v-for="(request, index) in requests"
        :key="requestKey(request, index)"
        class="approval-item"
      >
        <div class="tool-line">
          <n-text strong>{{ toolName(request) }}</n-text>
          <n-tag size="small" :type="riskTagType(request)">
            {{ riskLabel(request) }}
          </n-tag>
        </div>

        <p v-if="toolSummary(request)" class="tool-summary">
          {{ toolSummary(request) }}
        </p>

        <div v-if="riskReasons(request).length > 0" class="risk-reasons">
          <span
            v-for="reason in riskReasons(request)"
            :key="reason"
            class="risk-reason"
          >
            {{ reason }}
          </span>
        </div>

        <n-collapse v-if="hasArguments(request)" class="arguments-collapse" arrow-placement="right">
          <n-collapse-item title="参数" name="arguments">
            <pre class="arguments-block">{{ formatArguments(request) }}</pre>
          </n-collapse-item>
        </n-collapse>
      </div>
    </div>

    <div class="revision-row">
      <n-input
        v-model:value="revisionGuidance"
        type="textarea"
        size="small"
        placeholder="给模型的重写要求"
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
    </div>

    <div class="approval-actions">
      <n-space justify="end" :wrap="true">
        <n-button size="small" @click="handleDeny">
          <template #icon>
            <n-icon><CloseCircle /></n-icon>
          </template>
          拒绝
        </n-button>
        <n-button size="small" :disabled="!revisionGuidance.trim()" @click="handleRevise">
          <template #icon>
            <n-icon><CreateOutline /></n-icon>
          </template>
          要求重写
        </n-button>
        <n-button size="small" @click="handleTrust">
          <template #icon>
            <n-icon><Shield /></n-icon>
          </template>
          信任工具
        </n-button>
        <n-button size="small" type="primary" @click="handleApprove">
          <template #icon>
            <n-icon><CheckmarkCircle /></n-icon>
          </template>
          批准
        </n-button>
      </n-space>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton,
  NCollapse,
  NCollapseItem,
  NIcon,
  NInput,
  NSpace,
  NTag,
  NText,
} from 'naive-ui'
import {
  CheckmarkCircle,
  CloseCircle,
  CreateOutline,
  Shield,
  ShieldCheckmark,
} from '@vicons/ionicons5'
import { useCommand } from '@/composables/useCommand'
import { useRuntimeStore } from '@/stores/runtime'

type ApprovalRequest = Record<string, any>

const runtimeStore = useRuntimeStore()
const commands = useCommand()
const revisionGuidance = ref('')

const requests = computed<ApprovalRequest[]>(() => runtimeStore.currentApprovalRequests)

function requestKey(request: ApprovalRequest, index: number): string {
  return String(request.tool_call_id || request.tool_name || request.name || index)
}

function toolName(request: ApprovalRequest): string {
  return String(request.tool_name || request.tool_id || request.name || '工具调用')
}

function toolSummary(request: ApprovalRequest): string {
  return String(request.summary || request.message || '')
}

function riskLevel(request: ApprovalRequest): string {
  return String(request.risk_level || request.risk || 'standard').toLowerCase()
}

function riskLabel(request: ApprovalRequest): string {
  const level = riskLevel(request)
  const labels: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
    critical: '高风险',
    standard: '需确认',
  }
  return labels[level] || level
}

function riskTagType(request: ApprovalRequest): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const level = riskLevel(request)
  if (level === 'high' || level === 'critical') return 'error'
  if (level === 'medium') return 'warning'
  if (level === 'low') return 'default'
  return 'info'
}

function riskReasons(request: ApprovalRequest): string[] {
  const reasons = request.risk_reasons
  if (!Array.isArray(reasons)) return []
  return reasons.map((reason) => String(reason)).filter(Boolean)
}

function requestArguments(request: ApprovalRequest): Record<string, any> {
  const args = request.args || request.arguments || {}
  return args && typeof args === 'object' && !Array.isArray(args) ? args : {}
}

function hasArguments(request: ApprovalRequest): boolean {
  return Object.keys(requestArguments(request)).length > 0
}

function formatArguments(request: ApprovalRequest): string {
  return JSON.stringify(requestArguments(request), null, 2)
}

function handleApprove() {
  commands.approveToolCall()
}

function handleDeny() {
  commands.denyToolCall()
}

function handleTrust() {
  commands.trustTool()
}

function handleRevise() {
  const guidance = revisionGuidance.value.trim()
  if (!guidance) return
  commands.reviseWithGuidance(guidance)
  revisionGuidance.value = ''
}
</script>

<style scoped>
.tool-approval-panel {
  padding: 14px 16px;
  border: 1px solid #111111;
  border-radius: 6px;
  background: #ffffff;
  color: #111111;
}

.approval-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.approval-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.approval-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.approval-item {
  padding-top: 12px;
  border-top: 1px solid #e5e5e5;
}

.tool-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.tool-summary {
  margin: 8px 0 0;
  color: #333333;
  font-size: 13px;
  line-height: 1.5;
}

.risk-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.risk-reason {
  max-width: 100%;
  padding: 2px 8px;
  border: 1px solid #d9d9d9;
  border-radius: 999px;
  color: #333333;
  font-size: 12px;
  line-height: 1.6;
}

.arguments-collapse {
  margin-top: 8px;
}

.arguments-block {
  margin: 0;
  padding: 10px;
  overflow: auto;
  max-height: 180px;
  border: 1px solid #e5e5e5;
  border-radius: 4px;
  background: #fafafa;
  color: #111111;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.revision-row {
  margin-top: 12px;
}

.approval-actions {
  margin-top: 12px;
}
</style>
