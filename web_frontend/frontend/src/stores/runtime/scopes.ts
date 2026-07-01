import type { ActiveRequestView, FactoryFrontendEvent, FactoryMode } from '@/types/protocol'

export interface AgentPackageScopeInfo {
  packageId: string
  sessionId: string
  scope: string
}

export function agentPackageConversationScope(
  packageId: string | null,
  sessionId: string | null,
): string {
  return `agent_package:${packageId || 'unknown'}:${sessionId || 'new'}`
}

export function conversationScopeForMode(
  mode: string | null,
  payload: Record<string, any> = {},
): string | null {
  if (mode === 'chat') return 'factory:chat'
  if (mode === 'create_agent') return 'factory:create_agent'
  if (mode === 'evolve_agent') {
    const packageId = payload?.package_id || payload?.package?.package_id
    return `factory:evolve_agent:${packageId || 'unselected'}`
  }
  return null
}

export function conversationScopeForRequestEvent(
  event: FactoryFrontendEvent,
  activeRequests: Record<string, ActiveRequestView>,
): string | null {
  const requestId = event.request_id || null
  if (requestId && activeRequests[requestId]?.conversationScope) {
    return activeRequests[requestId].conversationScope || null
  }
  return scopeFromEventPayload(event)
}

export function scopeFromEventPayload(event: FactoryFrontendEvent): string | null {
  if (event.mode === 'agent_package') {
    const agentSession = event.payload?.agent_session && typeof event.payload.agent_session === 'object'
      ? event.payload.agent_session
      : {}
    const packageId = String(event.payload?.package_id || agentSession.package_id || '').trim()
    const sessionId = String(event.session_id || agentSession.session_id || '').trim()
    if (packageId) {
      return agentPackageConversationScope(packageId, sessionId || null)
    }
  }
  return conversationScopeForMode(event.mode, event.payload || {})
}

export function agentPackageScopeInfoFromEvent(event: FactoryFrontendEvent): AgentPackageScopeInfo | null {
  if (event.mode !== 'agent_package') return null
  const agentSession = event.payload?.agent_session && typeof event.payload.agent_session === 'object'
    ? event.payload.agent_session
    : {}
  const packageId = String(event.payload?.package_id || agentSession.package_id || '').trim()
  const sessionId = String(event.session_id || agentSession.session_id || '').trim()
  if (!packageId || !sessionId) return null
  return {
    packageId,
    sessionId,
    scope: agentPackageConversationScope(packageId, sessionId),
  }
}

export function scopeFromMessageMetadata(
  metadata: Record<string, any>,
  currentMode: FactoryMode | null,
): string | null {
  const mode = String(metadata.mode || currentMode || '')
  if (mode === 'agent_package') {
    return agentPackageConversationScope(
      metadata.package_id ? String(metadata.package_id) : null,
      metadata.agent_session_id ? String(metadata.agent_session_id) : null,
    )
  }
  return conversationScopeForMode(mode, metadata)
}
