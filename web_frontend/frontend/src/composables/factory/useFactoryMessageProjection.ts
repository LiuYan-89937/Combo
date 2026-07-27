import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import type { TranscriptItem } from '@/types/protocol'

export interface FactoryTimelineItem {
  kind: 'message'
  id: string
  timestamp: string
  order: number
  message: TranscriptItem
}

export function useFactoryMessageProjection() {
  const runtimeStore = useRuntimeStore()
  const { t } = useI18n()

  const activeStreams = computed(() => {
    return Object.values(runtimeStore.modelStreams).filter(
      (stream) => stream.visibleToUser && stream.active,
    )
  })
  const hasActiveStreams = computed(() => activeStreams.value.length > 0)
  const timelineItems = computed<FactoryTimelineItem[]>(() => (
    runtimeStore.transcript.map((message, index) => (
      {
        kind: 'message',
        id: message.id,
        timestamp: message.timestamp,
        order: index,
        message,
      }
    ))
  ))
  const hasApprovalRequests = computed(() => runtimeStore.currentApprovalRequests.length > 0)
  const transientActivityLabel = computed(() => {
    if (!runtimeStore.hasActiveRun || runtimeStore.isAwaitingUserInputInterrupt) return ''
    if (
      runtimeStore.contextActivity.status === 'running'
      && runtimeStore.contextActivity.eventType === 'context_compression_started'
    ) {
      return t('context.context_compression_started')
    }
    return ''
  })
  const activeStreamContentKey = computed(() => {
    return [
      runtimeStore.transcript.map(messagePartsKey).join('|'),
      transientActivityLabel.value,
    ].join('')
  })

  function isMessageStreaming(streamId?: string): boolean {
    if (!streamId) return false
    return Boolean(runtimeStore.modelStreams[streamId]?.active)
  }

  return {
    activeStreamContentKey,
    hasActiveStreams,
    hasApprovalRequests,
    isMessageStreaming,
    timelineItems,
    transientActivityLabel,
  }
}

function messagePartsKey(message: TranscriptItem): string {
  return message.parts.map((part) => {
    if (part.type === 'text' || part.type === 'reasoning') {
      return `${part.id}:${part.status || ''}:${part.text.length}`
    }
    return `${part.id}:${part.type}:${part.status || ''}`
  }).join(',')
}
