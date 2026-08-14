import type { RuntimeFrontendEvent, RuntimeMode } from '@/types/protocol'

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
  if (mode !== 'agent_package') return null
  const session = payload?.session && typeof payload.session === 'object' ? payload.session : {}
  const packageId = cleanText(payload.package_id || payload?.package?.package_id || session.package_id)
  if (!packageId) return null
  return agentPackageConversationScope(
    packageId,
    cleanText(payload.session_id || payload.agent_session_id || session.session_id),
  )
}

export function isMoreSpecificConversationScope(
  currentScope: string | null | undefined,
  nextScope: string | null | undefined,
): boolean {
  if (!currentScope || !nextScope || currentScope === nextScope) return false
  const currentParts = currentScope.split(':')
  const nextParts = nextScope.split(':')
  if (currentParts.length !== nextParts.length) return false
  if (currentParts[currentParts.length - 1] !== 'new') return false
  if (!nextParts[nextParts.length - 1] || nextParts[nextParts.length - 1] === 'new') return false
  return currentParts.slice(0, -1).join(':') === nextParts.slice(0, -1).join(':')
}

export function scopeFromEventPayload(event: RuntimeFrontendEvent): string | null {
  if (event.mode === 'agent_package') {
    const agentSession = event.payload?.agent_session && typeof event.payload.agent_session === 'object'
      ? event.payload.agent_session
      : {}
    const loadedSession = event.payload?.session && typeof event.payload.session === 'object'
      ? event.payload.session
      : {}
    const packageId = String(event.payload?.package_id || agentSession.package_id || '').trim()
    const sessionId = String(
      event.payload?.session_id
      || event.payload?.agent_session_id
      || event.session_id
      || agentSession.session_id
      || loadedSession.session_id
      || '',
    ).trim()
    if (packageId) {
      return agentPackageConversationScope(packageId, sessionId || null)
    }
  }
  return conversationScopeForMode(event.mode, {
    ...(event.payload || {}),
    session_id: event.session_id || event.payload?.session_id,
  })
}

export function agentPackageScopeInfoFromEvent(event: RuntimeFrontendEvent): AgentPackageScopeInfo | null {
  if (event.mode !== 'agent_package') return null
  const agentSession = event.payload?.agent_session && typeof event.payload.agent_session === 'object'
    ? event.payload.agent_session
    : {}
  const loadedSession = event.payload?.session && typeof event.payload.session === 'object'
    ? event.payload.session
    : {}
  const packageId = String(event.payload?.package_id || agentSession.package_id || '').trim()
  const sessionId = String(
    event.payload?.session_id
    || event.payload?.agent_session_id
    || event.session_id
    || agentSession.session_id
    || loadedSession.session_id
    || '',
  ).trim()
  if (!packageId || !sessionId) return null
  return {
    packageId,
    sessionId,
    scope: agentPackageConversationScope(packageId, sessionId),
  }
}

export function scopeFromRequestPayload(
  mode: RuntimeMode | null,
  payload: Record<string, any>,
): string | null {
  if (mode !== 'agent_package') {
    return conversationScopeForMode(mode, payload)
  }
  const packageId = cleanText(payload.package_id)
  if (!packageId) return null
  return agentPackageConversationScope(packageId, cleanText(payload.session_id))
}

export function scopeFromMessageMetadata(
  metadata: Record<string, any>,
  currentMode: RuntimeMode | null,
): string | null {
  const mode = String(metadata.mode || currentMode || '')
  if (mode === 'agent_package') {
    return agentPackageConversationScope(
      metadata.package_id ? String(metadata.package_id) : null,
      metadata.agent_session_id ? String(metadata.agent_session_id) : null,
    )
  }
  return null
}

function cleanText(value: unknown): string | null {
  const text = String(value || '').trim()
  return text || null
}
