<template>
  <div v-if="loading" class="git-diff-viewer git-diff-state">{{ t('git.loadingDiff') }}</div>
  <div v-else-if="error" class="git-diff-viewer git-diff-state error">{{ error }}</div>
  <div v-else-if="diff?.binary" class="git-diff-viewer git-diff-state">{{ t('git.binaryDiff') }}</div>
  <div v-else class="git-diff-viewer side-by-side-diff">
    <div class="diff-head">
      <span>{{ t('git.before') }}</span>
      <span>{{ t('git.after') }}</span>
    </div>
    <div class="diff-scroll">
      <div
        v-for="row in diffRows"
        :key="row.key"
        class="diff-row"
        :class="row.kind"
      >
        <span class="line-number">{{ row.oldLineNumber || '' }}</span>
        <code class="line old" :class="{ empty: row.oldText === null }">{{ row.oldText ?? '' }}</code>
        <span class="line-number">{{ row.newLineNumber || '' }}</span>
        <code class="line new" :class="{ empty: row.newText === null }">{{ row.newText ?? '' }}</code>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { GitFileDiff } from '@/api/git'
import { useI18n } from '@/composables/useI18n'
import { buildSideBySideDiff } from '@/utils/sideBySideDiff'

const props = withDefaults(defineProps<{
  diff: GitFileDiff | null
  loading?: boolean
  error?: string
}>(), {
  loading: false,
  error: '',
})
const { t } = useI18n()
const diffRows = computed(() => props.diff
  ? buildSideBySideDiff(props.diff.old_content, props.diff.new_content)
  : [])
</script>

<style scoped>
.git-diff-viewer { width: 100%; height: 100%; min-width: 0; min-height: 0; }
.side-by-side-diff { display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; border: 1px solid var(--app-border); border-radius: 22px; background: var(--app-surface); }
.diff-head { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); padding: 11px 50px; border-bottom: 1px solid var(--app-border); color: var(--app-text-muted); font: 11px/1.2 var(--app-font-mono); }
.diff-scroll { min-width: 0; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; }
.diff-row { min-width: 0; display: grid; grid-template-columns: 44px minmax(0, 1fr) 44px minmax(0, 1fr); align-items: stretch; }
.line-number { padding: 2px 10px; border-right: 1px solid var(--app-divider); color: var(--app-text-disabled); background: var(--app-surface-muted); font: 11px/1.55 var(--app-font-mono); text-align: right; user-select: none; }
.line { position: relative; min-width: 0; min-height: 21px; display: block; padding: 2px 12px 2px 25px; overflow-wrap: anywhere; border-right: 1px solid var(--app-divider); color: var(--app-text); font: 12px/1.55 var(--app-font-mono); white-space: pre-wrap; word-break: break-word; }
.diff-row.changed .line.old:not(.empty) { background: var(--app-diff-deletion-surface); }
.diff-row.changed .line.new:not(.empty) { background: var(--app-diff-addition-surface); }
.diff-row.changed .line.old:not(.empty)::before,
.diff-row.changed .line.new:not(.empty)::before { position: absolute; left: 9px; font-weight: 700; }
.diff-row.changed .line.old:not(.empty)::before { content: '-'; color: var(--app-diff-deletion); }
.diff-row.changed .line.new:not(.empty)::before { content: '+'; color: var(--app-diff-addition); }
.diff-row.changed .line.empty { background: var(--app-surface-muted); }
.git-diff-state { display: grid; place-items: center; overflow: hidden; border: 1px solid var(--app-border); border-radius: 22px; color: var(--app-text-muted); }
.git-diff-state.error { color: var(--app-error); }
</style>
