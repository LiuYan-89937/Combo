import type { FactoryFrontendEvent, RuntimeViewState } from '@/types/protocol'
import {
  extensionItemView,
  knowledgeDocumentView,
  knowledgeSearchResultView,
  knowledgeSourceView,
  schedulerJobView,
  schedulerRunNoticeView,
  schedulerToolOptionView,
  workspaceEntryView,
  workspaceFileView,
  workspaceRootView,
} from './viewMappers'

export type ResourceMutationState = Pick<
  RuntimeViewState,
  | 'extensionItems'
  | 'extensionTestResult'
  | 'knowledgeDocument'
  | 'knowledgeDocuments'
  | 'knowledgeResults'
  | 'knowledgeSources'
  | 'schedulerJobs'
  | 'schedulerRunNotices'
  | 'schedulerToolOptions'
  | 'workspaceEntries'
  | 'workspaceFile'
  | 'workspaceRoots'
>

const SCHEDULER_NOTICE_EVENTS = new Set([
  'scheduler_run_scheduled',
  'scheduler_run_started',
  'scheduler_run_completed',
  'scheduler_run_failed',
  'scheduler_run_skipped',
  'scheduler_run_cancelled',
])

export function applyKnowledgeEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  updateKnowledgeSources(state, event)
  if (event.event_type === 'knowledge_documents_listed') {
    const documents = event.payload?.documents || []
    state.knowledgeDocuments = Array.isArray(documents)
      ? documents.map(knowledgeDocumentView)
      : []
  } else if (event.event_type === 'knowledge_search_completed') {
    const results = event.payload?.results || []
    state.knowledgeResults = Array.isArray(results)
      ? results.map(knowledgeSearchResultView)
      : []
  } else if (event.event_type === 'knowledge_document_read') {
    state.knowledgeDocument = event.payload || null
  }
}

export function applyWorkspaceEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type === 'workspace_roots_listed') {
    const roots = event.payload?.roots || []
    state.workspaceRoots = Array.isArray(roots)
      ? roots.map(workspaceRootView)
      : []
  } else if (event.event_type === 'workspace_entries_listed') {
    const entries = event.payload?.entries || []
    state.workspaceEntries = Array.isArray(entries)
      ? entries.map(workspaceEntryView)
      : []
  } else if (event.event_type === 'workspace_file_read') {
    state.workspaceFile = workspaceFileView(event.payload || {})
  }
}

export function applyExtensionsEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  const mcpServers = Array.isArray(event.payload?.mcp_servers) ? event.payload?.mcp_servers : []
  const skills = Array.isArray(event.payload?.skills) ? event.payload?.skills : []
  state.extensionItems = [
    ...mcpServers.map((item: any) => extensionItemView(item, 'mcp')),
    ...skills.map((item: any) => extensionItemView(item, 'skill')),
  ]
  if (event.event_type === 'extension_config_tested') {
    state.extensionTestResult = event.payload?.test || event.payload || null
  } else if (event.event_type === 'extension_config_updated') {
    state.extensionTestResult = null
  }
}

export function applySchedulerEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  updateSchedulerJobs(state, event)
  updateSchedulerOptions(state, event)
  updateSchedulerRunNotices(state, event)
}

export function markSchedulerRunNoticeRead(state: ResourceMutationState, noticeId: string) {
  const notice = state.schedulerRunNotices.find((item) => item.id === noticeId)
  if (notice) {
    notice.unread = false
  }
}

function updateKnowledgeSources(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (Array.isArray(event.payload?.sources)) {
    state.knowledgeSources = event.payload.sources.map((source: any) => knowledgeSourceView(source, event.timestamp))
    return
  }
  if (event.event_type === 'knowledge_source_removed') {
    const sourceId = event.payload?.source_id
    if (sourceId) {
      state.knowledgeSources = state.knowledgeSources.filter((source) => source.payload?.source_id !== sourceId)
      state.knowledgeDocuments = state.knowledgeDocuments.filter((document) => document.payload?.source_id !== sourceId)
      state.knowledgeResults = state.knowledgeResults.filter((result) => result.payload?.source_id !== sourceId)
    }
    return
  }

  const source = event.payload?.source || event.payload?.preview || null
  const sourceId = event.payload?.source_id || source?.source_id
  if (!sourceId && !source?.display_name) return

  const item = knowledgeSourceView(source || event.payload, event.timestamp)
  const key = String(sourceId || item.name)
  const index = state.knowledgeSources.findIndex((value) => String(value.payload?.source_id || value.name) === key)
  if (index >= 0) {
    state.knowledgeSources[index] = item
  } else {
    state.knowledgeSources.unshift(item)
  }
}

function updateSchedulerJobs(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type === 'scheduler_job_deleted') {
    const jobId = event.payload?.job_id
    state.schedulerJobs = state.schedulerJobs.filter((item) => item.payload?.job_id !== jobId)
    return
  }
  const jobs = event.payload?.payload?.jobs || event.payload?.jobs
  if (Array.isArray(jobs)) {
    state.schedulerJobs = jobs.map(schedulerJobView)
    return
  }
  const job = event.payload?.payload?.job || event.payload?.job
  if (!job) return

  const view = schedulerJobView(job)
  const index = state.schedulerJobs.findIndex((item) => item.payload?.job_id === job.job_id)
  if (index >= 0) {
    state.schedulerJobs[index] = view
  } else {
    state.schedulerJobs.unshift(view)
  }
}

function updateSchedulerOptions(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type !== 'scheduler_options_listed') return
  const tools = event.payload?.payload?.tools || event.payload?.tools || []
  state.schedulerToolOptions = Array.isArray(tools)
    ? tools
        .map(schedulerToolOptionView)
        .filter((tool): tool is NonNullable<ReturnType<typeof schedulerToolOptionView>> => tool !== null)
    : []
}

function updateSchedulerRunNotices(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (!SCHEDULER_NOTICE_EVENTS.has(event.event_type)) return

  const notice = schedulerRunNoticeView(event)
  if (!notice) return
  const index = state.schedulerRunNotices.findIndex((item) => item.id === notice.id)
  if (index >= 0) {
    state.schedulerRunNotices[index] = {
      ...state.schedulerRunNotices[index],
      ...notice,
      unread: notice.status === 'running' ? state.schedulerRunNotices[index].unread : true,
    }
  } else {
    state.schedulerRunNotices.unshift(notice)
  }
  if (state.schedulerRunNotices.length > 30) {
    state.schedulerRunNotices = state.schedulerRunNotices.slice(0, 30)
  }
}
