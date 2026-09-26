const MAX_RECENT_EVENT_IDS = 10_000

const recentEventIds = new Set<string>()

export function acceptRuntimeEventId(eventId: string): boolean {
  if (recentEventIds.has(eventId)) return false
  rememberRuntimeEventIds([eventId])
  return true
}

export function rememberRuntimeEventIds(eventIds: Iterable<string>): void {
  for (const eventId of eventIds) {
    if (recentEventIds.has(eventId)) continue
    recentEventIds.add(eventId)
    while (recentEventIds.size > MAX_RECENT_EVENT_IDS) {
      const oldest = recentEventIds.values().next().value
      if (oldest === undefined) break
      recentEventIds.delete(oldest)
    }
  }
}
