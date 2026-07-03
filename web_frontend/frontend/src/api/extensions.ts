import type { ToolPermissionOverrideView, ToolPermissionPolicyView } from '@/types/protocol'
import type { McpServerConfig, SkillConfig } from './resourceTypes'
import { requestEvent, withQuery } from './http'

export const extensionsApi = {
  list: (packageId?: string) => requestEvent(withQuery('/api/extensions', { package_id: packageId })),
  saveMcp: (server: McpServerConfig, packageId?: string) =>
    requestEvent('/api/extensions/mcp', {
      method: 'POST',
      body: JSON.stringify({ server, package_id: packageId }),
    }),
  testMcp: (serverIdOrConfig: string | McpServerConfig, packageId?: string) => {
    const payload =
      typeof serverIdOrConfig === 'string'
        ? { server_id: serverIdOrConfig, package_id: packageId }
        : { server: serverIdOrConfig, package_id: packageId }
    return requestEvent('/api/extensions/mcp/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  setMcpEnabled: (serverId: string, enabled: boolean, packageId?: string) =>
    requestEvent(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, package_id: packageId }),
    }),
  removeMcp: (serverId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
  saveSkill: (skill: SkillConfig, packageId?: string) =>
    requestEvent('/api/extensions/skills', {
      method: 'POST',
      body: JSON.stringify({
        skill,
        replace_skill_id: skill.replace_skill_id,
        package_id: packageId,
      }),
    }),
  setSkillEnabled: (skillId: string, enabled: boolean, packageId?: string) =>
    requestEvent(`/api/extensions/skills/${encodeURIComponent(skillId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, package_id: packageId }),
    }),
  removeSkill: (skillId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/extensions/skills/${encodeURIComponent(skillId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
  updateToolPermissions: (policy: ToolPermissionPolicyView, packageId?: string) =>
    requestEvent('/api/extensions/tool-permissions', {
      method: 'PUT',
      body: JSON.stringify({ policy, package_id: packageId }),
    }),
  setToolPermission: (toolId: string, override: ToolPermissionOverrideView, packageId?: string) =>
    requestEvent(`/api/extensions/tool-permissions/${encodeURIComponent(toolId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ override, package_id: packageId }),
    }),
  resetToolPermission: (toolId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/extensions/tool-permissions/${encodeURIComponent(toolId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
}
