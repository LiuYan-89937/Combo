export interface SessionPresentationMetadata {
  collaboration_id?: string | null
  visible_in_agent_session_list?: boolean | null
  visible_in_factory_session_list?: boolean | null
}

export function isStandaloneAgentSession(session: SessionPresentationMetadata): boolean {
  return session.visible_in_agent_session_list !== false && !normalizedCollaborationId(session)
}

export function isStandaloneFactorySession(session: SessionPresentationMetadata): boolean {
  return session.visible_in_factory_session_list !== false && !normalizedCollaborationId(session)
}

function normalizedCollaborationId(session: SessionPresentationMetadata): string {
  return String(session.collaboration_id || '').trim()
}
