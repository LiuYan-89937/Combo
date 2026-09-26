<template>
  <div class="conversation-outline" @keydown="handleKeydown">
    <header class="outline-header">
      <strong>{{ t('outline.title') }}</strong>
      <div class="outline-actions">
        <span class="outline-count">{{ t('outline.turnCount', { count: props.entries.length }) }}</span>
        <button type="button" class="outline-close" :aria-label="t('outline.close')" @click="emit('close')">×</button>
      </div>
    </header>

    <nav ref="listRef" class="outline-list" :aria-label="t('outline.title')">
      <button
        v-for="(entry, index) in props.entries"
        :key="entry.id"
        type="button"
        class="outline-turn"
        :class="{ active: isActiveTurn(entry) }"
        :aria-current="isActiveTurn(entry) ? 'location' : undefined"
        @click="emit('jump', entry.anchorId)"
      >
        <span class="outline-number">{{ t('outline.turnNumber', { count: index + 1 }) }}</span>
        <span class="outline-message">{{ entry.userMessage || t('outline.untitled') }}</span>
        <time class="outline-time" :datetime="entry.timestamp">{{ formattedTime(entry.timestamp) }}</time>
      </button>
      <p v-if="!props.entries.length" class="outline-empty">{{ t('outline.empty') }}</p>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import type { ConversationOutlineEntry } from '@/utils/conversationOutline'

const props = withDefaults(defineProps<{
  entries: ConversationOutlineEntry[]
  activeAnchorId?: string | null
}>(), {
  activeAnchorId: null,
})

const emit = defineEmits<{
  jump: [anchorId: string]
  close: []
}>()

const { locale, t } = useI18n()
const listRef = ref<HTMLElement | null>(null)

function isActiveTurn(entry: ConversationOutlineEntry): boolean {
  return props.activeAnchorId !== null && entry.anchorIds.includes(props.activeAnchorId)
}

watch(() => props.activeAnchorId, async () => {
  await nextTick()
  scrollActiveIntoView()
}, { immediate: true })

onMounted(async () => {
  await nextTick()
  scrollActiveIntoView()
})

function scrollActiveIntoView(): void {
  const list = listRef.value
  const active = list?.querySelector<HTMLElement>('.outline-turn.active')
  if (!list || !active) return
  const listBox = list.getBoundingClientRect()
  const rowBox = active.getBoundingClientRect()
  if (rowBox.top >= listBox.top && rowBox.bottom <= listBox.bottom) return
  list.scrollTop += rowBox.top - listBox.top - (listBox.height - rowBox.height) / 2
}

function handleKeydown(event: KeyboardEvent): void {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  if (!(event.target instanceof Node && listRef.value?.contains(event.target))) return
  const buttons = Array.from(listRef.value?.querySelectorAll<HTMLButtonElement>('button') ?? [])
  if (!buttons.length) return
  event.preventDefault()
  const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const index = event.key === 'Home' ? 0
    : event.key === 'End' ? buttons.length - 1
      : current < 0 ? (event.key === 'ArrowDown' ? 0 : buttons.length - 1)
        : Math.min(buttons.length - 1, Math.max(0, current + (event.key === 'ArrowDown' ? 1 : -1)))
  buttons[index]?.focus()
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
  width: 100%;
  max-height: min(70vh, 700px);
  flex-direction: column;
}

.outline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 16px;
  border-bottom: 1px solid var(--app-border);
}

.outline-header strong { font-size: 14px; }
.outline-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; }
.outline-count { color: var(--app-text-muted); font-size: 11px; }
.outline-close { width: 24px; height: 24px; border: 0; border-radius: var(--app-radius-sm); background: transparent; color: var(--app-text-muted); font: inherit; font-size: 18px; line-height: 1; cursor: pointer; }
.outline-close:hover { background: var(--app-surface-elevated); color: var(--app-text); }
.outline-close:focus-visible { outline: 2px solid var(--app-text); }

.outline-list {
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
  scrollbar-width: thin;
}

.outline-turn {
  display: grid;
  width: 100%;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: 10px;
  border: 0;
  border-radius: var(--app-radius-md);
  padding: 10px;
  background: transparent;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
}
.outline-turn + .outline-turn { margin-top: 2px; }
.outline-turn.active { background: color-mix(in srgb, var(--app-text) 7%, transparent); }
.outline-turn:hover { background: color-mix(in srgb, var(--app-text) 5%, transparent); }
.outline-turn:focus-visible { outline: 2px solid var(--app-text); outline-offset: -2px; }
.outline-number, .outline-time { color: var(--app-text-muted); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.outline-message {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
  font-size: 13px;
  line-height: 1.45;
}
.outline-empty { margin: 0; padding: 18px 8px; color: var(--app-text-muted); font-size: 12px; text-align: center; }
</style>
