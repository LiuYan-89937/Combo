import type { RunStatus, TranscriptItem } from '@/types/protocol'

export type RequestDispatchState = 'queued' | 'steering' | 'promoted' | 'running' | 'stopping' | 'completed' | 'cancelled' | 'failed' | 'stopped'

export function isPendingDispatch(value: unknown): boolean {
  return value === 'queued' || value === 'steering'
}

export function dispatchStateForTurn(status: RunStatus): RequestDispatchState {
  if (status === 'queued') return 'queued'
  if (status === 'running' || status === 'interrupted' || status === 'waiting_for_workers') return 'running'
  if (status === 'stopping' || status === 'cancelled' || status === 'failed' || status === 'stopped') return status
  return 'completed'
}

// Submission order orders turns; a checkpoint anchor places guidance within its running turn.
export function orderedTranscript(messages: TranscriptItem[]): TranscriptItem[] {
  const ids = new Set(messages.map(message => message.id))
  const following = new Map<string, TranscriptItem[]>()
  const anchored = new Set<string>()
  for (const message of messages) {
    const after = message.metadata?.steering?.after_message_id
    if (message.role !== 'user' || message.metadata?.dispatch_state !== 'promoted' || !ids.has(after)) continue
    following.set(after, [...(following.get(after) || []), message])
    anchored.add(message.id)
  }
  const result: TranscriptItem[] = []
  const seen = new Set<string>()
  const append = (message: TranscriptItem) => {
    if (seen.has(message.id)) return
    seen.add(message.id)
    result.push(message)
    for (const child of following.get(message.id) || []) append(child)
  }
  for (const message of messages) if (!anchored.has(message.id)) append(message)
  for (const message of messages) append(message)
  return result
}
