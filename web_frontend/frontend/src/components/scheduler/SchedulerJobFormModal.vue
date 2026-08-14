<template>
  <n-modal
    v-model:show="show"
    preset="card"
    class="editor-modal-shell scheduler-job-modal"
    :bordered="false"
  >
    <template #header>
      <div class="modal-heading">
        <span class="modal-kicker">{{ t('scheduler.editorKicker') }}</span>
        <h2>{{ t('scheduler.createTitle') }}</h2>
        <p>{{ t('scheduler.createSubtitle') }}</p>
      </div>
    </template>

    <n-form ref="formRef" :model="formData" :rules="rules" label-placement="top" class="scheduler-form">
      <section class="editor-section">
        <div class="section-heading">
          <span class="section-index">01</span>
          <div>
            <h3>{{ t('scheduler.sectionScope') }}</h3>
            <p>{{ t('scheduler.scopeDescription') }}</p>
          </div>
        </div>

        <n-form-item path="workspace_id" :show-label="false" class="section-control">
          <n-select
            v-model:value="formData.workspace_id"
            :options="workspaceOptions"
            :loading="loadingWorkspaces"
            :placeholder="t('scheduler.workspacePlaceholder')"
            size="large"
          />
        </n-form-item>

        <div v-if="!loadingWorkspaces && workspaceOptions.length === 0" class="workspace-empty" role="status">
          <span aria-hidden="true">!</span>
          <div>
            <strong>{{ t('scheduler.workspaceEmptyTitle') }}</strong>
            <p>{{ t('scheduler.workspaceRequiredHint') }}</p>
          </div>
        </div>
      </section>

      <section class="editor-section">
        <div class="section-heading">
          <span class="section-index">02</span>
          <div>
            <h3>{{ t('scheduler.sectionTask') }}</h3>
            <p>{{ t('scheduler.taskTypeDescription') }}</p>
          </div>
        </div>

        <div class="task-type-grid" role="group" :aria-label="t('scheduler.taskType')">
          <button
            type="button"
            class="task-type-option"
            :class="{ selected: formData.task_type === 'agent' }"
            :aria-pressed="formData.task_type === 'agent'"
            @click="formData.task_type = 'agent'"
          >
            <span class="option-mark">A</span>
            <span class="option-copy">
              <strong>{{ t('scheduler.agentTask') }}</strong>
              <small>{{ t('scheduler.agentTaskDescription') }}</small>
            </span>
            <span class="selection-dot" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="task-type-option"
            :class="{ selected: formData.task_type === 'script' }"
            :aria-pressed="formData.task_type === 'script'"
            @click="formData.task_type = 'script'"
          >
            <span class="option-mark">&gt;_</span>
            <span class="option-copy">
              <strong>{{ t('scheduler.scriptTask') }}</strong>
              <small>{{ t('scheduler.scriptTaskDescription') }}</small>
            </span>
            <span class="selection-dot" aria-hidden="true" />
          </button>
        </div>

        <n-form-item
          v-if="formData.task_type === 'agent'"
          :label="t('scheduler.task')"
          path="task_content"
          class="content-editor"
        >
          <n-input
            v-model:value="formData.task_content"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 8 }"
            :placeholder="t('scheduler.taskPlaceholder')"
          />
        </n-form-item>

        <template v-else>
          <div class="field-grid script-fields">
            <n-form-item :label="t('scheduler.interpreter')">
              <n-select v-model:value="formData.interpreter" :options="interpreterOptions" size="large" />
            </n-form-item>
          </div>
          <n-form-item :label="t('scheduler.script')" path="script" class="content-editor code-editor">
            <n-input
              v-model:value="formData.script"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 12 }"
              :placeholder="t('scheduler.scriptPlaceholder')"
            />
          </n-form-item>
        </template>
      </section>

      <section class="editor-section">
        <div class="section-heading">
          <span class="section-index">03</span>
          <div>
            <h3>{{ t('scheduler.sectionRuntime') }}</h3>
            <p>{{ t('scheduler.runtimeDescription') }}</p>
          </div>
        </div>

        <div class="field-grid">
          <div class="runtime-field">
            <n-form-item :label="t('scheduler.strategy')">
              <n-select v-model:value="formData.strategy" :options="strategyOptions" size="large" />
            </n-form-item>
            <p class="control-help">{{ selectedStrategyDescription }}</p>
          </div>
          <div class="runtime-field">
            <n-form-item :label="t('scheduler.unattendedApproval')">
              <n-select v-model:value="formData.approval_policy" :options="approvalOptions" size="large" />
            </n-form-item>
            <p class="control-help">{{ selectedApprovalDescription }}</p>
          </div>
        </div>
      </section>

      <section class="editor-section schedule-section">
        <div class="section-heading">
          <span class="section-index">04</span>
          <div>
            <h3>{{ t('scheduler.sectionSchedule') }}</h3>
            <p>{{ t('scheduler.scheduleDescription') }}</p>
          </div>
          <label class="enable-control">
            <span>
              <strong>{{ t('scheduler.enabled') }}</strong>
              <small>{{ formData.enabled ? t('scheduler.enabledDescription') : t('scheduler.disabledDescription') }}</small>
            </span>
            <n-switch v-model:value="formData.enabled" />
          </label>
        </div>

        <div class="schedule-mode-grid" role="group" :aria-label="t('scheduler.scheduleType')">
          <button
            v-for="option in scheduleModeOptions"
            :key="option.value"
            type="button"
            :class="{ selected: formData.schedule_mode === option.value }"
            :aria-pressed="formData.schedule_mode === option.value"
            @click="formData.schedule_mode = option.value"
          >
            <strong>{{ option.label }}</strong>
            <small>{{ option.description }}</small>
          </button>
        </div>

        <div v-if="formData.schedule_mode === 'recurring'" class="recurrence-editor">
          <n-form-item :label="t('scheduler.recurrencePattern')">
            <n-select
              v-model:value="formData.recurrence_kind"
              :options="recurrenceOptions"
              size="large"
            />
          </n-form-item>

          <n-form-item
            v-if="formData.recurrence_kind === 'daily'"
            :label="t('scheduler.runTime')"
            path="recurrence_time"
          >
            <n-time-picker
              v-model:formatted-value="formData.recurrence_time"
              format="HH:mm"
              value-format="HH:mm"
              size="large"
            />
          </n-form-item>

          <div v-else-if="formData.recurrence_kind === 'weekly'" class="weekly-fields">
            <n-form-item :label="t('scheduler.weekdays')" path="weekdays">
              <n-select
                v-model:value="formData.weekdays"
                :options="weekdayOptions"
                multiple
                size="large"
              />
            </n-form-item>
            <n-form-item :label="t('scheduler.runTime')" path="recurrence_time">
              <n-time-picker
                v-model:formatted-value="formData.recurrence_time"
                format="HH:mm"
                value-format="HH:mm"
                size="large"
              />
            </n-form-item>
          </div>

          <div v-else-if="formData.recurrence_kind === 'interval'" class="interval-fields">
            <n-form-item :label="t('scheduler.intervalValue')" path="interval_value">
              <n-input-number v-model:value="formData.interval_value" :min="1" size="large" />
            </n-form-item>
            <n-form-item :label="t('scheduler.intervalUnit')">
              <n-select v-model:value="formData.interval_unit" :options="intervalUnitOptions" size="large" />
            </n-form-item>
          </div>

          <n-form-item v-else :label="t('scheduler.cron')" path="cron_expression">
            <n-input v-model:value="formData.cron_expression" placeholder="0 9 * * *" size="large" />
          </n-form-item>
        </div>

        <n-form-item v-else :label="t('scheduler.runDate')" path="run_once_at" class="run-once-field">
          <n-date-picker
            v-model:value="formData.run_once_at"
            type="datetime"
            clearable
            size="large"
          />
        </n-form-item>
        <p class="control-help schedule-help">{{ selectedScheduleDescription }}</p>
      </section>
    </n-form>

    <template #footer>
      <div class="modal-footer">
        <p>{{ t('scheduler.createFooterHint') }}</p>
        <div>
          <n-button size="large" @click="show = false">{{ t('common.cancel') }}</n-button>
          <n-button
            type="primary"
            size="large"
            :disabled="workspaceOptions.length === 0"
            @click="handleSubmit"
          >
            {{ t('scheduler.create') }}
          </n-button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NDatePicker, NForm, NFormItem, NInput, NInputNumber, NModal, NSelect, NSwitch, NTimePicker } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { workspaceApi, type WorkspaceProjectView } from '@/api/workspace'
import type { SchedulerJobInput } from '@/api/resourceTypes'
import type { ApprovalMode, ExecutionPreference } from '@/api/dynamicRuntime'
import { useI18n } from '@/composables/useI18n'
import { requiredTextRule } from '@/utils/formValidation'

type ScheduleMode = 'recurring' | 'once'
type RecurrenceKind = 'daily' | 'weekly' | 'interval' | 'cron'
type IntervalUnit = 'minutes' | 'hours' | 'days'
type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'

const INTERVAL_SECONDS: Record<IntervalUnit, number> = {
  minutes: 60,
  hours: 3600,
  days: 86400,
}
const WEEKDAY_ORDER: Weekday[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: SchedulerJobInput]
}>()
const { t } = useI18n()
const formRef = ref<FormInst | null>(null)
const workspaces = ref<WorkspaceProjectView[]>([])
const loadingWorkspaces = ref(false)
const formData = ref(emptyForm())
const show = computed({ get: () => props.show, set: value => emit('update:show', value) })
const workspaceOptions = computed(() => workspaces.value.map(workspace => ({
  label: `${workspace.title} — ${workspace.workdir_root}`,
  value: workspace.workspace_id,
})))
const strategyOptions = computed(() => [
  { label: t('scheduler.strategyFast'), value: 'react' },
  { label: t('scheduler.strategyPlan'), value: 'plan_and_execute' },
])
const approvalOptions = computed(() => [
  { label: t('chat.approvalAuto'), value: 'auto' },
  { label: t('chat.approvalAsk'), value: 'ask' },
  { label: t('chat.approvalAlways'), value: 'always_approval' },
])
const interpreterOptions = computed(() => [
  { label: 'Shell', value: 'shell' },
  { label: 'Python', value: 'python' },
])
const scheduleModeOptions = computed<Array<{ label: string; value: ScheduleMode; description: string }>>(() => [
  { label: t('scheduler.scheduleRecurring'), value: 'recurring', description: t('scheduler.scheduleRecurringDescription') },
  { label: t('scheduler.scheduleDate'), value: 'once', description: t('scheduler.scheduleDateDescription') },
])
const recurrenceOptions = computed<Array<{ label: string; value: RecurrenceKind }>>(() => [
  { label: t('scheduler.recurrenceDaily'), value: 'daily' },
  { label: t('scheduler.recurrenceWeekly'), value: 'weekly' },
  { label: t('scheduler.scheduleInterval'), value: 'interval' },
  { label: t('scheduler.recurrenceAdvanced'), value: 'cron' },
])
const weekdayOptions = computed(() => [
  { label: t('scheduler.weekdayMonday'), value: 'mon' },
  { label: t('scheduler.weekdayTuesday'), value: 'tue' },
  { label: t('scheduler.weekdayWednesday'), value: 'wed' },
  { label: t('scheduler.weekdayThursday'), value: 'thu' },
  { label: t('scheduler.weekdayFriday'), value: 'fri' },
  { label: t('scheduler.weekdaySaturday'), value: 'sat' },
  { label: t('scheduler.weekdaySunday'), value: 'sun' },
])
const intervalUnitOptions = computed<Array<{ label: string; value: IntervalUnit }>>(() => [
  { label: t('scheduler.unitMinutes'), value: 'minutes' },
  { label: t('scheduler.unitHours'), value: 'hours' },
  { label: t('scheduler.unitDays'), value: 'days' },
])
const selectedStrategyDescription = computed(() => formData.value.strategy === 'react'
  ? t('scheduler.strategyFastDescription')
  : t('scheduler.strategyPlanDescription'))
const selectedApprovalDescription = computed(() => ({
  auto: t('scheduler.approvalAutoDescription'),
  ask: t('scheduler.approvalAskDescription'),
  always_approval: t('scheduler.approvalAlwaysDescription'),
}[formData.value.approval_policy]))
const selectedScheduleDescription = computed(() => {
  if (formData.value.schedule_mode === 'once') return t('scheduler.scheduleDateDescription')
  return ({
    daily: t('scheduler.recurrenceDailyDescription'),
    weekly: t('scheduler.recurrenceWeeklyDescription'),
    interval: t('scheduler.scheduleIntervalDescription'),
    cron: t('scheduler.scheduleCronDescription'),
  }[formData.value.recurrence_kind])
})
const rules = computed<FormRules>(() => ({
  workspace_id: [requiredTextRule(t('scheduler.validateWorkspace'))],
  task_content: formData.value.task_type === 'agent' ? [requiredTextRule(t('scheduler.validateTask'))] : [],
  script: formData.value.task_type === 'script' ? [requiredTextRule(t('scheduler.validateScript'))] : [],
  recurrence_time: formData.value.schedule_mode === 'recurring' && ['daily', 'weekly'].includes(formData.value.recurrence_kind)
    ? [requiredTextRule(t('scheduler.validateRunTime'))]
    : [],
  weekdays: formData.value.schedule_mode === 'recurring' && formData.value.recurrence_kind === 'weekly'
    ? [{ type: 'array', required: true, min: 1, message: t('scheduler.validateWeekdays'), trigger: ['blur', 'change'] }]
    : [],
  interval_value: formData.value.schedule_mode === 'recurring' && formData.value.recurrence_kind === 'interval'
    ? [{ type: 'number', required: true, min: 1, message: t('scheduler.validateInterval'), trigger: ['blur', 'change'] }]
    : [],
  cron_expression: formData.value.schedule_mode === 'recurring' && formData.value.recurrence_kind === 'cron'
    ? [requiredTextRule(t('scheduler.validateCron'))]
    : [],
  run_once_at: formData.value.schedule_mode === 'once'
    ? [{ type: 'number', required: true, message: t('scheduler.validateRunDate'), trigger: ['blur', 'change'] }]
    : [],
}))

function emptyForm() {
  return {
    workspace_id: '',
    task_type: 'agent' as 'agent' | 'script',
    task_content: '',
    interpreter: 'shell' as 'shell' | 'python',
    script: '',
    strategy: 'react' as ExecutionPreference,
    approval_policy: 'ask' as ApprovalMode,
    schedule_mode: 'recurring' as ScheduleMode,
    recurrence_kind: 'daily' as RecurrenceKind,
    recurrence_time: '09:00',
    weekdays: ['mon'] as Weekday[],
    interval_value: 1,
    interval_unit: 'hours' as IntervalUnit,
    cron_expression: '0 9 * * *',
    run_once_at: null as number | null,
    enabled: true,
  }
}

function recurringTimeParts(): { hour: number; minute: number } {
  const [hour, minute] = formData.value.recurrence_time.split(':').map(Number)
  return { hour, minute }
}

function serializedSchedule(): { schedule_type: 'cron' | 'interval' | 'date'; schedule_expr: string } {
  if (formData.value.schedule_mode === 'once') {
    return {
      schedule_type: 'date',
      schedule_expr: new Date(formData.value.run_once_at as number).toISOString(),
    }
  }
  if (formData.value.recurrence_kind === 'interval') {
    return {
      schedule_type: 'interval',
      schedule_expr: String(formData.value.interval_value * INTERVAL_SECONDS[formData.value.interval_unit]),
    }
  }
  if (formData.value.recurrence_kind === 'cron') {
    return { schedule_type: 'cron', schedule_expr: formData.value.cron_expression.trim() }
  }
  const { hour, minute } = recurringTimeParts()
  const weekdayExpression = formData.value.recurrence_kind === 'weekly'
    ? formData.value.weekdays.slice().sort(
      (left, right) => WEEKDAY_ORDER.indexOf(left) - WEEKDAY_ORDER.indexOf(right),
    ).join(',')
    : '*'
  return { schedule_type: 'cron', schedule_expr: `${minute} ${hour} * * ${weekdayExpression}` }
}

async function loadWorkspaces(): Promise<void> {
  loadingWorkspaces.value = true
  try {
    workspaces.value = (await workspaceApi.projects()).workspaces
    if (!formData.value.workspace_id && workspaces.value.length === 1) {
      formData.value.workspace_id = workspaces.value[0].workspace_id
    }
  } finally {
    loadingWorkspaces.value = false
  }
}

function handleSubmit(): void {
  void formRef.value?.validate((errors) => {
    if (errors) return
    const agentTask = formData.value.task_type === 'agent'
    const schedule = serializedSchedule()
    emit('submit', {
      workspace_id: formData.value.workspace_id,
      task_content: agentTask ? formData.value.task_content.trim() : formData.value.script.trim(),
      strategy: formData.value.strategy,
      approval_policy: formData.value.approval_policy,
      enabled: formData.value.enabled,
      ...schedule,
      target: agentTask
        ? { target_type: 'graph_run', payload: { message: formData.value.task_content.trim() } }
        : { target_type: 'script_run', payload: { interpreter: formData.value.interpreter, script: formData.value.script.trim() } },
    })
    formData.value = emptyForm()
  })
}

watch(() => props.show, (visible) => {
  if (visible) void loadWorkspaces()
}, { immediate: true })
</script>

<style scoped>
.modal-heading {
  display: grid;
  gap: 5px;
  padding: 3px 0 2px;
}

.modal-kicker {
  color: var(--app-text-muted);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .16em;
  text-transform: uppercase;
}

.modal-heading h2 {
  margin: 0;
  color: var(--app-text-strong);
  font-size: 25px;
  letter-spacing: -.035em;
}

.modal-heading p,
.section-heading p,
.workspace-empty p,
.modal-footer p {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: 11px;
  line-height: 1.55;
}

.scheduler-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  gap: 12px;
}

.editor-section {
  height: 100%;
  padding: 18px;
  border: 1px solid var(--app-border);
  border-radius: 18px;
  background: var(--app-surface);
}

.section-heading {
  display: grid;
  grid-template-columns: 29px minmax(0, 1fr);
  align-items: start;
  gap: 11px;
  margin-bottom: 16px;
}

.section-index {
  display: grid;
  width: 29px;
  height: 29px;
  place-items: center;
  color: var(--app-surface);
  border-radius: 10px;
  background: var(--app-text);
  font-size: 9px;
  font-weight: 800;
}

.section-heading h3 {
  margin: 1px 0 3px;
  color: var(--app-text-strong);
  font-size: 14px;
  letter-spacing: -.01em;
}

.section-control,
.content-editor,
.schedule-expression {
  margin-bottom: 0;
}

.workspace-empty {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  align-items: center;
  gap: 11px;
  margin-top: 10px;
  padding: 12px;
  color: var(--app-surface);
  border-radius: 13px;
  background: var(--app-text);
}

.workspace-empty > span {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 13px;
  font-weight: 800;
}

.workspace-empty strong {
  display: block;
  margin-bottom: 2px;
  font-size: 11px;
}

.workspace-empty p {
  color: var(--app-surface);
}

.task-type-grid,
.schedule-mode-grid {
  display: grid;
  gap: 9px;
}

.task-type-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 17px;
}

.task-type-option {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 12px;
  align-items: center;
  gap: 11px;
  min-height: 76px;
  padding: 13px;
  color: var(--app-text);
  text-align: left;
  border: 1px solid var(--app-border);
  border-radius: 15px;
  background: var(--app-surface);
  cursor: pointer;
  transition: border-color .16s ease, background .16s ease, color .16s ease;
}

.task-type-option:hover,
.task-type-option:focus-visible {
  border-color: var(--app-text);
  outline: none;
}

.task-type-option.selected {
  color: var(--app-surface);
  border-color: var(--app-text);
  background: var(--app-text);
}

.option-mark {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 800;
}

.option-copy {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.option-copy strong {
  font-size: 12px;
}

.option-copy small {
  overflow: hidden;
  color: inherit;
  font-size: 10px;
  opacity: .78;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selection-dot {
  width: 8px;
  height: 8px;
  border: 1px solid currentColor;
  border-radius: 50%;
}

.selected .selection-dot {
  background: currentColor;
  box-shadow: inset 0 0 0 2px var(--app-text);
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.script-fields {
  grid-template-columns: minmax(0, 220px);
}

.field-grid :deep(.n-form-item),
.content-editor :deep(.n-form-item) {
  min-width: 0;
}

.runtime-field :deep(.n-form-item) {
  margin-bottom: 0;
}

.control-help {
  margin: 5px 1px 0;
  color: var(--app-text-muted);
  font-size: 9px;
  line-height: 1.5;
}

.code-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
}

.schedule-section .section-heading {
  grid-template-columns: 29px minmax(0, 1fr) auto;
}

.enable-control {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-left: 16px;
  border-left: 1px solid var(--app-border);
  cursor: pointer;
}

.enable-control > span {
  display: grid;
  gap: 2px;
}

.enable-control strong,
.enable-control small {
  white-space: nowrap;
}

.enable-control strong {
  font-size: 11px;
}

.enable-control small {
  color: var(--app-text-secondary);
  font-size: 9px;
}

.schedule-mode-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 15px;
}

.schedule-mode-grid button {
  display: grid;
  min-height: 64px;
  gap: 4px;
  padding: 11px 12px;
  color: var(--app-text);
  text-align: left;
  border: 1px solid var(--app-border);
  border-radius: 13px;
  background: var(--app-surface);
  cursor: pointer;
  transition: border-color .16s ease, background .16s ease, color .16s ease;
}

.schedule-mode-grid button:hover,
.schedule-mode-grid button:focus-visible {
  border-color: var(--app-text);
  outline: none;
}

.schedule-mode-grid button.selected {
  color: var(--app-surface);
  border-color: var(--app-text);
  background: var(--app-text);
}

.schedule-mode-grid strong {
  font-size: 11px;
}

.schedule-mode-grid small {
  color: inherit;
  font-size: 9px;
  opacity: .78;
}

.recurrence-editor {
  display: grid;
  grid-template-columns: minmax(0, .78fr) minmax(0, 1.22fr);
  gap: 14px;
}

.recurrence-editor > :deep(.n-form-item),
.weekly-fields :deep(.n-form-item),
.interval-fields :deep(.n-form-item) {
  min-width: 0;
  margin-bottom: 0;
}

.weekly-fields,
.interval-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(120px, .55fr);
  gap: 10px;
}

.recurrence-editor :deep(.n-time-picker),
.interval-fields :deep(.n-input-number),
.run-once-field :deep(.n-date-picker) {
  width: 100%;
}

.schedule-help {
  margin-top: -3px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.modal-footer p {
  max-width: 380px;
}

.modal-footer > div {
  display: flex;
  flex: none;
  gap: 8px;
}

:global(.scheduler-job-modal.n-card) {
  --editor-modal-width: 1120px;
  overflow: hidden;
  border-radius: 24px;
  background: var(--app-surface);
}

:global(.scheduler-job-modal .n-card-header) {
  padding: 24px 26px 18px;
  border-bottom: 1px solid var(--app-border);
}

:global(.scheduler-job-modal .n-card-content) {
  max-height: none;
  padding: 20px 26px;
  overflow-y: auto;
}

:global(.scheduler-job-modal .n-card__footer) {
  padding: 16px 26px 20px;
  border-top: 1px solid var(--app-border);
}

:global(.scheduler-job-modal .n-card-header__close) {
  align-self: flex-start;
  margin-top: 2px;
}

@media (max-width: 640px) {
  .scheduler-form,
  .task-type-grid,
  .field-grid,
  .schedule-mode-grid,
  .recurrence-editor,
  .weekly-fields,
  .interval-fields {
    grid-template-columns: 1fr;
  }

  .schedule-section .section-heading {
    grid-template-columns: 29px minmax(0, 1fr);
  }

  .enable-control {
    grid-column: 2;
    justify-content: space-between;
    margin-top: 8px;
    padding: 10px 0 0;
    border-top: 1px solid var(--app-border);
    border-left: 0;
  }

  .modal-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .modal-footer > div,
  .modal-footer .n-button {
    flex: 1;
  }

  :global(.scheduler-job-modal .n-card-header),
  :global(.scheduler-job-modal .n-card-content),
  :global(.scheduler-job-modal .n-card__footer) {
    padding-right: 18px;
    padding-left: 18px;
  }
}
</style>
