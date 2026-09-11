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
        <button type="button" class="capsule-action" :disabled="applyingChanges" @click="confirmApply">
          {{ applyActionLabel }}
        </button>
        <button type="button" class="capsule-action primary" @click="openReview()">
          {{ t('git.review') }}
        </button>
      </span>
    </div>

    <div class="git-change-files">
      <div
        v-for="file in visibleFiles"
        :key="file.path"
        class="file-row"
      >
        <button
          type="button"
          class="file-row-main"
          :title="file.path"
          @click="openReview(file.path)"
        >
          <span class="file-name">
            <span class="file-path">{{ basename(file.path) }}</span>
            <small v-if="dirname(file.path)" class="file-dir">{{ dirname(file.path) }}</small>
          </span>
        </button>
        <!-- Binary rows cannot show line counts, so the slot offers a way to
             actually open the file instead of only labelling it as binary. -->
        <FileOpenMenu v-if="file.binary" :path="nativePath(file.path)" />
        <span v-else class="file-lines">
          <b v-if="file.additions" :title="t('git.linesAdded', { count: file.additions })">+{{ file.additions }}</b>
          <i v-if="file.deletions" :title="t('git.linesRemoved', { count: file.deletions })">-{{ file.deletions }}</i>
          <span v-if="!file.additions && !file.deletions" class="file-lines-none" :title="t('git.linesUnchanged')">—</span>
        </span>
      </div>
      <button
        v-if="changes.files.length > COLLAPSED_FILE_LIMIT"
        type="button"
        class="file-list-toggle"
        :aria-expanded="filesExpanded"
        @click="filesExpanded = !filesExpanded"
      >
        {{ filesExpanded ? t('git.collapseFiles') : t('git.showAllFiles', { count: changes.files.length }) }}
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
      </header>

      <div
        ref="workspaceEl"
        class="git-review-workspace"
        :style="{ '--review-file-list-width': `${fileListWidth}px` }"
      >
        <aside class="review-file-list" role="tablist" :aria-label="t('git.changedFilesLabel')">
          <div
            v-for="file in changes.files"
            :key="file.path"
            class="review-file-row"
            :class="{ active: selectedPath === file.path }"
          >
            <button
              type="button"
              role="tab"
              class="review-file-main"
              :aria-selected="selectedPath === file.path"
              @click="selectFile(file.path)"
            >
              <span class="review-file-copy">
                <strong>{{ basename(file.path) }}</strong>
                <small v-if="dirname(file.path)" class="file-dir">{{ dirname(file.path) }}</small>
              </span>
              <span v-if="!file.binary" class="file-lines">
                <b v-if="file.additions">+{{ file.additions }}</b>
                <i v-if="file.deletions">-{{ file.deletions }}</i>
                <span v-if="!file.additions && !file.deletions" class="file-lines-none">—</span>
              </span>
            </button>
            <FileOpenMenu v-if="file.binary" :path="nativePath(file.path)" />
          </div>
        </aside>

        <div
          class="review-splitter"
          role="separator"
          aria-orientation="vertical"
          :aria-label="t('git.resizeFileList')"
          :aria-valuenow="Math.round(fileListWidth)"
          :aria-valuemin="FILE_LIST_MIN_WIDTH"
          :aria-valuemax="fileListMaxWidth"
          tabindex="0"
          @pointerdown="startResize"
          @keydown="handleSplitterKeydown"
          @dblclick="resetFileListWidth"
        />

        <section class="git-review-content">
          <div class="git-review-path" :title="selectedPath">{{ selectedPath }}</div>
          <GitDiffViewer
            :diff="selectedDiff"
            :loading="diffLoading"
            :error="diffError"
            :native-path="selectedDiff?.binary ? nativePath(selectedPath) : ''"
          />
        </section>
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NModal, useDialog, useMessage } from 'naive-ui'
import { gitApi, type GitFileDiff, type GitTurnChanges } from '@/api/git'
import { useI18n } from '@/composables/useI18n'
import GitDiffViewer from '@/components/chat/GitDiffViewer.vue'
import FileOpenMenu from '@/components/common/FileOpenMenu.vue'
import { joinNativePath } from '@/utils/nativePath'

const FILE_LIST_DEFAULT_WIDTH = 260
const FILE_LIST_MIN_WIDTH = 180
// 右侧差异区保留的最小宽度，决定左栏能被拖多宽。
const FILE_LIST_CONTENT_MIN_WIDTH = 320
const SPLITTER_WIDTH = 12
const FILE_LIST_WIDTH_STORAGE_KEY = 'combo.gitReviewFileListWidth'

const props = defineProps<{ changes: GitTurnChanges }>()
const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const reviewOpen = ref(false)
const filesExpanded = ref(false)
const COLLAPSED_FILE_LIMIT = 10
const selectedPath = ref('')
const selectedDiff = ref<GitFileDiff | null>(null)
const diffLoading = ref(false)
const diffError = ref('')
const applyingChanges = ref(false)
const reverted = ref(false)
const visibleFiles = computed(() => (
  filesExpanded.value ? props.changes.files : props.changes.files.slice(0, COLLAPSED_FILE_LIMIT)
))
const applyActionLabel = computed(() => {
  if (applyingChanges.value) return reverted.value ? t('git.reapplying') : t('git.reverting')
  return reverted.value ? t('git.reapply') : t('git.revert')
})
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

// 左栏宽度可拖动调整；拖动只在当前会话内即时生效，松手后写入本地偏好。
const workspaceEl = ref<HTMLElement | null>(null)
const fileListWidth = ref(readStoredFileListWidth())
const fileListMaxWidth = ref(FILE_LIST_DEFAULT_WIDTH)
let resizing = false

function readStoredFileListWidth(): number {
  if (typeof window === 'undefined') return FILE_LIST_DEFAULT_WIDTH
  const value = Number(window.localStorage.getItem(FILE_LIST_WIDTH_STORAGE_KEY))
  return Number.isFinite(value) && value > 0 ? value : FILE_LIST_DEFAULT_WIDTH
}

function maximumFileListWidth(): number {
  const width = workspaceEl.value?.clientWidth ?? 0
  if (!width) return fileListMaxWidth.value
  return Math.max(
    FILE_LIST_MIN_WIDTH,
    Math.round(width - SPLITTER_WIDTH - FILE_LIST_CONTENT_MIN_WIDTH),
  )
}

function applyFileListWidth(value: number): void {
  fileListMaxWidth.value = maximumFileListWidth()
  fileListWidth.value = Math.min(
    Math.max(Math.round(value), FILE_LIST_MIN_WIDTH),
    fileListMaxWidth.value,
  )
}

function persistFileListWidth(): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(FILE_LIST_WIDTH_STORAGE_KEY, String(fileListWidth.value))
}

function startResize(event: PointerEvent): void {
  if (event.button !== 0) return
  event.preventDefault()
  resizing = true
  window.addEventListener('pointermove', handleResizeMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function handleResizeMove(event: PointerEvent): void {
  if (!resizing) return
  const rect = workspaceEl.value?.getBoundingClientRect()
  if (!rect) return
  applyFileListWidth(event.clientX - rect.left)
}

function stopResize(): void {
  if (!resizing) return
  resizing = false
  window.removeEventListener('pointermove', handleResizeMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
  persistFileListWidth()
}

function resetFileListWidth(): void {
  applyFileListWidth(FILE_LIST_DEFAULT_WIDTH)
  persistFileListWidth()
}

function handleSplitterKeydown(event: KeyboardEvent): void {
  const step = event.shiftKey ? 48 : 16
  if (event.key === 'ArrowLeft') applyFileListWidth(fileListWidth.value - step)
  else if (event.key === 'ArrowRight') applyFileListWidth(fileListWidth.value + step)
  else if (event.key === 'Home') applyFileListWidth(FILE_LIST_MIN_WIDTH)
  else if (event.key === 'End') applyFileListWidth(fileListMaxWidth.value)
  else return
  event.preventDefault()
  persistFileListWidth()
}

function handleWindowResize(): void {
  applyFileListWidth(fileListWidth.value)
}

// 弹窗打开后容器才有尺寸，此时才能算出有效的最大宽度。
watch(reviewOpen, (open) => {
  if (open) void nextTick(() => applyFileListWidth(fileListWidth.value))
})

onMounted(() => window.addEventListener('resize', handleWindowResize))
onBeforeUnmount(() => {
  stopResize()
  window.removeEventListener('resize', handleWindowResize)
})

function confirmApply() {
  const reapply = reverted.value
  dialog.warning({
    title: t(reapply ? 'git.reapplyTitle' : 'git.revertTitle'),
    content: t(reapply ? 'git.reapplyDescription' : 'git.revertDescription'),
    positiveText: t(reapply ? 'git.reapply' : 'git.revert'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => applyTurn(reapply ? 'reapply' : 'revert'),
  })
}

async function applyTurn(direction: 'revert' | 'reapply') {
  applyingChanges.value = true
  try {
    const result = direction === 'revert'
      ? await gitApi.revertTurn(props.changes.repository_root, props.changes.request_id)
      : await gitApi.reapplyTurn(props.changes.repository_root, props.changes.request_id)
    if (!result.applied) {
      dialog.warning({
        title: t('git.revertConflictTitle'),
        content: t('git.revertConflictDescription', { count: result.conflicting_files.length }),
        positiveText: t('git.acknowledge'),
      })
      return
    }
    reverted.value = direction === 'revert'
    message.success(t(direction === 'revert' ? 'git.revertComplete' : 'git.reapplyComplete'))
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    applyingChanges.value = false
  }
}

function basename(path: string): string {
  return path.split('/').at(-1) || path
}

function dirname(path: string): string {
  const parts = path.split('/')
  parts.pop()
  return parts.join('/')
}

/** Absolute native path, needed to hand a repository file to a system app. */
function nativePath(path: string): string {
  return joinNativePath(props.changes.repository_root, path)
}

</script>

<style scoped>
.git-change-capsule { min-width: 0; margin-top: 18px; overflow: hidden; border: 1px solid var(--app-border); border-radius: var(--app-radius-lg); background: var(--app-surface); box-shadow: var(--app-shadow-sm); }
.git-change-summary { min-height: 72px; display: flex; align-items: center; gap: 14px; padding: 12px 14px; }
.git-change-mark { width: 46px; height: 46px; flex: 0 0 auto; display: grid; place-items: center; overflow: hidden; border-radius: var(--app-radius-md); background: var(--app-text); }
.git-change-mark img { width: 34px; height: 34px; object-fit: contain; filter: var(--app-brand-mark-on-inverse-filter); }
.git-change-copy { min-width: 0; display: grid; gap: 4px; }
.git-change-copy strong { font-size: 15px; color: var(--app-text-strong); }
.git-change-lines, .file-lines, .review-total { display: inline-flex; align-items: center; gap: 7px; font: 12px/1.3 var(--app-font-mono); }
.git-change-lines b, .file-lines b, .review-total b { color: var(--app-diff-addition); font-style: normal; }
.git-change-lines i, .file-lines i, .review-total i { color: var(--app-diff-deletion); font-style: normal; }
.git-change-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.capsule-action { min-height: 36px; padding: 0 16px; border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); background: var(--app-surface); color: var(--app-text); font: inherit; cursor: pointer; }
.capsule-action.primary { border-color: var(--app-text); background: var(--app-text); color: var(--app-text-inverse); }
.capsule-action:disabled { cursor: default; opacity: .45; }
.git-change-files { display: grid; border-top: 1px solid var(--app-border); }
/* 行本身是容器而非按钮：二进制行右侧要放「打开方式」下拉，按钮不能嵌套按钮。 */
.git-change-files .file-row { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 8px 18px; border-bottom: 1px solid var(--app-divider); color: var(--app-text-secondary); }
.git-change-files .file-row:last-child { border-bottom: 0; }
.git-change-files .file-row:hover { background: var(--app-surface-hover); }
.git-change-files .file-row-main { min-width: 0; display: block; padding: 3px 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.git-change-files .file-list-toggle { display: flex; align-items: center; justify-content: center; padding: 11px 18px; border: 0; border-bottom: 1px solid var(--app-divider); background: transparent; color: var(--app-text-muted); font: 11px/1.4 var(--app-font-sans); text-align: center; cursor: pointer; }
.git-change-files .file-list-toggle:hover { background: var(--app-surface-hover); }
.file-name { min-width: 0; display: flex; align-items: baseline; gap: 6px; }
.file-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: 12px/1.5 var(--app-font-mono); }
.file-dir { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--app-text-muted); font: 10px/1.5 var(--app-font-mono); }
.file-lines-none { color: var(--app-text-muted); }
.git-change-files .file-lines, .review-file-list .file-lines { justify-self: end; }
.git-change-files .file-list-toggle { display: flex; align-items: center; justify-content: center; color: var(--app-text-muted); font: 11px/1.4 var(--app-font-sans); text-align: center; }
.git-change-capsule.reverted { opacity: .7; }
:global(.git-review-modal) { width: min(1400px, calc(100vw - 40px)); max-width: calc(100vw - 40px); max-height: calc(100vh - 40px); display: flex; flex-direction: column; overflow: hidden; border-radius: var(--app-radius-xl); }
:global(.git-review-modal .n-card-header) { flex: 0 0 auto; }
:global(.git-review-modal .n-card__content) { min-width: 0; min-height: 0; flex: 1 1 auto; overflow: hidden; padding: 0 20px 20px; }
.git-review-shell { width: 100%; min-width: 0; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; overflow: hidden; }
.git-review-toolbar { display: flex; align-items: center; min-width: 0; }
.review-total { flex: 0 0 auto; padding: 9px 13px; border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); color: var(--app-text-secondary); }
.git-review-workspace { height: clamp(360px, 65vh, 680px); max-height: calc(100vh - 190px); min-width: 0; min-height: 0; display: grid; grid-template-columns: var(--review-file-list-width, 260px) 12px minmax(0, 1fr); align-items: stretch; gap: 0; overflow: hidden; }
/* 左右分栏之间的可拖拽分隔条：命中区域宽 12px，视觉上是一条细线。 */
.review-splitter { position: relative; min-width: 0; cursor: col-resize; touch-action: none; }
.review-splitter::before { content: ''; position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; background: var(--app-border); transform: translateX(-50%); transition: background .15s var(--app-transition-fast); }
.review-splitter:hover::before, .review-splitter:focus-visible::before { width: 3px; border-radius: var(--app-radius-pill); background: var(--app-text-muted); }
.review-splitter:focus-visible { outline: none; }
.review-file-list { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 4px; padding: 5px; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; border: 1px solid var(--app-border); border-radius: var(--app-radius-lg); background: var(--app-surface-muted); }
.review-file-list .review-file-row { min-width: 0; flex: 0 0 auto; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 8px 9px; border-radius: var(--app-radius-md); color: var(--app-text-secondary); }
.review-file-list .review-file-row:hover { background: var(--app-surface-hover); }
.review-file-list .review-file-row.active { background: var(--app-surface); color: var(--app-text-strong); }
.review-file-list .review-file-main { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 2px 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.review-file-copy { min-width: 0; display: grid; gap: 2px; }
.review-file-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.review-file-copy strong { font: 11px/1.35 var(--app-font-mono); }
.git-review-content { min-width: 0; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; border: 1px solid var(--app-border); border-radius: var(--app-radius-lg); background: var(--app-surface); }
.git-review-path { overflow: hidden; padding: 11px 14px; border-bottom: 1px solid var(--app-border); color: var(--app-text-muted); font: 11px/1.4 var(--app-font-mono); text-overflow: ellipsis; white-space: nowrap; }
.git-review-content :deep(.git-diff-viewer) { border: 0; border-radius: 0; }
@media (max-width: 820px) { .git-change-summary { align-items: flex-start; flex-wrap: wrap; }.git-change-actions { width: 100%; margin-left: 60px; }.git-review-workspace { grid-template-columns: 1fr; grid-template-rows: minmax(110px, 26%) minmax(0, 1fr); }.review-splitter { display: none; }.review-file-list { display: grid; grid-auto-rows: min-content; } }
</style>
