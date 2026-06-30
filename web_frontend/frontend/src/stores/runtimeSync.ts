/**
 * 将协议 reducer 的结果同步到页面级 stores。
 *
 * SSE 事件先进入 RuntimeStore，页面组件仍通过各自领域 store 读取数据。
 * 这里保持两者一致，避免“后端返回了但页面读不到”的状态分叉。
 */

import type { FactoryFrontendEvent } from '@/types/protocol'
import { useAgentStore } from './agent'
import { useExtensionStore } from './extension'
import { useKnowledgeStore } from './knowledge'
import { useRuntimeStore } from './runtime'
import { useSchedulerStore } from './scheduler'
import { useSessionStore } from './session'
import { useWorkspaceStore } from './workspace'

export function syncDomainStoresFromRuntime(event: FactoryFrontendEvent): void {
  const runtimeStore = useRuntimeStore()

  if (
    event.event_type === 'session_started' ||
    event.event_type === 'session_switched' ||
    event.event_type === 'sessions_listed'
  ) {
    const sessionStore = useSessionStore()
    sessionStore.setSessions(runtimeStore.sessions as any)
    if (runtimeStore.activeFactorySessionId) {
      sessionStore.setCurrentSession(runtimeStore.activeFactorySessionId)
    }
  }

  if (
    event.event_type === 'agent_packages_listed' ||
    event.event_type === 'agent_package_deleted' ||
    event.event_type === 'agent_package_selected' ||
    event.event_type === 'agent_package_sessions_listed' ||
    event.event_type === 'agent_package_session_loaded' ||
    (event.event_type === 'run_completed' && Boolean(event.payload?.agent_session))
  ) {
    const agentStore = useAgentStore()
    agentStore.setPackages(runtimeStore.agentPackages as any)
    if (runtimeStore.selectedAgentPackage?.package_id) {
      agentStore.selectPackage(runtimeStore.selectedAgentPackage.package_id)
    }
    agentStore.setSessions(runtimeStore.agentSessions as any)
    if (event.event_type === 'agent_package_session_loaded' && event.payload?.session?.session_id) {
      agentStore.setActiveAgentSession(event.payload.session.session_id)
    }
    if (event.event_type === 'run_completed' && runtimeStore.activeAgentSessionId) {
      agentStore.setActiveAgentSession(runtimeStore.activeAgentSessionId)
    }
  }

  if (event.event_type.startsWith('workspace_')) {
    const workspaceStore = useWorkspaceStore()
    if (event.event_type === 'workspace_roots_listed') {
      workspaceStore.setRoots(runtimeStore.workspaceRoots)
    } else if (event.event_type === 'workspace_entries_listed') {
      workspaceStore.setEntries(runtimeStore.workspaceEntries)
    } else if (event.event_type === 'workspace_file_read') {
      workspaceStore.setCurrentFile(runtimeStore.workspaceFile)
    }
  }

  if (event.event_type.startsWith('knowledge_')) {
    const knowledgeStore = useKnowledgeStore()
    knowledgeStore.setSources(runtimeStore.knowledgeSources)
    knowledgeStore.setDocuments(runtimeStore.knowledgeDocuments)
    knowledgeStore.setSearchResults(runtimeStore.knowledgeResults)
    knowledgeStore.setCurrentDocument(runtimeStore.knowledgeDocument)
  }

  if (event.event_type.startsWith('scheduler_')) {
    const schedulerStore = useSchedulerStore()
    schedulerStore.setJobs(runtimeStore.schedulerJobs)
    const runs = event.payload?.payload?.runs || event.payload?.runs
    if (Array.isArray(runs)) {
      schedulerStore.setRuns(runs)
    }
  }

  if (
    event.event_type === 'extension_configs_listed' ||
    event.event_type === 'extension_config_updated' ||
    event.event_type === 'extension_config_tested'
  ) {
    const extensionStore = useExtensionStore()
    extensionStore.setItems(runtimeStore.extensionItems)
    extensionStore.setTestResult(runtimeStore.extensionTestResult)
  }
}
