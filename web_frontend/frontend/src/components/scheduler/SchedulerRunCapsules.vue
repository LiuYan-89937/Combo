<template>
  <div v-if="visibleRuns.length" class="scheduler-run-stack">
    <article v-for="run in visibleRuns" :key="run.run_id" class="scheduler-capsule" :class="{ expanded: expandedId === run.run_id }">
      <button class="capsule-summary" type="button" @click="toggle(run)">
        <span class="scheduler-mark" aria-hidden="true">♪</span>
        <span class="summary-copy">
          <strong>{{ runTitle(run) }}</strong>
          <small>{{ executorLabel(run) }} · {{ statusLabel(run.status) }}</small>
        </span>
        <span class="summary-time">{{ elapsed(run) }}</span>
        <span class="summary-chevron">{{ expandedId === run.run_id ? '⌃' : '⌄' }}</span>
      </button>

      <div v-if="expandedId === run.run_id" class="capsule-detail">
        <div v-if="eventsByRun[run.run_id]?.length" class="event-chain">
          <div v-for="event in eventsByRun[run.run_id]" :key="event.sequence" class="event-row">
            <i></i>
            <div>
              <strong>{{ eventTitle(event) }}</strong>
              <pre v-if="eventText(event)">{{ eventText(event) }}</pre>
            </div>
          </div>
        </div>
        <div
          v-if="delivery(run)"
          ref="markdownRoot"
          class="scheduler-delivery markdown-body"
          v-html="renderedDelivery(run)"
        ></div>
        <div v-if="pendingInteraction(run.run_id)" class="interaction-actions">
          <n-input
            v-if="run.status === 'waiting_external'"
            v-model:value="interactionText[run.run_id]"
            size="small"
            :placeholder="t('scheduler.answerPlaceholder')"
          />
          <n-button v-if="run.status === 'waiting_approval'" size="tiny" @click.stop="resolve(run.run_id, 'reject')">{{ t('scheduler.reject') }}</n-button>
          <n-button
            size="tiny"
            type="primary"
            :disabled="run.status === 'waiting_external' && !interactionText[run.run_id]?.trim()"
            @click.stop="resolve(run.run_id, run.status === 'waiting_external' ? 'answer' : 'approve')"
          >{{ run.status === 'waiting_external' ? t('scheduler.answer') : t('scheduler.approve') }}</n-button>
        </div>
        <div class="detail-actions">
          <n-button v-if="isActive(run.status)" size="tiny" @click.stop="cancel(run.run_id)">{{ t('common.cancel') }}</n-button>
          <n-button v-else size="tiny" quaternary @click.stop="dismissed.add(run.run_id)">{{ t('common.close') }}</n-button>
        </div>
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { NButton, NInput } from 'naive-ui'
import { schedulerApi } from '@/api/scheduler'
import type { SchedulerRunEventView, SchedulerRunView } from '@/api/resourceTypes'
import { useI18n } from '@/composables/useI18n'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'

const { t } = useI18n()
const runs = ref<SchedulerRunView[]>([])
const expandedId = ref<string | null>(null)
const eventsByRun = reactive<Record<string, SchedulerRunEventView[]>>({})
const dismissed = reactive(new Set<string>())
const interactionText = reactive<Record<string, string>>({})
const markdownRoot = ref<HTMLElement | null>(null)
const { renderMarkdown } = useMarkdownRenderer(markdownRoot)
let timer: ReturnType<typeof setTimeout> | null = null

const TERMINAL_VISIBILITY_MS = 15 * 60 * 1000
const visibleRuns = computed(() => runs.value.filter(run => {
  if (dismissed.has(run.run_id)) return false
  if (isActive(run.status)) return true
  const terminalAt = Date.parse(run.completed_at || '')
  return Number.isFinite(terminalAt) && Date.now() - terminalAt <= TERMINAL_VISIBILITY_MS
}).slice(0, 6))

onMounted(refresh)
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })

async function refresh(): Promise<void> {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  try {
    const event = await schedulerApi.runs(undefined, 12)
    const payload = event.payload?.payload || event.payload || {}
    runs.value = Array.isArray(payload.runs) ? payload.runs : []
    if (expandedId.value) await loadEvents(expandedId.value)
  } finally {
    timer = setTimeout(refresh, runs.value.some(run => isActive(run.status)) ? 1000 : 4000)
  }
}

async function toggle(run: SchedulerRunView): Promise<void> {
  expandedId.value = expandedId.value === run.run_id ? null : run.run_id
  if (expandedId.value) await loadEvents(run.run_id)
}

async function loadEvents(runId: string): Promise<void> {
  const known = eventsByRun[runId] || []
  const response = await schedulerApi.runEvents(runId, known.at(-1)?.sequence || 0)
  if (response.events.length) eventsByRun[runId] = [...known, ...response.events]
}

async function cancel(runId: string): Promise<void> {
  await schedulerApi.cancelRun(runId)
  await refresh()
}

async function resolve(runId: string, decision: 'approve' | 'reject' | 'answer'): Promise<void> {
  const interaction = pendingInteraction(runId)
  if (!interaction) return
  await schedulerApi.resolveInteraction(runId, interaction.interruptId, decision, interactionText[runId]?.trim())
  interactionText[runId] = ''
  await refresh()
}

function isActive(status: string): boolean {
  return ['queued', 'running', 'waiting_approval', 'waiting_external'].includes(status)
}

function runTitle(run: SchedulerRunView): string {
  return String(run.job_snapshot?.task_content || run.task_content || t('scheduler.title'))
}

function executorLabel(run: SchedulerRunView): string {
  return run.executor_type === 'script' ? t('scheduler.scriptTask') : t('scheduler.agentTask')
}

function statusLabel(status: string): string {
  return t(`scheduler.status.${status}` as any)
}

function elapsed(run: SchedulerRunView): string {
  const start = Date.parse(run.started_at || run.scheduled_at)
  const end = run.completed_at ? Date.parse(run.completed_at) : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function eventTitle(event: SchedulerRunEventView): string {
  const labels: Record<string, string> = {
    run_started: t('scheduler.status.running'),
    agent_queued: t('scheduler.agentQueued'),
    process_started: t('scheduler.processStarted'),
    process_output: t('scheduler.output'),
    result: t('scheduler.result'),
    failed: t('scheduler.status.failed'),
    cancelled: t('scheduler.status.cancelled'),
    tool_activity: String(event.payload.model_alias || event.payload.tool_name || t('scheduler.toolActivity')),
  }
  return labels[event.event_type] || String(event.payload.title || event.payload.summary || event.event_type)
}

function eventText(event: SchedulerRunEventView): string {
  const payload = event.payload
  return String(payload.text || payload.message || payload.summary || payload.stderr || payload.stdout || '').trim()
}

function delivery(run: SchedulerRunView): string {
  const result = run.result || {}
  return String(result.content || result.stdout || run.result_summary || '').trim()
}

function renderedDelivery(run: SchedulerRunView): string {
  return renderMarkdown(delivery(run), { surface: 'chat_message' })
}

function pendingInteraction(runId: string): { interruptId: string } | null {
  const run = runs.value.find(item => item.run_id === runId)
  if (!run || !['waiting_approval', 'waiting_external'].includes(run.status)) return null
  const events = eventsByRun[runId] || []
  const event = [...events].reverse().find(item => ['approval_required', 'question'].includes(item.event_type))
  const interruptId = String(event?.payload.interrupt_id || event?.payload.question_id || event?.payload.id || '').trim()
  return interruptId ? { interruptId } : null
}
</script>

<style scoped>
.scheduler-run-stack { position: fixed; right: 24px; top: 176px; z-index: 32; width: min(420px, calc(100vw - 32px)); display: grid; gap: 10px; }
.scheduler-capsule { overflow: hidden; border: 1px solid var(--app-border); border-radius: 28px; background: var(--app-surface); color: var(--app-text); }
.scheduler-capsule.expanded { border-radius: 24px; }
.capsule-summary { width: 100%; min-height: 68px; display: flex; align-items: center; gap: 12px; padding: 10px 16px; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.scheduler-mark { width: 38px; height: 38px; display: grid; place-items: center; flex: 0 0 38px; border-radius: 50%; background: var(--app-text); color: var(--app-surface); font-size: 24px; }
.summary-copy { display: grid; gap: 4px; min-width: 0; flex: 1; }
.summary-copy strong, .summary-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.summary-copy small, .summary-time { color: var(--app-text-muted); font-size: 12px; }
.summary-chevron { font-size: 16px; }
.capsule-detail { padding: 0 18px 16px 66px; max-height: min(62vh, 620px); overflow: auto; }
.event-chain { display: grid; }
.event-row { position: relative; display: grid; grid-template-columns: 14px 1fr; gap: 10px; padding: 8px 0; }
.event-row::before { content: ''; position: absolute; left: 5px; top: 0; bottom: 0; width: 1px; background: var(--app-border); }
.event-row i { z-index: 1; width: 11px; height: 11px; margin-top: 4px; border-radius: 50%; background: var(--app-text); border: 3px solid var(--app-surface); }
.event-row strong { font-size: 13px; }
.event-row pre { margin: 5px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: 12px; color: var(--app-text-muted); }
.scheduler-delivery { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--app-border); }
.detail-actions { display: flex; justify-content: flex-end; padding-top: 12px; }
.interaction-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding-top: 12px; }
@media (max-width: 720px) { .scheduler-run-stack { right: 12px; top: 112px; } }
</style>
