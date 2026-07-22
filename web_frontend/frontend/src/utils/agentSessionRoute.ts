import type { LocationQuery, LocationQueryRaw } from 'vue-router'

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
