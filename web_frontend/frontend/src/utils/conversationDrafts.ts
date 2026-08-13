const CONVERSATION_DRAFT_STORAGE_PREFIX = 'combo.conversation-draft.v1:'

function storageKey(scope: string): string {
  return `${CONVERSATION_DRAFT_STORAGE_PREFIX}${encodeURIComponent(scope)}`
}

export function loadConversationDraft(scope: string): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.localStorage.getItem(storageKey(scope)) || ''
  } catch {
    return ''
  }
}

export function saveConversationDraft(scope: string, content: string): void {
  if (typeof window === 'undefined') return
  try {
    if (content.length > 0) {
      window.localStorage.setItem(storageKey(scope), content)
    } else {
      window.localStorage.removeItem(storageKey(scope))
    }
  } catch {
    // Draft persistence must never block composing or sending a message.
  }
}

export function clearConversationDraft(scope: string): void {
  saveConversationDraft(scope, '')
}
