/**
 * Session Store
 * 管理 Factory 会话列表和会话切换
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface SessionView {
  session_id: string
  display_title: string | null
  first_user_input: string | null
  current_mode: string | null
  chat_turn_count: number
  create_agent_turn_count: number
  created_at: string
  updated_at: string
}

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<SessionView[]>([])
  const currentSessionId = ref<string | null>(null)

  function setSessions(newSessions: SessionView[]): void {
    sessions.value = newSessions
  }

  function setCurrentSession(sessionId: string): void {
    currentSessionId.value = sessionId
  }

  function addSession(session: SessionView): void {
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
  }

  return {
    sessions,
    currentSessionId,
    setSessions,
    setCurrentSession,
    addSession,
    removeSession,
  }
})
