/**
 * 将协议 reducer 的结果同步到页面级 stores。
 *
 * SSE 事件先进入 RuntimeStore，页面组件仍通过各自领域 store 读取数据。
 * 这里保持两者一致，避免“后端返回了但页面读不到”的状态分叉。
 */

import type { RuntimeFrontendEvent } from '@/types/protocol'
import { useAgentStore } from './agent'
import { useExtensionStore } from './extension'
import { useKnowledgeStore } from './knowledge'
import { useRuntimeStore } from './runtime'
import { useSchedulerStore } from './scheduler'
import { useSessionStore } from './session'
import { useWorkspaceStore } from './workspace'
import { SYSTEM_CHAT_PACKAGE_ID, normalizeResourcePackageId } from '@/utils/resourceScope'
import {
  isStandaloneAgentSession,
  isStandaloneMainSession,
} from '@/utils/sessionPresentation'
import { sessionDeletionFromPayload } from './runtime/sessionDeletion'

export function syncDomainStoresFromRuntime(event: RuntimeFrontendEvent): void {
  const runtimeStore = useRuntimeStore()
  if (event.event_type === 'agent_package_selected' && !runtimeStore.ownsAgentPackageSelection(event)) {
    return
  }
  const hasRunAgentSession =
    (
      event.event_type === 'run_started'
      || event.event_type === 'run_completed'
      || event.event_type === 'run_cancelled'
      || event.event_type === 'run_failed'
    )
    && Boolean(event.payload?.agent_session)

  if (
    event.event_type === 'session_started' ||
    event.event_type === 'session_switched' ||
    event.event_type === 'session_empty' ||
    event.event_type === 'session_deleted' ||
    event.event_type === 'sessions_listed'
  ) {
    const sessionStore = useSessionStore()
    sessionStore.setSessions(runtimeStore.sessions as any)
    const activeMainSessionId = runtimeStore.activeMainSessionId
    const activeMainSession = runtimeStore.sessions.find((session: any) => (
      session.session_id === activeMainSessionId && isStandaloneMainSession(session)
    ))
    if (activeMainSession || event.event_type === 'session_deleted' || event.event_type === 'session_empty') {
      sessionStore.setCurrentSession(activeMainSession ? activeMainSessionId : null)
    }
    if (event.event_type === 'session_deleted') {
      useAgentStore().removeRecentSessionsForPackage(SYSTEM_CHAT_PACKAGE_ID)
    }
  }

  if (
    event.event_type === 'agent_packages_listed' ||
    event.event_type === 'agent_package_deleted' ||
    event.event_type === 'agent_package_selected' ||
    event.event_type === 'agent_package_sessions_listed' ||
    event.event_type === 'agent_package_session_loaded' ||
    event.event_type === 'agent_package_session_deleted' ||
    hasRunAgentSession
  ) {
    const agentStore = useAgentStore()
    if (event.event_type === 'agent_packages_listed' || event.event_type === 'agent_package_deleted') {
      agentStore.setPackages(runtimeStore.agentPackages as any)
    }
    if (event.event_type === 'agent_package_deleted' && event.payload?.package_id) {
      agentStore.removePackage(String(event.payload.package_id))
    }
    if (event.event_type === 'agent_package_selected' && event.payload?.package?.package_id) {
      agentStore.addPackage(event.payload.package as any)
    }
    if (runtimeStore.selectedAgentPackage?.package_id) {
      agentStore.selectPackage(runtimeStore.selectedAgentPackage.package_id)
    }
    const sessionPackageId = String(
      event.payload?.package_id
      || event.payload?.package?.package_id
      || runtimeStore.selectedAgentPackage?.package_id
      || '',
    ).trim()
    agentStore.setSessions(runtimeStore.agentSessions as any, sessionPackageId)
    if (event.event_type === 'agent_package_sessions_listed') {
      agentStore.mergeRecentSessions(
        runtimeStore.agentSessions.map((session: any) => sessionWithPackage(session, event.payload?.package_id)) as any
      )
    }
    if (
      event.event_type === 'agent_package_session_loaded' &&
      event.payload?.session &&
      isStandaloneAgentSession(event.payload.session)
    ) {
      agentStore.mergeRecentSessions([sessionWithPackage(event.payload.session, event.payload.package_id)])
    }
    if (event.event_type === 'agent_package_session_deleted') {
      sessionDeletionFromPayload(event.payload).sessionIds.forEach((sessionId) => {
        agentStore.removeSession(sessionId)
      })
    }
    if (hasRunAgentSession && isStandaloneAgentSession(event.payload?.agent_session || {})) {
      agentStore.mergeRecentSessions([sessionWithPackage(event.payload.agent_session, event.payload.package_id)])
    }
    if (
      event.event_type === 'agent_package_session_loaded'
      && event.payload?.session?.session_id
      && isStandaloneAgentSession(event.payload.session)
    ) {
      const loadedSessionId = String(event.payload.session.session_id)
      if (runtimeStore.activeAgentSessionId === loadedSessionId) {
        const packageId = String(event.payload.package_id || event.payload.session.package_id || '').trim()
        if (packageId) {
          agentStore.enterAgentChat(packageId, loadedSessionId)
        } else {
          agentStore.setActiveAgentSession(loadedSessionId)
        }
      }
    }
    if (
      hasRunAgentSession
      && runtimeStore.activeAgentSessionId
      && isStandaloneAgentSession(event.payload?.agent_session || {})
    ) {
      const packageId = String(event.payload.package_id || event.payload.agent_session?.package_id || '').trim()
      if (packageId) {
        agentStore.enterAgentChat(packageId, runtimeStore.activeAgentSessionId)
      } else {
        agentStore.setActiveAgentSession(runtimeStore.activeAgentSessionId)
      }
    }
  }

  if (
    event.event_type === 'agent_package_instance_updated' ||
    event.event_type === 'agent_package_instances_listed'
  ) {
    const agentStore = useAgentStore()
    if (event.event_type === 'agent_package_instances_listed' && Array.isArray(event.payload?.instances)) {
      agentStore.setInstances(event.payload.instances as any)
    }
    if (event.event_type === 'agent_package_instance_updated' && event.payload?.package_id) {
      agentStore.upsertInstance(event.payload as any)
    }
  }

  if (event.event_type.startsWith('workspace_') && resourceEventMatchesCurrentContext(event)) {
    const workspaceStore = useWorkspaceStore()
    if (event.event_type === 'workspace_roots_listed') {
      workspaceStore.setRoots(runtimeStore.workspaceRoots)
    } else if (event.event_type === 'workspace_entries_listed') {
      workspaceStore.setEntries(runtimeStore.workspaceEntries)
    } else if (event.event_type === 'workspace_file_read') {
      workspaceStore.setCurrentFile(runtimeStore.workspaceFile)
    }
  }

  if (event.event_type.startsWith('knowledge_') && resourceEventMatchesCurrentContext(event)) {
    const knowledgeStore = useKnowledgeStore()
    if (event.event_type.startsWith('knowledge_ingestion_')) {
      knowledgeStore.applyIngestionEvent(event)
    }
    if (
      event.event_type === 'knowledge_sources_listed' ||
      event.event_type === 'knowledge_source_registered' ||
      event.event_type === 'knowledge_source_removed' ||
      event.event_type === 'knowledge_source_reindex_requested' ||
      event.event_type === 'knowledge_source_ready'
    ) {
      knowledgeStore.setSources(runtimeStore.knowledgeSources)
    }
    if (event.event_type === 'knowledge_documents_listed') {
      knowledgeStore.setDocuments(runtimeStore.knowledgeDocuments)
    }
    if (event.event_type === 'knowledge_search_completed') {
      knowledgeStore.setSearchResults(runtimeStore.knowledgeResults)
    }
    if (event.event_type === 'knowledge_document_read') {
      knowledgeStore.setCurrentDocument(runtimeStore.knowledgeDocument)
    }
  }

  if (event.event_type.startsWith('scheduler_') && resourceEventMatchesCurrentContext(event)) {
    const schedulerStore = useSchedulerStore()
    if (
      event.event_type === 'scheduler_jobs_listed' ||
      event.event_type === 'scheduler_job_created' ||
      event.event_type === 'scheduler_job_updated' ||
      event.event_type === 'scheduler_job_deleted' ||
      event.event_type === 'scheduler_job_described'
    ) {
      schedulerStore.setJobs(runtimeStore.schedulerJobs)
    }
    if (event.event_type === 'scheduler_options_listed') {
      schedulerStore.setToolOptions(runtimeStore.schedulerToolOptions)
    }
    const runs = event.payload?.payload?.runs || event.payload?.runs
    if (Array.isArray(runs)) {
      schedulerStore.setRuns(runs)
    }
  }

  if (
    event.event_type === 'extension_configs_listed' ||
    event.event_type === 'extension_config_updated' ||
    event.event_type === 'extension_config_tested' ||
    event.event_type === 'extension_config_test_output_delta' ||
    event.event_type === 'extension_skillhub_result'
  ) {
    if (!resourceEventMatchesCurrentContext(event)) return
    const extensionStore = useExtensionStore()
    extensionStore.setItems(runtimeStore.extensionItems)
    extensionStore.setTestResult(runtimeStore.extensionTestResult)
    extensionStore.setToolPermissions(runtimeStore.toolPermissions)
    extensionStore.setBindings(runtimeStore.extensionBindings)
    if (event.payload?.skillhub) {
      extensionStore.setSkillHubResult(event.payload.skillhub)
    }
  }
}

function resourceEventMatchesCurrentContext(event: RuntimeFrontendEvent): boolean {
  return resourceEventPackageId(event) === currentResourcePackageId()
}

function currentResourcePackageId(): string | null {
  const agentStore = useAgentStore()
  if (agentStore.activeChatPackageId) {
    return normalizeResourcePackageId(agentStore.activeChatPackageId)
  }
  return normalizeResourcePackageId(SYSTEM_CHAT_PACKAGE_ID)
}

function resourceEventPackageId(event: RuntimeFrontendEvent): string | null {
  const payload = event.payload || {}
  const nested = payload.payload && typeof payload.payload === 'object' ? payload.payload : {}
  const execution = nested.execution && typeof nested.execution === 'object' ? nested.execution : {}
  return normalizeResourcePackageId(
    payload.package_id ||
      nested.package_id ||
      execution.package_id ||
      payload.owner_id ||
      nested.owner_id ||
      null
  )
}

function sessionWithPackage(session: any, packageId: unknown): any {
  if (!session || typeof session !== 'object') return session
  return {
    ...session,
    package_id: session.package_id || packageId,
  }
}
