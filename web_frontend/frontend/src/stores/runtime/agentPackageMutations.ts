import type { RuntimeFrontendEvent, RuntimeViewState } from '@/types/protocol'
import { isStandaloneAgentSession } from '@/utils/sessionPresentation'
import { sessionDeletionFromPayload, sessionDeletionIncludes } from './sessionDeletion'

type AgentPackageState = Pick<
  RuntimeViewState,
  'agentPackages' | 'selectedAgentPackage' | 'agentSessions' | 'currentMode' | 'activeAgentSessionId'
>

export function applyAgentPackageListed(state: AgentPackageState, event: RuntimeFrontendEvent) {
  state.agentPackages = event.payload?.packages || []
}

export function applyAgentPackageSelected(state: AgentPackageState, event: RuntimeFrontendEvent) {
  state.currentMode = event.mode || state.currentMode
  state.selectedAgentPackage = event.payload?.package || null
  if (event.payload?.sessions) {
    state.agentSessions = event.payload.sessions.filter(isStandaloneAgentSession)
  }
}

export function applyAgentPackageDeleted(state: AgentPackageState, event: RuntimeFrontendEvent) {
  const deletedPackageId = event.payload?.package_id
  state.agentPackages = event.payload?.packages
    || state.agentPackages.filter((pkg) => pkg.package_id !== deletedPackageId)
  if (state.selectedAgentPackage?.package_id === deletedPackageId) {
    state.selectedAgentPackage = null
  }
}

export function applyAgentPackageSessionsListed(state: AgentPackageState, event: RuntimeFrontendEvent) {
  state.agentSessions = (event.payload?.sessions || []).filter(isStandaloneAgentSession)
}

export function applyAgentPackageSessionDeleted(
  state: AgentPackageState,
  event: RuntimeFrontendEvent,
): { sessionIds: string[]; deletedCurrentSession: boolean; emptyPackageId: string | null } {
  const deletion = sessionDeletionFromPayload(event.payload)
  const deletedSessionIds = new Set(deletion.sessionIds)
  const deletedCurrentSession = sessionDeletionIncludes(deletion, state.activeAgentSessionId)
  state.agentSessions = event.payload?.sessions
    ? event.payload.sessions.filter(isStandaloneAgentSession)
    : state.agentSessions.filter((session) => !deletedSessionIds.has(session.session_id))
  return {
    sessionIds: deletion.sessionIds,
    deletedCurrentSession,
    emptyPackageId: deletedCurrentSession
      ? String(event.payload?.package_id || state.selectedAgentPackage?.package_id || '').trim() || null
      : null,
  }
}
