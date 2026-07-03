import { extensionsApi } from '@/api/extensions'
import type { ToolPermissionOverrideView, ToolPermissionPolicyView } from '@/types/protocol'
import type { McpServerConfig, SkillConfig } from '@/api/resourceTypes'
import { useCommandTransport } from './transport'

export function useExtensionCommands() {
  const transport = useCommandTransport()

  const refreshExtensions = (packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.list(packageId))
  }

  const saveMcp = (server: McpServerConfig, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.saveMcp(server, packageId))
  }

  const testMcp = (serverIdOrConfig: string | McpServerConfig, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.testMcp(serverIdOrConfig, packageId))
  }

  const setMcpEnabled = (serverId: string, enabled: boolean, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.setMcpEnabled(serverId, enabled, packageId))
  }

  const removeMcp = (serverId: string, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.removeMcp(serverId, packageId))
  }

  const saveSkill = (skill: SkillConfig, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.saveSkill(skill, packageId))
  }

  const setSkillEnabled = (skillId: string, enabled: boolean, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.setSkillEnabled(skillId, enabled, packageId))
  }

  const removeSkill = (skillId: string, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.removeSkill(skillId, packageId))
  }

  const updateToolPermissions = (policy: ToolPermissionPolicyView, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.updateToolPermissions(policy, packageId))
  }

  const setToolPermission = (toolId: string, override: ToolPermissionOverrideView, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.setToolPermission(toolId, override, packageId))
  }

  const resetToolPermission = (toolId: string, packageId?: string) => {
    return transport.applyEventRequest(extensionsApi.resetToolPermission(toolId, packageId))
  }

  return {
    refreshExtensions,
    saveMcp,
    testMcp,
    setMcpEnabled,
    removeMcp,
    saveSkill,
    setSkillEnabled,
    removeSkill,
    updateToolPermissions,
    setToolPermission,
    resetToolPermission,
  }
}
