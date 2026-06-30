/**
 * Agent Store
 * 管理 Agent 包和子会话
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface AgentPackageView {
  package_id: string
  agent_name: string | null
  name: string | null
  agent_description: string | null
  status: string | null
  tool_count: number | null
  session_count: number | null
  created_at: string | null
  updated_at: string | null
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

  function setPackages(packages: AgentPackageView[]): void {
    agentPackages.value = packages
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
    selectedPackageId,
    agentSessions,
    selectedSessionId,
    activeChatPackageId,
    selectedPackage,
    selectedSession,
    activeChatPackage,
    setPackages,
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
