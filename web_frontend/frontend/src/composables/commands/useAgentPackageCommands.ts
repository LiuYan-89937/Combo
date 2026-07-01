import * as commands from '@/api/commands'
import { agentPackagesApi } from '@/api/agentPackages'
import { useAgentStore, type AgentPackageView } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useCommandTransport } from './transport'

export function useAgentPackageCommands() {
  const agentStore = useAgentStore()
  const uiStore = useUiStore()
  const transport = useCommandTransport()

  const listAgentPackages = () => {
    transport.applyEventRequest(agentPackagesApi.list())
  }

  const selectAgentPackage = (packageId: string, purpose?: 'run' | 'evolution') => {
    return transport.applyEventRequest(agentPackagesApi.select(packageId, purpose))
  }

  const deleteAgentPackage = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.delete(packageId))
  }

  const exportAgentPackage = async (pkg: AgentPackageView) => {
    try {
      const response = await agentPackagesApi.exportArchive(pkg.package_id)
      const url = URL.createObjectURL(response.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = response.filename || `${pkg.agent_name || pkg.name || pkg.package_id}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      uiStore.addNotification({
        type: 'success',
        title: '导出完成',
        message: `${pkg.agent_name || pkg.name || 'Agent 包'} 已开始下载。`,
        duration: 3000,
      })
      return true
    } catch (error) {
      transport.reportError(error)
      return false
    }
  }

  const listAgentPackageSessions = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.sessions(packageId))
  }

  const listAgentPackageInstances = () => {
    return transport.applyEventRequest(agentPackagesApi.instances())
  }

  const listRecentAgentSessions = async (limit = 5) => {
    try {
      const response = await agentPackagesApi.recentSessions(limit)
      agentStore.setRecentSessions(response.sessions)
      return response.sessions
    } catch (error) {
      transport.reportError(error)
      return []
    }
  }

  const initializeAgentPackage = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.initialize(packageId))
  }

  const shutdownAgentPackageInstance = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.shutdown(packageId))
  }

  const loadAgentPackageSession = (packageId: string, sessionId: string) => {
    return transport.applyEventRequest(agentPackagesApi.session(packageId, sessionId))
  }

  const runAgentPackage = (packageId: string, message: string, sessionId?: string) => {
    const command = commands.runAgentPackageCommand(packageId, message, sessionId)
    transport.sendRuntimeCommand(command)
    return command
  }

  const sendAgentPackageMessage = (packageId: string, message: string, sessionId?: string) => {
    const command = commands.sendAgentPackageMessageCommand(packageId, message, sessionId)
    transport.sendRuntimeCommand(command)
    return command
  }

  const runAgentEvolution = (packageId: string, message: string) => {
    const command = commands.runAgentEvolutionCommand(packageId, message)
    transport.sendRuntimeCommand(command)
    return command
  }

  return {
    listAgentPackages,
    selectAgentPackage,
    deleteAgentPackage,
    exportAgentPackage,
    listAgentPackageSessions,
    listAgentPackageInstances,
    listRecentAgentSessions,
    initializeAgentPackage,
    shutdownAgentPackageInstance,
    loadAgentPackageSession,
    runAgentPackage,
    sendAgentPackageMessage,
    runAgentEvolution,
  }
}
