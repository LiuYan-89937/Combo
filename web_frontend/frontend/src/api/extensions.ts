import type { ToolPermissionOverrideView, ToolPermissionPolicyView } from '@/types/protocol'
import type { McpServerConfig, SkillConfig, WorkspaceContextInput, WorkspaceRequestContext } from './resourceTypes'
import { requestEvent, withQuery } from './http'

type ExtensionContext = Pick<WorkspaceRequestContext, 'packageId' | 'resourceMode'>

export const extensionsApi = {
  list: (context?: WorkspaceContextInput) => requestEvent(withQuery('/api/extensions', extensionContextQuery(context))),
  saveMcp: (server: McpServerConfig, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/mcp', {
      method: 'POST',
      body: JSON.stringify({ server, ...extensionContextPayload(context) }),
    }),
  testMcp: (serverIdOrConfig: string | McpServerConfig, context?: WorkspaceContextInput) => {
    const payload =
      typeof serverIdOrConfig === 'string'
        ? { server_id: serverIdOrConfig, ...extensionContextPayload(context) }
        : { server: serverIdOrConfig, ...extensionContextPayload(context) }
    return requestEvent('/api/extensions/mcp/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  setMcpEnabled: (serverId: string, enabled: boolean, context?: WorkspaceContextInput) =>
    requestEvent(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, ...extensionContextPayload(context) }),
    }),
  removeMcp: (serverId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, extensionContextQuery(context)), {
      method: 'DELETE',
    }),
  saveSkill: (skill: SkillConfig, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/skills', {
      method: 'POST',
      body: JSON.stringify({
        skill,
        replace_skill_id: skill.replace_skill_id,
        ...extensionContextPayload(context),
      }),
    }),
  setSkillEnabled: (skillId: string, enabled: boolean, context?: WorkspaceContextInput) =>
    requestEvent(`/api/extensions/skills/${encodeURIComponent(skillId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, ...extensionContextPayload(context) }),
    }),
  removeSkill: (skillId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/skills/${encodeURIComponent(skillId)}`, extensionContextQuery(context)), {
      method: 'DELETE',
    }),
  updateToolPermissions: (policy: ToolPermissionPolicyView, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/tool-permissions', {
      method: 'PUT',
      body: JSON.stringify({ policy, ...extensionContextPayload(context) }),
    }),
  setToolPermission: (toolId: string, override: ToolPermissionOverrideView, context?: WorkspaceContextInput) =>
    requestEvent(`/api/extensions/tool-permissions/${encodeURIComponent(toolId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ override, ...extensionContextPayload(context) }),
    }),
  resetToolPermission: (toolId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/tool-permissions/${encodeURIComponent(toolId)}`, extensionContextQuery(context)), {
      method: 'DELETE',
    }),
}

function extensionContextPayload(context?: WorkspaceContextInput): { package_id?: string; resource_mode?: string } {
  const normalized = normalizeExtensionContext(context)
  return {
    ...(normalized.packageId ? { package_id: normalized.packageId } : {}),
    ...(normalized.resourceMode ? { resource_mode: normalized.resourceMode } : {}),
  }
}

function extensionContextQuery(context?: WorkspaceContextInput): { package_id?: string; resource_mode?: string } {
  return extensionContextPayload(context)
}

function normalizeExtensionContext(context?: WorkspaceContextInput): ExtensionContext {
  if (typeof context === 'string') return { packageId: context || undefined }
  if (!context) return {}
  return {
    packageId: context.packageId || undefined,
    resourceMode: context.resourceMode,
  }
}
