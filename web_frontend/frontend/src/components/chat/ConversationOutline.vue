<template>
  <div class="conversation-outline">
    <header class="outline-header">
      <strong>{{ t('outline.title') }}</strong>
      <span class="outline-count">{{ t('outline.turnCount', { count: entries.length }) }}</span>
    </header>

    <p v-if="!entries.length" class="outline-empty">{{ t('outline.empty') }}</p>

    <div v-else class="outline-list">
      <button
        v-for="(entry, index) in entries"
        :key="entry.id"
        type="button"
        class="outline-entry"
        :class="[`outline-state-${entry.status}`, { active: entry.anchorId === props.activeAnchorId }]"
        :title="entry.userPreview || entry.resultPreview"
        @click="emit('jump', entry.anchorId)"
      >
        <span class="outline-index">{{ index + 1 }}</span>
        <span class="outline-copy">
          <span class="outline-user">{{ entry.userPreview || t('outline.untitled') }}</span>
          <span v-if="entry.resultPreview" class="outline-result">{{ entry.resultPreview }}</span>
          <span class="outline-meta">
            <span>{{ formattedTime(entry.timestamp) }}</span>
            <span v-if="entry.toolCount" class="outline-meta-tools">
              {{ t('outline.tools', { count: entry.toolCount }) }}
            </span>
          </span>
        </span>
        <span class="outline-state" aria-hidden="true"></span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useConversationMessageProjection } from '@/composables/conversation/useConversationMessageProjection'
import { buildConversationOutline } from '@/utils/conversationOutline'

const props = withDefaults(defineProps<{
  activeAnchorId?: string | null
}>(), {
  activeAnchorId: null,
})

const emit = defineEmits<{
  jump: [anchorId: string]
}>()

const { locale, t } = useI18n()
const { timelineItems, isTimelineItemStreaming } = useConversationMessageProjection()

const entries = computed(() => buildConversationOutline(
  timelineItems.value,
  item => isTimelineItemStreaming(item),
))

function formattedTime(timestamp: string): string {
  const date = new Date(timestamp)
  if (!Number.isFinite(date.getTime())) return ''
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  return date.toLocaleString(locale.value, sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.conversation-outline {
  display: flex;
  width: min(340px, calc(100vw - 44px));
  max-height: min(62vh, 560px);
  flex-direction: column;
  padding: 12px 6px 12px 12px;
}

.outline-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding-right: 6px;
  margin-bottom: 10px;
}

.outline-header strong { font-size: 13px; }

.outline-count { color: var(--app-text-muted); font-size: 10px; }

.outline-empty {
  margin: 0;
  padding: 18px 4px;
  color: var(--app-text-muted);
  font-size: 11px;
  text-align: center;
}

.outline-list {
  display: grid;
  gap: 2px;
  overflow-y: auto;
  padding-right: 6px;
  scrollbar-width: thin;
}

.outline-entry {
  position: relative;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 8px;
  align-items: start;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--app-transition-base);
}

.outline-entry:hover { background: var(--app-surface-hover); }

.outline-entry.active {
  background: var(--app-surface-hover);
  box-shadow: inset 2px 0 0 var(--app-text);
}

.outline-index {
  padding-top: 1px;
  color: var(--app-text-subtle);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.outline-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.outline-user {
  overflow: hidden;
  color: var(--app-text);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.outline-result {
  display: -webkit-box;
  overflow: hidden;
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.outline-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--app-text-subtle);
  font-size: 10px;
}

.outline-meta-tools::before {
  margin-right: 8px;
  content: '·';
}

.outline-state {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: transparent;
}

.outline-state-running .outline-state { background: var(--app-info); animation: app-pulse-soft 1.4s ease-in-out infinite; }
.outline-state-failed .outline-state { background: var(--app-error); }
</style>
