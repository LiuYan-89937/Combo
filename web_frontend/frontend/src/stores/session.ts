/**
 * Session Store
 * 管理主会话列表和会话切换
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { isStandaloneMainSession } from '@/utils/sessionPresentation'

export interface SessionView {
  session_id: string
  display_title: string | null
  first_user_input: string | null
  current_mode: string | null
  session_kind?: string | null
  visible_in_main_session_list?: boolean | null
  mode_titles?: Record<string, string | null>
  mode_turn_counts?: Record<string, number>
  created_at: string
  updated_at: string
}

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<SessionView[]>([])
  const currentSessionId = ref<string | null>(null)

  function setSessions(newSessions: SessionView[]): void {
    sessions.value = newSessions.filter(isStandaloneMainSession)
    if (
      currentSessionId.value
      && !sessions.value.some((session) => session.session_id === currentSessionId.value)
    ) {
      currentSessionId.value = null
    }
  }

  function setCurrentSession(sessionId: string | null): void {
    currentSessionId.value = sessionId
  }

  function addSession(session: SessionView): void {
    if (!isStandaloneMainSession(session)) return
    const existingIndex = sessions.value.findIndex((s) => s.session_id === session.session_id)
    if (existingIndex !== -1) {
      sessions.value[existingIndex] = session
    } else {
      sessions.value.unshift(session)
    }
  }

  function removeSession(sessionId: string): void {
    const index = sessions.value.findIndex((s) => s.session_id === sessionId)
    if (index !== -1) {
      sessions.value.splice(index, 1)
    }
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
    }
  }

  function clearSessions(): void {
    sessions.value = []
    currentSessionId.value = null
  }

  return {
    sessions,
    currentSessionId,
    setSessions,
    setCurrentSession,
    addSession,
    removeSession,
    clearSessions,
  }
})
