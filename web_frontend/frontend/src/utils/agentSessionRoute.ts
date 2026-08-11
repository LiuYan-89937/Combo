import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

const AGENT_SESSIONS_LANDING_KEY = 'agent_sessions'
const AGENT_SESSIONS_LANDING_VALUE = '1'

export function agentSessionsLandingQuery(): LocationQueryRaw {
  return { [AGENT_SESSIONS_LANDING_KEY]: AGENT_SESSIONS_LANDING_VALUE }
}

export function isAgentSessionsLanding(query: LocationQuery): boolean {
  const value = query[AGENT_SESSIONS_LANDING_KEY]
  const normalized = Array.isArray(value) ? value[0] : value
  return normalized === AGENT_SESSIONS_LANDING_VALUE
}

export function isBuiltinChatRoute(query: LocationQuery): boolean {
  if (isAgentSessionsLanding(query)) return false
  const packageId = queryText(query.package_id)
  return !packageId || packageId === SYSTEM_CHAT_PACKAGE_ID
}

export function isAgentPackageRoute(query: LocationQuery): boolean {
  return isAgentSessionsLanding(query) || !isBuiltinChatRoute(query)
}

function queryText(value: LocationQuery[string]): string {
  const normalized = Array.isArray(value) ? value[0] : value
  return String(normalized || '').trim()
}
