<template>
  <div class="git-file-row" :title="file.path">
    <span class="change-code">{{ changeCode }}</span>
    <span class="file-path">{{ file.path }}</span>
    <span class="line-count"><b>+{{ file.additions }}</b><i>-{{ file.deletions }}</i></span>
    <button type="button" :title="action === 'stage' ? t('sourceControl.stage') : t('sourceControl.unstage')" @click="$emit('action')">
      {{ action === 'stage' ? '+' : '−' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { GitFileStatus } from '@/api/git'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ file: GitFileStatus; action: 'stage' | 'unstage' }>()
defineEmits<{ action: [] }>()
const { t } = useI18n()
const changeCode = computed(() => ({
  added: 'A', modified: 'M', deleted: 'D', renamed: 'R', copied: 'C', type_changed: 'T', conflicted: '!',
})[props.file.change_type] || 'M')
</script>

<style scoped>
.git-file-row { min-width: 0; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto 28px; align-items: center; gap: 6px; min-height: 30px; padding-left: 3px; border-radius: 9px; color: var(--app-text-secondary); }.git-file-row:hover { background: color-mix(in srgb, var(--app-text) 5%, transparent); }.change-code { color: var(--app-text-muted); font: 10px/1 var(--app-font-mono); text-align: center; }.file-path { min-width: 0; overflow: hidden; font: 10px/1.3 var(--app-font-mono); text-overflow: ellipsis; white-space: nowrap; }.line-count { display: inline-flex; gap: 5px; font: 9px/1 var(--app-font-mono); }.line-count b { color: var(--app-diff-addition); }.line-count i { color: var(--app-diff-deletion); font-style: normal; }.git-file-row button { width: 26px; height: 26px; padding: 0; border: 0; border-radius: 8px; color: var(--app-text); background: transparent; cursor: pointer; }.git-file-row button:hover { background: color-mix(in srgb, var(--app-text) 8%, transparent); }
</style>
