<template>
  <details
    class="tool-execution-card"
    :class="[`tool-state-${state}`]"
    :open="cardExpanded"
    @toggle="handleCardToggle"
  >
    <summary class="tool-summary">
      <span class="tool-main">
        <span class="tool-icon-shell" :class="`tool-category-${presentation.category}`">
          <img
            v-if="applicationIconDataUrl"
            class="tool-application-icon"
            :src="applicationIconDataUrl"
            :alt="applicationDisplayName || displayName"
          />
          <ToolIcon v-else :name="presentation.icon" />
        </span>
        <span class="tool-copy">
          <span class="tool-copy-line">
            <strong>{{ summaryTitle }}</strong>
            <span v-if="changeFileName" class="tool-change-path" :title="changePath">{{ changeFileName }}</span>
            <b v-if="displayTotals.added" class="tool-change-added">+{{ displayTotals.added }}</b>
            <i v-if="displayTotals.removed" class="tool-change-removed">-{{ displayTotals.removed }}</i>
          </span>
          <span v-if="secondaryText" class="tool-summary-text">{{ secondaryText }}</span>
        </span>
      </span>
      <span class="tool-side">
        <span v-if="durationLabel" class="tool-duration">{{ durationLabel }}</span>
        <span v-if="state === 'failed'" class="tool-report-action" @click.stop @keydown.stop>
          <ErrorReportButton
            :summary="errorSummary"
            :error-code="errorMetadata.code"
            :request-id="errorMetadata.requestId"
            :diagnostic-ref="errorMetadata.diagnosticRef"
            :context="{ tool_name: part.toolName, call_id: part.callId || '' }"
            size="tiny"
            type="error"
          />
        </span>
        <span v-if="showStatusLabel" class="tool-status">{{ statusLabel }}</span>
        <span class="summary-chevron" aria-hidden="true">⌄</span>
      </span>
    </summary>

    <div v-if="cardExpanded" class="tool-body">
      <div v-if="resultFacts.length" class="tool-facts">
        <span v-for="fact in resultFacts" :key="fact">{{ fact }}</span>
      </div>

      <div v-if="editDiffRows.length" class="tool-diff">
        <div class="tool-diff-header">
          <ResourceIcon :name="diffFilePath" kind="file" :size="16" />
          <span class="tool-diff-path" :title="diffFilePath">{{ diffFilePath }}</span>
          <span class="tool-diff-total">
            <b v-if="editDiffTotals.added">+{{ editDiffTotals.added }}</b>
            <i v-if="editDiffTotals.removed">-{{ editDiffTotals.removed }}</i>
          </span>
        </div>
        <div class="tool-diff-body">
          <div
            v-for="(row, index) in visibleDiffRows"
            :key="`${index}:${row.lineNumber}:${row.kind}`"
            class="tool-diff-row"
            :class="`tool-diff-${row.kind}`"
          >
            <span class="tool-diff-gutter">{{ row.lineNumber }}</span>
            <span class="tool-diff-marker" aria-hidden="true" />
            <code class="tool-diff-text">{{ row.text || ' ' }}</code>
          </div>
        </div>
        <p v-if="diffTruncated" class="tool-diff-truncated">
          {{ t('tool.diff.truncated', { count: editDiffRows.length - visibleDiffRows.length }) }}
        </p>
      </div>

      <div v-if="changedFiles.length" class="structured-results transaction-results">
        <div
          v-for="file in changedFiles"
          :key="`${file.changeType}:${file.path}`"
          class="transaction-file"
        >
          <ResourceIcon :name="file.path" kind="file" :size="18" />
          <span class="transaction-file-path" :title="file.path">{{ file.path }}</span>
          <span class="transaction-change" :class="`transaction-change-${file.changeType}`">
            {{ transactionChangeLabel(file.changeType) }}
          </span>
          <span class="transaction-lines">
            <b v-if="file.added">+{{ file.added }}</b>
            <i v-if="file.removed">-{{ file.removed }}</i>
          </span>
        </div>
      </div>

      <div v-else-if="grepMatches.length" class="structured-results grep-results">
        <div v-for="match in grepMatches" :key="`${match.path}:${match.line_number}`" class="grep-result">
          <strong>{{ match.path }}:{{ match.line_number }}</strong>
          <code>{{ match.line }}</code>
        </div>
      </div>

      <div v-else-if="workspaceEntries.length" class="structured-results entry-results">
        <a
          v-for="entry in workspaceEntries"
          :key="`${entry.type}:${entry.path}`"
          :href="workspacePathUrl(entry.path, entry.type) || undefined"
          :target="workspacePathUrl(entry.path, entry.type) ? '_blank' : undefined"
          :rel="workspacePathUrl(entry.path, entry.type) ? 'noopener noreferrer' : undefined"
          @click="preventUnavailablePath($event, entry.path, entry.type)"
        >
          <ResourceIcon
            :name="entry.name || entry.path"
            :kind="entry.type"
            :size="18"
          />
          <span>{{ entry.path }}</span>
        </a>
      </div>

      <div v-if="shellOutput" class="structured-results shell-output">
        <pre ref="shellOutputElement" @scroll="handleShellOutputScroll">{{ shellOutput }}</pre>
      </div>

      <details
        v-if="hasArguments"
        class="tool-section"
        :open="argumentsExpanded"
        @toggle="handleArgumentsToggle"
      >
        <summary>{{ t('tool.arguments') }}</summary>
        <pre v-if="argumentsExpanded">{{ formattedArguments }}</pre>
      </details>

      <details
        v-if="hasOutput || part.error"
        class="tool-section"
        :open="outputExpanded"
        @toggle="handleOutputToggle"
      >
        <summary>{{ state === 'failed' ? t('common.error') : t('tool.result') }}</summary>
        <pre v-if="outputExpanded">{{ formattedOutput }}</pre>
      </details>

      <div v-if="part.artifacts.length" class="tool-artifacts">
        <a
          v-for="artifact in part.artifacts"
          :key="artifact.id"
          class="tool-artifact"
          :class="{ 'tool-artifact-image': isImageArtifact(artifact) }"
          :href="artifactUrl(artifact)"
          :target="artifactUrl(artifact) ? '_blank' : undefined"
          :rel="artifactUrl(artifact) ? 'noopener noreferrer' : undefined"
          @click="preventUnavailableArtifact($event, artifact)"
        >
          <img
            v-if="isImageArtifact(artifact) && artifactUrl(artifact)"
            class="tool-artifact-preview"
            :src="artifactUrl(artifact)"
            :alt="artifact.name"
          />
          <ResourceIcon
            v-else
            :name="artifact.name"
            :mime-type="artifact.mimeType"
            :size="22"
          />
          <span class="tool-artifact-details">
            <strong>{{ artifact.name }}</strong>
            <small>{{ artifactMeta(artifact) }}</small>
          </span>
        </a>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import ToolIcon from '@/components/common/ToolIcon.vue'
import ErrorReportButton from '@/components/common/ErrorReportButton.vue'
import { useI18n } from '@/composables/useI18n'
import { useAutoExpandedDetails } from '@/composables/useAutoExpandedDetails'
import { useWorkspaceResourceUrls } from '@/composables/useWorkspaceResourceUrls'
import { isImageResource, workspaceResourceUrl } from '@/utils/workspaceResources'
import { toolPresentation } from '@/utils/toolPresentation'
import { buildUnifiedDiff, type UnifiedDiffRow } from '@/utils/unifiedDiff'
import { isRuntimeCancellation } from '@/utils/runtimeCancellation'
import type {
  ArtifactMessagePart,
  ToolExecutionMessagePart,
} from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'

const props = withDefaults(defineProps<{
  part: ToolExecutionMessagePart
  workspaceContext?: WorkspaceRequestContext | null
}>(), {
  workspaceContext: null,
})

interface ChangedFile {
  path: string
  name: string
  changeType: string
  added: number
  removed: number
}

/** Tools that rewrite one file and therefore always report a target path. */
const WRITE_TOOL_NAMES = new Set(['edit', 'write'])

/** Long edits are capped so a huge rewrite cannot flood the transcript. */
const MAX_DIFF_ROWS = 200

const { t } = useI18n()
const presentation = computed(() => toolPresentation(props.part.toolName, props.part.arguments))
const displayName = computed(() => (
  presentation.value.labelKey ? t(presentation.value.labelKey as any) : props.part.toolName
))
const summaryText = computed(() => (
  applicationDisplayName.value
  || (presentation.value.summaryKey
    ? t(presentation.value.summaryKey as any)
    : presentation.value.summary)
))
const state = computed(() => {
  if (props.part.status === 'cancelled' || isRuntimeCancellation(props.part)) return 'cancelled'
  if (props.part.error || props.part.status === 'failed') return 'failed'
  if (props.part.status === 'awaiting_approval') return 'approval'
  if (['running', 'streaming', 'requested'].includes(String(props.part.status || ''))) return 'running'
  return 'completed'
})
const active = computed(() => state.value === 'running' || state.value === 'approval')

// The card body and its argument/result sections mount only while expanded:
// content rendered inside a collapsed `<details>` can come back blank until the
// section is toggled again, which is what made arguments/results look empty.
const cardAutoExpanded = computed(() => active.value || state.value === 'failed')
const { expanded: cardExpanded, handleToggle: handleCardToggle } = useAutoExpandedDetails(cardAutoExpanded)
const { expanded: argumentsExpanded, handleToggle: handleArgumentsToggle } = useAutoExpandedDetails(computed(() => false))
const { expanded: outputExpanded, handleToggle: handleOutputToggle } = useAutoExpandedDetails(computed(() => state.value === 'failed'))
const statusLabel = computed(() => {
  if (state.value === 'cancelled') return t('tool.status.cancelled')
  if (state.value === 'failed') return t('tool.status.failed')
  if (state.value === 'approval') return t('tool.status.waitingApproval')
  if (state.value === 'running') {
    return presentation.value.activeLabelKey
      ? t(presentation.value.activeLabelKey as any)
      : t('tool.status.started')
  }
  if (resultRecord.value?.status === 'preview_ready') return t('tool.transaction.previewReady')
  if (resultRecord.value?.status === 'committed') return t('tool.transaction.committed')
  return t('tool.status.completed')
})
const showStatusLabel = computed(() => (
  state.value !== 'completed'
  || ['preview_ready', 'committed'].includes(String(resultRecord.value?.status || ''))
))
const formattedArguments = computed(() => valueString(props.part.arguments))
const argumentRecord = computed<Record<string, any> | null>(() => {
  const value = props.part.arguments
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null
})
const formattedOutput = computed(() => valueString(props.part.error || displayOutput(props.part.output)))
const hasArguments = computed(() => hasValue(props.part.arguments))
const hasOutput = computed(() => hasValue(props.part.output))
const errorRecord = computed<Record<string, any>>(() => (
  props.part.error && typeof props.part.error === 'object' && !Array.isArray(props.part.error)
    ? props.part.error as Record<string, any>
    : {}
))
const errorMetadata = computed(() => ({
  code: String(errorRecord.value.code || ''),
  requestId: String(errorRecord.value.request_id || ''),
  diagnosticRef: String(errorRecord.value.diagnostic_ref || ''),
}))
const errorSummary = computed(() => {
  const message = errorRecord.value.message || errorRecord.value.detail || props.part.error
  return `${displayName.value}: ${valueString(message) || t('tool.status.failed')}`
})
const clockMs = ref(Date.now())
const timingActive = computed(() => (
  state.value === 'running'
  && Number.isFinite(Date.parse(String(props.part.startedAt || '')))
))
let clockTimer: ReturnType<typeof setInterval> | null = null

watch(timingActive, (active) => {
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  if (!active) return
  clockMs.value = Date.now()
  clockTimer = setInterval(() => {
    clockMs.value = Date.now()
  }, 200)
}, { immediate: true })

onBeforeUnmount(() => {
  if (clockTimer) clearInterval(clockTimer)
})

const durationMs = computed(() => {
  const startedAt = Date.parse(String(props.part.startedAt || ''))
  const completedAt = timingActive.value
    ? clockMs.value
    : Date.parse(String(props.part.completedAt || ''))
  return Number.isFinite(startedAt) && Number.isFinite(completedAt) && completedAt >= startedAt
    ? completedAt - startedAt
    : null
})
const durationLabel = computed(() => {
  const value = durationMs.value
  if (value == null) return ''
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`
})
const resultRecord = computed<Record<string, any> | null>(() => {
  const value = props.part.output
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, any>
  return record.output && typeof record.output === 'object' && !Array.isArray(record.output)
    ? record.output as Record<string, any>
    : record
})
const applicationRecord = computed<Record<string, any> | null>(() => {
  const application = resultRecord.value?.application
  return application && typeof application === 'object' && !Array.isArray(application)
    ? application as Record<string, any>
    : null
})
const applicationIconDataUrl = computed(() => {
  const value = String(applicationRecord.value?.icon_data_url || '').trim()
  return value.startsWith('data:image/') ? value : ''
})
const applicationDisplayName = computed(() => (
  String(applicationRecord.value?.display_name || '').trim()
))
const resultFacts = computed(() => {
  const result = resultRecord.value
  if (!result) return []
  const facts: string[] = []
  const matches = Array.isArray(result.matches) ? result.matches.length : null
  const entries = Array.isArray(result.entries) ? result.entries.length : null
  if (matches !== null) facts.push(t('tool.fact.matches', { count: matches }))
  if (entries !== null) facts.push(t('tool.fact.entries', { count: entries }))
  // The summary line already reports added/removed lines for files we can name,
  // so the raw replacement/byte counters would only repeat it.
  const hasFileChanges = changedFiles.value.length > 0
  if (!hasFileChanges && typeof result.replacements === 'number') {
    facts.push(t('tool.fact.replacements', { count: result.replacements }))
  }
  if (!hasFileChanges && typeof result.bytes_written === 'number') {
    facts.push(t('tool.fact.bytesWritten', { count: result.bytes_written }))
  }
  if (typeof result.operations_count === 'number') {
    facts.push(t('tool.fact.operations', { count: result.operations_count }))
  }
  if (typeof result.exit_code === 'number') facts.push(t('tool.fact.exitCode', { code: result.exit_code }))
  if (result.truncated === true || result.stdout_truncated === true || result.stderr_truncated === true) {
    facts.push(t('tool.fact.truncated'))
  }
  return facts
})
const changedFiles = computed<ChangedFile[]>(() => {
  const result = resultRecord.value
  if (!result) return []
  const affected = result.affected_files
  if (Array.isArray(affected)) {
    return affected
      .filter(file => (
        file
        && typeof file === 'object'
        && typeof file.path === 'string'
        && ['created', 'modified', 'deleted'].includes(String(file.change_type || ''))
      ))
      .map(file => normalizeChangedFile(
        String(file.path),
        String(file.change_type || 'modified'),
        file.change_summary,
      ))
  }
  // Single-file tools (edit / write_once) report the target path and its diff
  // directly instead of an affected_files list.
  const path = String(result.path || '').trim()
  if (path && result.change_summary && typeof result.change_summary === 'object') {
    const changeType = result.created === true ? 'created' : 'modified'
    return [normalizeChangedFile(path, changeType, result.change_summary)]
  }
  // The result payload may still be in flight or compressed away. Fall back to
  // the requested target so the touched file is always named on write tools.
  const requested = String(argumentRecord.value?.path || '').trim()
  if (!WRITE_TOOL_NAMES.has(props.part.toolName) || !requested) return []
  return [normalizeChangedFile(requested, 'modified', null)]
})
const changeTotals = computed(() => changedFiles.value.reduce(
  (totals, file) => ({ added: totals.added + file.added, removed: totals.removed + file.removed }),
  { added: 0, removed: 0 },
))
// The edit tool only reports the swapped snippet, so its real content change is
// rebuilt here from the old/new text the model actually sent.
const editDiffRows = computed<UnifiedDiffRow[]>(() => {
  if (props.part.toolName !== 'edit') return []
  const oldText = typeof argumentRecord.value?.old_text === 'string' ? argumentRecord.value.old_text : ''
  const newText = typeof argumentRecord.value?.new_text === 'string' ? argumentRecord.value.new_text : ''
  if (!oldText && !newText) return []
  return buildUnifiedDiff(oldText, newText)
})
const editDiffTotals = computed(() => editDiffRows.value.reduce(
  (totals, row) => {
    if (row.kind === 'added') totals.added += 1
    else if (row.kind === 'removed') totals.removed += 1
    return totals
  },
  { added: 0, removed: 0 },
))
const displayTotals = computed(() => (
  changeTotals.value.added || changeTotals.value.removed ? changeTotals.value : editDiffTotals.value
))
const visibleDiffRows = computed(() => editDiffRows.value.slice(0, MAX_DIFF_ROWS))
const diffTruncated = computed(() => editDiffRows.value.length > MAX_DIFF_ROWS)
const diffFilePath = computed(() => changePath.value || String(argumentRecord.value?.path || '').trim())
// `已编辑` / `已新建` / `已删除`, or a file count when a transaction touched many.
const changeAction = computed(() => {
  const files = changedFiles.value
  if (!files.length) return ''
  if (files.length > 1) return t('tool.change.editedFiles', { count: files.length })
  const key = files[0].changeType === 'created'
    ? 'tool.change.created'
    : files[0].changeType === 'deleted'
      ? 'tool.change.deleted'
      : 'tool.change.edited'
  return t(key as any)
})
// A file change says more about what happened than the generic tool name, so the
// action leads the summary and the touched file keeps its own underlined span.
const changeFileName = computed(() => (changedFiles.value.length === 1 ? changedFiles.value[0].name : ''))
const summaryTitle = computed(() => changeAction.value || displayName.value)
const secondaryText = computed(() => summaryText.value)
const changePath = computed(() => changedFiles.value[0]?.path || '')
const grepMatches = computed<Array<Record<string, any>>>(() => {
  const matches = resultRecord.value?.matches
  if (!Array.isArray(matches) || !matches.some(item => item && typeof item.line_number === 'number')) return []
  return matches.filter(item => item && typeof item === 'object').slice(0, 30)
})
const workspaceEntries = computed<Array<Record<string, any>>>(() => {
  const result = resultRecord.value
  const values = Array.isArray(result?.entries)
    ? result.entries
    : Array.isArray(result?.matches) && grepMatches.value.length === 0
      ? result.matches
      : []
  return values.filter(item => item && typeof item === 'object' && item.path).slice(0, 30)
})
const workspaceContext = computed(() => props.workspaceContext)
const protectedResourceSources = computed(() => props.part.artifacts
  .filter(artifact => isImageArtifact(artifact))
  .map(artifact => String(artifact.path || '').trim())
  .filter(Boolean))
const protectedResources = useWorkspaceResourceUrls(protectedResourceSources, workspaceContext)
const shellOutput = computed(() => {
  if (presentation.value.category !== 'process') return ''
  const stdout = String(resultRecord.value?.stdout || '').trim()
  const stderr = String(resultRecord.value?.stderr || '').trim()
  return [stdout, stderr].filter(Boolean).join('\n')
})
const shellOutputElement = ref<HTMLElement | null>(null)
const shellOutputPinned = ref(true)

watch(shellOutput, async () => {
  await nextTick()
  const element = shellOutputElement.value
  if (!element || !shellOutputPinned.value) return
  element.scrollTop = element.scrollHeight
})

function handleShellOutputScroll() {
  const element = shellOutputElement.value
  if (!element) return
  shellOutputPinned.value = element.scrollHeight - element.scrollTop - element.clientHeight < 24
}

function artifactUrl(artifact: ArtifactMessagePart): string {
  return artifact.path ? protectedResources.resolve(artifact.path) || '' : ''
}

function isImageArtifact(artifact: ArtifactMessagePart): boolean {
  return isImageResource(artifact.path || artifact.name, artifact.mimeType)
}

function workspacePathUrl(path: unknown, kind?: unknown): string {
  if (String(kind || '') === 'directory') return ''
  const value = String(path || '').trim()
  return value ? workspaceResourceUrl(value, props.workspaceContext) || '' : ''
}

function preventUnavailablePath(event: MouseEvent, path: unknown, kind?: unknown) {
  if (!workspacePathUrl(path, kind)) event.preventDefault()
}

function preventUnavailableArtifact(event: MouseEvent, artifact: ArtifactMessagePart) {
  if (!artifactUrl(artifact)) event.preventDefault()
}

function normalizeChangedFile(path: string, changeType: string, summary: unknown): ChangedFile {
  const record = summary && typeof summary === 'object' && !Array.isArray(summary)
    ? summary as Record<string, any>
    : {}
  return {
    path,
    name: path.split(/[\\/]/).pop() || path,
    changeType,
    added: Number(record.added_lines) || 0,
    removed: Number(record.removed_lines) || 0,
  }
}

function transactionChangeLabel(changeType: unknown): string {
  const key = {
    created: 'tool.transaction.created',
    modified: 'tool.transaction.modified',
    deleted: 'tool.transaction.deleted',
  }[String(changeType || '')] as
    | 'tool.transaction.created'
    | 'tool.transaction.modified'
    | 'tool.transaction.deleted'
    | undefined
  return key ? t(key) : String(changeType || '')
}

function artifactMeta(artifact: ArtifactMessagePart): string {
  const values = [
    artifact.mimeType,
    typeof artifact.sizeBytes === 'number' ? formatFileSize(artifact.sizeBytes) : null,
  ].filter(Boolean)
  return values.join(' · ')
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function hasValue(value: unknown): boolean {
  if (value == null || value === '') return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0
  return true
}

function valueString(value: unknown): string {
  if (value == null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || String(value)
}

function displayOutput(value: unknown): unknown {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value
  const result = value as Record<string, any>
  const application = result.application
  if (!application || typeof application !== 'object' || Array.isArray(application)) return value
  const { icon_data_url: _iconDataUrl, ...visibleApplication } = application as Record<string, any>
  return { ...result, application: visibleApplication }
}
</script>

<style scoped>
.tool-execution-card {
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--app-info) 24%, var(--app-border));
  border-radius: var(--app-radius-lg);
  background: color-mix(in srgb, var(--app-info) 4%, var(--app-surface));
}

.tool-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: 7px 10px;
  cursor: pointer;
  user-select: none;
}

.tool-main,
.tool-side {
  display: flex;
  align-items: center;
  min-width: 0;
}

.tool-main {
  gap: 8px;
}

.tool-side {
  flex: 0 0 auto;
  gap: var(--app-space-sm);
}

.tool-icon-shell {
  display: grid;
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  place-items: center;
  background: transparent;
  color: var(--app-text);
}

.tool-state-completed .tool-icon-shell {
  background: transparent;
  color: var(--app-text);
}

.tool-state-failed .tool-icon-shell {
  background: transparent;
  color: var(--app-error);
}

.tool-icon-shell :deep(.n-icon) {
  display: flex;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  align-items: center;
  justify-content: center;
}

.tool-icon-shell :deep(svg) {
  display: block;
  width: 18px;
  height: 18px;
}

.tool-application-icon {
  display: block;
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.tool-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.tool-copy-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.tool-copy strong,
.tool-summary-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-copy strong {
  min-width: 0;
  font-size: 13px;
}

.tool-change-added,
.tool-change-removed {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 600;
  font-style: normal;
}

.tool-change-path {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text);
  text-decoration: underline dotted;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  text-decoration-color: color-mix(in srgb, var(--app-text) 40%, transparent);
}

.tool-change-added {
  color: var(--app-diff-addition);
}

.tool-change-removed {
  color: var(--app-diff-deletion);
}

/* Inline content diff for the edit tool: shows the actual added/removed lines
   instead of only the tool name. */
.tool-diff {
  margin: var(--app-space-xs, 8px) var(--app-space-sm, 12px) 0;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.tool-diff-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface-muted);
}

.tool-diff-path {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-family: var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-diff-total {
  flex: none;
  display: inline-flex;
  gap: 6px;
  font: 10px/1 var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
}

.tool-diff-total b { color: var(--app-diff-addition); }
.tool-diff-total i { color: var(--app-diff-deletion); font-style: normal; }

.tool-diff-body {
  max-height: min(46vh, 420px);
  overflow: auto;
  overscroll-behavior: contain;
}

.tool-diff-row {
  display: grid;
  grid-template-columns: 38px 14px minmax(0, 1fr);
  align-items: baseline;
  font-family: var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 11px;
  line-height: 1.65;
}

.tool-diff-gutter {
  padding-right: 8px;
  color: var(--app-text-subtle);
  text-align: right;
  font-variant-numeric: tabular-nums;
  user-select: none;
}

.tool-diff-marker { user-select: none; }

.tool-diff-text {
  min-width: 0;
  padding-right: 10px;
  color: var(--app-text);
  font: inherit;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.tool-diff-added { background: var(--app-diff-addition-surface); }
.tool-diff-removed { background: var(--app-diff-deletion-surface); }

.tool-diff-added .tool-diff-marker::before {
  content: '+';
  color: var(--app-diff-addition);
  font-weight: 700;
}

.tool-diff-removed .tool-diff-marker::before {
  content: '−';
  color: var(--app-diff-deletion);
  font-weight: 700;
}

.tool-diff-context .tool-diff-text { color: var(--app-text-secondary); }

.tool-diff-truncated {
  margin: 0;
  padding: 7px 10px;
  border-top: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 10px;
}

.tool-summary-text,
.tool-duration {
  color: var(--app-text-muted);
  font-size: 11px;
}

.tool-status {
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.summary-chevron {
  color: var(--app-text-subtle);
  transition: transform var(--app-transition-base);
}

details[open] > summary .summary-chevron {
  transform: rotate(180deg);
}

.tool-body {
  border-top: 1px solid var(--app-border);
  background: var(--app-surface);
}

.tool-report-action {
  display: inline-flex;
  align-items: center;
}

.tool-facts,
.tool-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
}

.tool-facts span {
  padding: 3px 8px;
  border-radius: var(--app-radius-pill);
  background: var(--app-surface-muted);
  color: var(--app-text-muted);
  font-size: 11px;
}

.tool-section {
  border-top: 1px solid var(--app-divider);
}

.structured-results {
  border-top: 1px solid var(--app-divider);
  padding: var(--app-space-sm) var(--app-space-md);
}

.grep-results,
.entry-results,
.transaction-results {
  display: grid;
  gap: 6px;
  max-height: 320px;
  overflow: auto;
}

.transaction-file {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--app-space-sm);
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-muted);
}

.transaction-file-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transaction-change {
  padding: 2px 7px;
  border-radius: var(--app-radius-pill);
  color: var(--app-text-muted);
  font-size: 11px;
}

.transaction-change-created {
  background: color-mix(in srgb, var(--app-success) 14%, transparent);
  color: var(--app-success);
}

.transaction-change-modified {
  background: color-mix(in srgb, var(--app-info) 14%, transparent);
  color: var(--app-info);
}

.transaction-change-deleted {
  background: color-mix(in srgb, var(--app-error) 12%, transparent);
  color: var(--app-error);
}

.transaction-lines {
  display: flex;
  gap: 5px;
  min-width: 44px;
  justify-content: flex-end;
  font-size: 11px;
  font-style: normal;
}

.transaction-lines b {
  color: var(--app-success);
}

.transaction-lines i {
  color: var(--app-error);
  font-style: normal;
}

.grep-result {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-muted);
}

.grep-result strong {
  overflow: hidden;
  color: var(--app-info);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grep-result code {
  overflow: hidden;
  color: var(--app-text);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-results a {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--app-space-sm);
  padding: 5px 7px;
  border-radius: var(--app-radius-sm);
  color: var(--app-text);
  text-decoration: none;
}

.entry-results a:hover {
  background: var(--app-surface-muted);
}

.entry-results span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shell-output pre {
  max-height: 320px;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text);
  font-size: 12px;
}

.tool-section summary {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px var(--app-space-md);
  color: var(--app-text-muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  list-style: none;
  transition: background-color var(--app-transition-fast), color var(--app-transition-fast);
}

.tool-section summary::-webkit-details-marker { display: none; }

.tool-section summary::before {
  display: inline-block;
  content: '›';
  color: var(--app-text-subtle);
  font-size: 14px;
  line-height: 1;
  transition: transform var(--app-transition-base);
}

.tool-section[open] > summary::before { transform: rotate(90deg); }

.tool-section summary:hover {
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
}

.tool-section pre {
  max-height: 420px;
  margin: 0;
  padding: 0 var(--app-space-md) var(--app-space-md);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: transparent;
  font-size: 12px;
}

.tool-artifacts {
  border-top: 1px solid var(--app-divider);
}

.tool-artifact {
  display: flex;
  min-width: min(240px, 100%);
  align-items: center;
  gap: var(--app-space-sm);
  padding: 8px 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text);
  text-decoration: none;
}

.tool-artifact > span:last-child {
  display: grid;
  min-width: 0;
}

.tool-artifact-image {
  display: grid;
  width: min(420px, 100%);
  padding: 0;
  overflow: hidden;
}

.tool-artifact-preview {
  display: block;
  width: 100%;
  max-height: 320px;
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface-muted);
  object-fit: contain;
}

.tool-artifact-image .tool-artifact-details {
  padding: 9px 11px;
}

.tool-artifact strong,
.tool-artifact small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-artifact small {
  color: var(--app-text-muted);
}
</style>
