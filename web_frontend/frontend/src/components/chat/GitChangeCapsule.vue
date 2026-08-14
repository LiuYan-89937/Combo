<template>
  <section class="git-change-capsule" :class="{ reverted }">
    <div class="git-change-summary">
      <span class="git-change-mark" aria-hidden="true">
        <img src="/brand/combo/ui-icons/empty-workspace.png" alt="" />
      </span>
      <span class="git-change-copy">
        <strong>{{ reverted ? t('git.changesReverted') : t('git.changedFiles', { count: changes.files.length }) }}</strong>
        <span v-if="!reverted" class="git-change-lines">
          <b>+{{ changes.additions }}</b>
          <i>-{{ changes.deletions }}</i>
        </span>
      </span>
      <span class="git-change-actions">
        <button type="button" class="capsule-action" :disabled="reverting || reverted" @click="confirmRevert">
          {{ reverting ? t('git.reverting') : t('git.revert') }}
        </button>
        <button type="button" class="capsule-action primary" @click="openReview()">
          {{ t('git.review') }}
        </button>
      </span>
    </div>

    <div class="git-change-files">
      <button
        v-for="file in changes.files"
        :key="file.path"
        type="button"
        @click="openReview(file.path)"
      >
        <span class="file-state">{{ changeCode(file.change_type) }}</span>
        <span class="file-path">{{ file.path }}</span>
        <span class="file-lines"><b>+{{ file.additions }}</b><i>-{{ file.deletions }}</i></span>
      </button>
    </div>
  </section>

  <n-modal
    v-model:show="reviewOpen"
    preset="card"
    class="git-review-modal"
    :title="t('git.reviewTitle')"
    :bordered="false"
  >
    <div class="git-review-shell">
      <header class="git-review-toolbar">
        <span class="review-total">
          {{ t('git.changedFiles', { count: changes.files.length }) }}
          <b>+{{ changes.additions }}</b>
          <i>-{{ changes.deletions }}</i>
        </span>
        <div class="review-file-pills" role="tablist" :aria-label="t('git.changedFilesLabel')">
          <button
            v-for="file in changes.files"
            :key="file.path"
            type="button"
            role="tab"
            :aria-selected="selectedPath === file.path"
            :class="{ active: selectedPath === file.path }"
            @click="selectFile(file.path)"
          >
            <span>{{ changeCode(file.change_type) }}</span>
            {{ basename(file.path) }}
          </button>
        </div>
      </header>

      <div class="git-review-path" :title="selectedPath">{{ selectedPath }}</div>

      <div v-if="diffLoading" class="git-diff-state">{{ t('git.loadingDiff') }}</div>
      <div v-else-if="diffError" class="git-diff-state error">{{ diffError }}</div>
      <div v-else-if="selectedDiff?.binary" class="git-diff-state">{{ t('git.binaryDiff') }}</div>
      <div v-else class="side-by-side-diff">
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
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NModal, useDialog, useMessage } from 'naive-ui'
import { gitApi, type GitChangeType, type GitFileDiff, type GitTurnChanges } from '@/api/git'
import { useI18n } from '@/composables/useI18n'
import { buildSideBySideDiff } from '@/utils/sideBySideDiff'

const props = defineProps<{ changes: GitTurnChanges }>()
const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const reviewOpen = ref(false)
const selectedPath = ref('')
const selectedDiff = ref<GitFileDiff | null>(null)
const diffLoading = ref(false)
const diffError = ref('')
const reverting = ref(false)
const reverted = ref(false)
const diffRows = computed(() => selectedDiff.value
  ? buildSideBySideDiff(selectedDiff.value.old_content, selectedDiff.value.new_content)
  : [])

function openReview(path?: string) {
  reviewOpen.value = true
  void selectFile(path || props.changes.files[0]?.path || '')
}

async function selectFile(path: string) {
  if (!path) return
  selectedPath.value = path
  selectedDiff.value = null
  diffError.value = ''
  diffLoading.value = true
  try {
    selectedDiff.value = await gitApi.fileDiff(
      props.changes.repository_root,
      props.changes.request_id,
      path,
    )
  } catch (error) {
    diffError.value = error instanceof Error ? error.message : String(error)
  } finally {
    diffLoading.value = false
  }
}

function confirmRevert() {
  dialog.warning({
    title: t('git.revertTitle'),
    content: t('git.revertDescription'),
    positiveText: t('git.revert'),
    negativeText: t('common.cancel'),
    onPositiveClick: revertChanges,
  })
}

async function revertChanges() {
  reverting.value = true
  try {
    const result = await gitApi.revertTurn(props.changes.repository_root, props.changes.request_id)
    if (!result.reverted) {
      dialog.warning({
        title: t('git.revertConflictTitle'),
        content: t('git.revertConflictDescription', { count: result.conflicting_files.length }),
        positiveText: t('git.acknowledge'),
      })
      return
    }
    reverted.value = true
    message.success(t('git.revertComplete'))
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    reverting.value = false
  }
}

function basename(path: string): string {
  return path.split('/').at(-1) || path
}

function changeCode(type: GitChangeType): string {
  return ({ added: 'A', modified: 'M', deleted: 'D', renamed: 'R', copied: 'C', type_changed: 'T', conflicted: '!' })[type] || 'M'
}
</script>

<style scoped>
.git-change-capsule { margin-top: 18px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 22px; background: var(--app-surface); box-shadow: var(--app-shadow-sm); }
.git-change-summary { min-height: 72px; display: flex; align-items: center; gap: 14px; padding: 12px 14px; }
.git-change-mark { width: 46px; height: 46px; flex: 0 0 auto; display: grid; place-items: center; overflow: hidden; border-radius: 15px; background: var(--app-text); }
.git-change-mark img { width: 34px; height: 34px; object-fit: contain; filter: var(--app-brand-mark-on-inverse-filter); }
.git-change-copy { min-width: 0; display: grid; gap: 4px; }
.git-change-copy strong { font-size: 15px; color: var(--app-text-strong); }
.git-change-lines, .file-lines, .review-total { display: inline-flex; align-items: center; gap: 7px; font: 12px/1.3 var(--app-font-mono); }
.git-change-lines b, .file-lines b, .review-total b { color: var(--app-success); font-style: normal; }
.git-change-lines i, .file-lines i, .review-total i { color: var(--app-error); font-style: normal; }
.git-change-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.capsule-action { min-height: 36px; padding: 0 16px; border: 1px solid var(--app-border); border-radius: 999px; background: var(--app-surface); color: var(--app-text); font: inherit; cursor: pointer; }
.capsule-action.primary { border-color: var(--app-text); background: var(--app-text); color: var(--app-text-inverse); }
.capsule-action:disabled { cursor: default; opacity: .45; }
.git-change-files { display: grid; border-top: 1px solid var(--app-border); }
.git-change-files button { min-width: 0; display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 11px 18px; border: 0; border-bottom: 1px solid var(--app-divider); background: transparent; color: var(--app-text-secondary); text-align: left; cursor: pointer; }
.git-change-files button:last-child { border-bottom: 0; }.git-change-files button:hover { background: var(--app-surface-hover); }
.file-state { font: 11px/1 var(--app-font-mono); color: var(--app-text-muted); }.file-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: 12px/1.5 var(--app-font-mono); }
.git-change-capsule.reverted { opacity: .7; }
:global(.git-review-modal) { width: min(1400px, calc(100vw - 40px)); height: min(880px, calc(100vh - 40px)); border-radius: 28px; }
:global(.git-review-modal .n-card__content) { min-height: 0; padding: 0 20px 20px; }
.git-review-shell { height: 100%; min-height: 0; display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 12px; }
.git-review-toolbar { display: flex; align-items: center; gap: 14px; min-width: 0; }
.review-total { flex: 0 0 auto; padding: 9px 13px; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text-secondary); }
.review-file-pills { min-width: 0; display: flex; gap: 7px; overflow-x: auto; scrollbar-width: none; }
.review-file-pills button { display: inline-flex; align-items: center; gap: 7px; flex: 0 0 auto; padding: 9px 13px; border: 1px solid var(--app-border); border-radius: 999px; background: var(--app-surface); color: var(--app-text-secondary); cursor: pointer; }
.review-file-pills button span { font: 10px/1 var(--app-font-mono); }.review-file-pills button.active { border-color: var(--app-text); background: var(--app-text); color: var(--app-text-inverse); }
.git-review-path { overflow: hidden; padding: 0 5px; color: var(--app-text-muted); font: 11px/1.4 var(--app-font-mono); text-overflow: ellipsis; white-space: nowrap; }
.side-by-side-diff { min-height: 0; overflow: hidden; border: 1px solid var(--app-border); border-radius: 22px; background: var(--app-surface); }
.diff-head { display: grid; grid-template-columns: 1fr 1fr; padding: 11px 52px; border-bottom: 1px solid var(--app-border); color: var(--app-text-muted); font: 11px/1.2 var(--app-font-mono); }
.diff-scroll { height: calc(100% - 38px); overflow: auto; }
.diff-row { min-width: 900px; display: grid; grid-template-columns: 50px minmax(380px, 1fr) 50px minmax(380px, 1fr); }
.line-number { padding: 2px 10px; border-right: 1px solid var(--app-divider); color: var(--app-text-disabled); background: var(--app-surface-muted); font: 11px/1.55 var(--app-font-mono); text-align: right; user-select: none; }
.line { min-height: 21px; display: block; padding: 2px 12px; border-right: 1px solid var(--app-divider); color: var(--app-text); font: 12px/1.55 var(--app-font-mono); white-space: pre; }
.diff-row.changed .line.old:not(.empty) { background: color-mix(in srgb, var(--app-error) 11%, var(--app-surface)); }.diff-row.changed .line.new:not(.empty) { background: color-mix(in srgb, var(--app-success) 11%, var(--app-surface)); }
.diff-row.changed .line.empty { background: var(--app-surface-muted); }
.git-diff-state { min-height: 280px; display: grid; place-items: center; border: 1px solid var(--app-border); border-radius: 22px; color: var(--app-text-muted); }.git-diff-state.error { color: var(--app-error); }
@media (max-width: 720px) { .git-change-summary { align-items: flex-start; flex-wrap: wrap; }.git-change-actions { width: 100%; margin-left: 60px; }.git-review-toolbar { align-items: flex-start; flex-direction: column; }.review-file-pills { width: 100%; } }
</style>
