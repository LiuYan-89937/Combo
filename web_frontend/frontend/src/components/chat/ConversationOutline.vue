<template>
  <div class="conversation-outline">
    <header class="outline-header">
      <strong>{{ t('outline.title') }}</strong>
      <span class="outline-count">{{ t('outline.turnCount', { count: entries.length }) }}</span>
    </header>

    <p v-if="!entries.length" class="outline-empty">{{ t('outline.empty') }}</p>

    <div
      v-else
      ref="listRef"
      class="outline-list"
      role="listbox"
      :aria-label="t('outline.title')"
      tabindex="0"
      @keydown="handleKeydown"
      @blur="cursorIndex = -1"
    >
      <button
        v-for="(entry, index) in entries"
        :key="entry.id"
        type="button"
        role="option"
        class="outline-entry"
        :class="[
          `outline-state-${entry.status}`,
          {
            active: entry.anchorId === props.activeAnchorId,
            cursor: index === cursorIndex,
          },
        ]"
        :aria-selected="entry.anchorId === props.activeAnchorId"
        :title="entry.userPreview || entry.resultPreview"
        @click="emit('jump', entry.anchorId)"
        @mousemove="cursorIndex = index"
      >
        <span class="outline-rail" aria-hidden="true">
          <span class="outline-node"></span>
        </span>
        <span class="outline-copy">
          <span class="outline-user">{{ entry.userPreview || t('outline.untitled') }}</span>
          <span v-if="entry.resultPreview" class="outline-result">{{ entry.resultPreview }}</span>
          <span v-else class="outline-result outline-result-empty">{{ t('outline.pending') }}</span>
        </span>
        <span class="outline-meta">
          <span class="outline-time">{{ formattedTime(entry.timestamp) }}</span>
          <span v-if="entry.toolCount" class="outline-tools">
            {{ t('outline.tools', { count: entry.toolCount }) }}
          </span>
        </span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
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

const listRef = ref<HTMLElement | null>(null)
// Roving highlight for keyboard use; -1 means the user is not navigating yet.
const cursorIndex = ref(-1)

/**
 * Opens on the turn the reader is currently looking at. Without this the panel
 * always starts at the first turn, so long sessions need a scroll before the
 * highlight is even visible.
 */
watch(() => props.activeAnchorId, async () => {
  cursorIndex.value = -1
  await nextTick()
  scrollActiveIntoView()
}, { immediate: true })

// The popover mounts its body on first open, so the initial scroll also has to
// run once the list exists rather than only when the anchor changes.
onMounted(async () => {
  await nextTick()
  scrollActiveIntoView()
})

/** Lets the host popover hand keyboard focus to the list when it opens. */
function focusList(): void {
  cursorIndex.value = -1
  listRef.value?.focus()
}

defineExpose({ focusList })

function scrollActiveIntoView(): void {
  const list = listRef.value
  if (!list) return
  const active = list.querySelector<HTMLElement>('.outline-entry.active')
    || list.querySelector<HTMLElement>('.outline-entry:last-child')
  if (!active) return
  const listBox = list.getBoundingClientRect()
  const rowBox = active.getBoundingClientRect()
  if (rowBox.top >= listBox.top && rowBox.bottom <= listBox.bottom) return
  list.scrollTop += rowBox.top - listBox.top - (listBox.height - rowBox.height) / 2
}

function handleKeydown(event: KeyboardEvent): void {
  if (!entries.value.length) return
  const last = entries.value.length - 1
  const current = cursorIndex.value >= 0
    ? cursorIndex.value
    : Math.max(0, entries.value.findIndex(entry => entry.anchorId === props.activeAnchorId))

  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const delta = event.key === 'ArrowDown' ? 1 : -1
    cursorIndex.value = Math.min(Math.max(current + delta, 0), last)
    scrollCursorIntoView()
    return
  }
  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    cursorIndex.value = event.key === 'Home' ? 0 : last
    scrollCursorIntoView()
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    const entry = entries.value[cursorIndex.value]
    if (!entry) return
    event.preventDefault()
    emit('jump', entry.anchorId)
  }
}

function scrollCursorIntoView(): void {
  const list = listRef.value
  const index = cursorIndex.value
  if (!list || index < 0) return
  const row = list.querySelectorAll<HTMLElement>('.outline-entry')[index]
  if (!row) return
  const listBox = list.getBoundingClientRect()
  const rowBox = row.getBoundingClientRect()
  if (rowBox.top < listBox.top) list.scrollTop -= listBox.top - rowBox.top
  else if (rowBox.bottom > listBox.bottom) list.scrollTop += rowBox.bottom - listBox.bottom
}

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
  width: min(360px, calc(100vw - 44px));
  max-height: min(62vh, 560px);
  flex-direction: column;
}

.outline-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  padding: 0 8px;
}

.outline-header strong { font-size: 13px; }

.outline-count { color: var(--app-text-muted); font-size: 10px; }

.outline-empty {
  margin: 0;
  padding: 18px 8px;
  color: var(--app-text-muted);
  font-size: 11px;
  text-align: center;
}

.outline-list {
  display: grid;
  gap: 1px;
  overflow-y: auto;
  padding-right: 2px;
  outline: none;
  scrollbar-width: thin;
}

/*
 * Every row is the same two lines so the list scans as a rhythm: a fixed
 * one-line result preview replaces the previous two-line clamp that made rows
 * with long answers several times taller than the rest.
 */
.outline-entry {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  align-items: start;
  gap: 9px;
  width: 100%;
  padding: 7px 8px 7px 4px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--app-transition-base);
}

.outline-entry:hover,
.outline-entry.cursor { background: color-mix(in srgb, var(--app-text) 5%, transparent); }

/* The reading position is the primary state; keyboard cursor only hints. */
.outline-entry.active {
  background: color-mix(in srgb, var(--app-text) 7%, transparent);
}

.outline-entry.active .outline-user { font-weight: 650; }

.outline-entry:focus-visible {
  outline: 2px solid var(--app-text);
  outline-offset: -2px;
}

.outline-rail {
  position: relative;
  display: flex;
  align-self: stretch;
  justify-content: center;
  padding-top: 5px;
}

/* A continuous rail turns the rows into a readable timeline of the session. */
.outline-rail::before {
  content: '';
  position: absolute;
  top: 14px;
  bottom: -8px;
  width: 1px;
  background: var(--app-divider);
}

.outline-entry:last-child .outline-rail::before { display: none; }

.outline-node {
  position: relative;
  z-index: 1;
  width: 6px;
  height: 6px;
  border: 1.5px solid var(--app-surface);
  border-radius: 50%;
  background: var(--app-text-muted);
  box-shadow: 0 0 0 1px var(--app-border-hover);
}

.outline-entry.active .outline-node {
  background: var(--app-text);
  box-shadow: 0 0 0 1px var(--app-text);
}

.outline-state-running .outline-node {
  background: var(--app-text);
  box-shadow: 0 0 0 1px var(--app-text);
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.outline-state-failed .outline-node {
  background: var(--app-diff-deletion);
  box-shadow: 0 0 0 1px var(--app-diff-deletion);
}

.outline-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.outline-user {
  overflow: hidden;
  color: var(--app-text);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.outline-result {
  overflow: hidden;
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.outline-result-empty { color: var(--app-text-placeholder); }

.outline-meta {
  display: grid;
  flex: 0 0 auto;
  gap: 1px;
  padding-top: 1px;
  justify-items: end;
  color: var(--app-text-placeholder);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
</style>
