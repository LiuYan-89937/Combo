/**
 * Agent Store
 * 管理 Agent 包和子会话
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface AgentPackageToolView {
  kind?: string
  id?: string
  name: string
  description?: string
  risk_level?: string
  concurrent?: boolean
}

export interface AgentPackageExtensionView {
  kind?: 'mcp' | 'skill' | string
  name: string
  scope?: string
  status?: string
  enabled?: boolean
  summary?: string
  transport?: string | null
  payload?: Record<string, any>
}

export interface AgentPackageKnowledgeSourceView {
  source_id?: string
  name: string
  kind?: string | null
  status?: string | null
  mode?: string | null
  uri?: string | null
  updated_at?: string | null
  document_count?: number | null
  sample_titles?: string[]
}

export interface AgentPackageInstanceView {
  package_id: string
  agent_id?: string | null
  agent_name?: string | null
  backend?: string | null
  status: string
  ready: boolean
  active_request_count?: number
  runtime_root?: string | null
  idle_timeout_seconds?: number | null
  error?: string | null
}

export interface AgentPackageView {
  package_id: string
  package_path?: string
  manifest_path?: string
  factory_run_id?: string | null
  agent_id?: string | null
  agent_name: string | null
  name: string | null
  agent_description: string | null
  status: string | null
  tool_count: number | null
  session_count: number | null
  created_at: string | null
  updated_at: string | null
  sandbox?: Record<string, any>
  extensions?: Record<string, any>
  tools?: AgentPackageToolView[]
  mcp_servers?: AgentPackageExtensionView[]
  skills?: AgentPackageExtensionView[]
  knowledge_sources?: AgentPackageKnowledgeSourceView[]
  extensions_error?: string | null
  knowledge_error?: string | null
  error?: string | null
}

export interface AgentSessionView {
  session_id: string
  package_id: string
  display_title: string | null
  first_user_input: string | null
  turn_count: number
  created_at: string
  updated_at: string
}

export const useAgentStore = defineStore('agent', () => {
  const agentPackages = ref<AgentPackageView[]>([])
  const packageInstances = ref<Record<string, AgentPackageInstanceView>>({})
  const selectedPackageId = ref<string | null>(null)
  const agentSessions = ref<AgentSessionView[]>([])
  const selectedSessionId = ref<string | null>(null)
  const activeChatPackageId = ref<string | null>(null)

  const selectedPackage = computed(() => {
    if (!selectedPackageId.value) return null
    return agentPackages.value.find((pkg) => pkg.package_id === selectedPackageId.value) || null
  })

  const selectedSession = computed(() => {
    if (!selectedSessionId.value) return null
    return agentSessions.value.find((session) => session.session_id === selectedSessionId.value) || null
  })

  const activeChatPackage = computed(() => {
    if (!activeChatPackageId.value) return null
    return agentPackages.value.find((pkg) => pkg.package_id === activeChatPackageId.value) || null
  })

  const selectedPackageInstance = computed(() => {
    if (!selectedPackageId.value) return null
    return packageInstances.value[selectedPackageId.value] || null
  })

  function packageInstance(packageId: string | null | undefined): AgentPackageInstanceView | null {
    if (!packageId) return null
    return packageInstances.value[packageId] || null
  }

  function setPackages(packages: AgentPackageView[]): void {
    agentPackages.value = packages
    if (
      selectedPackageId.value &&
      !agentPackages.value.some((pkg) => pkg.package_id === selectedPackageId.value)
    ) {
      selectedPackageId.value = null
      selectedSessionId.value = null
      agentSessions.value = []
    }
    if (
      activeChatPackageId.value &&
      !agentPackages.value.some((pkg) => pkg.package_id === activeChatPackageId.value)
    ) {
      activeChatPackageId.value = null
      selectedSessionId.value = null
    }
  }

  function setInstances(instances: AgentPackageInstanceView[]): void {
    packageInstances.value = Object.fromEntries(
      instances
        .filter((item) => item.package_id)
        .map((item) => [item.package_id, item])
    )
  }

  function upsertInstance(instance: AgentPackageInstanceView): void {
    if (!instance.package_id) return
    packageInstances.value = {
      ...packageInstances.value,
      [instance.package_id]: instance,
    }
  }

  function selectPackage(packageId: string): void {
    const packageChanged = selectedPackageId.value !== packageId
    selectedPackageId.value = packageId
    if (packageChanged) {
      selectedSessionId.value = null
      agentSessions.value = []
    }
  }

  function setSessions(sessions: AgentSessionView[]): void {
    agentSessions.value = sessions
  }

  function selectSession(sessionId: string | null): void {
    selectedSessionId.value = sessionId
  }

  function enterAgentChat(packageId: string, sessionId: string | null = null): void {
    activeChatPackageId.value = packageId
    selectedPackageId.value = packageId
    selectedSessionId.value = sessionId
  }

  function leaveAgentChat(): void {
    activeChatPackageId.value = null
    selectedSessionId.value = null
  }

  function setActiveAgentSession(sessionId: string | null): void {
    selectedSessionId.value = sessionId
  }

  function addPackage(pkg: AgentPackageView): void {
    const existingIndex = agentPackages.value.findIndex((p) => p.package_id === pkg.package_id)
    if (existingIndex !== -1) {
      agentPackages.value[existingIndex] = pkg
    } else {
      agentPackages.value.unshift(pkg)
    }
  }

  function removePackage(packageId: string): void {
    const index = agentPackages.value.findIndex((p) => p.package_id === packageId)
    if (index !== -1) {
      agentPackages.value.splice(index, 1)
    }
    if (selectedPackageId.value === packageId) {
      selectedPackageId.value = null
    }
    if (activeChatPackageId.value === packageId) {
      activeChatPackageId.value = null
      selectedSessionId.value = null
    }
  }

  return {
    agentPackages,
    packageInstances,
    selectedPackageId,
    agentSessions,
    selectedSessionId,
    activeChatPackageId,
    selectedPackage,
    selectedSession,
    activeChatPackage,
    selectedPackageInstance,
    packageInstance,
    setPackages,
    setInstances,
    upsertInstance,
    selectPackage,
    setSessions,
    selectSession,
    enterAgentChat,
    leaveAgentChat,
    setActiveAgentSession,
    addPackage,
    removePackage,
  }
})
