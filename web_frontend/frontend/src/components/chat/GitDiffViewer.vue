<template>
  <div v-if="loading" class="git-diff-viewer git-diff-state">{{ t('git.loadingDiff') }}</div>
  <div v-else-if="error" class="git-diff-viewer git-diff-state error">{{ error }}</div>
  <div v-else-if="diff?.binary" class="git-diff-viewer git-diff-state">{{ t('git.binaryDiff') }}</div>
  <div v-else class="git-diff-viewer unified-diff">
    <div v-if="hasGaps" class="git-diff-toolbar">
      <span class="git-diff-toolbar-text">
        {{ hiddenLineCount ? t('git.hiddenLinesTotal', { count: hiddenLineCount }) : t('git.allLinesShown') }}
      </span>
      <button type="button" class="git-diff-toolbar-action" @click="toggleAllGaps">
        {{ allExpanded ? t('git.collapseUnchanged') : t('git.expandAll') }}
      </button>
    </div>
    <div ref="host" class="diff-editor-host" />
    <p v-if="diff?.truncated" class="git-diff-truncated">{{ t('git.diffTruncated') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution'
import 'monaco-editor/esm/vs/basic-languages/csharp/csharp.contribution'
import 'monaco-editor/esm/vs/basic-languages/css/css.contribution'
import 'monaco-editor/esm/vs/basic-languages/dockerfile/dockerfile.contribution'
import 'monaco-editor/esm/vs/basic-languages/go/go.contribution'
import 'monaco-editor/esm/vs/basic-languages/html/html.contribution'
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution'
import 'monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution'
import 'monaco-editor/esm/vs/language/json/monaco.contribution'
import 'monaco-editor/esm/vs/basic-languages/kotlin/kotlin.contribution'
import 'monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution'
import 'monaco-editor/esm/vs/basic-languages/php/php.contribution'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import 'monaco-editor/esm/vs/basic-languages/ruby/ruby.contribution'
import 'monaco-editor/esm/vs/basic-languages/rust/rust.contribution'
import 'monaco-editor/esm/vs/basic-languages/shell/shell.contribution'
import 'monaco-editor/esm/vs/basic-languages/sql/sql.contribution'
import 'monaco-editor/esm/vs/basic-languages/swift/swift.contribution'
import 'monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution'
import 'monaco-editor/esm/vs/basic-languages/xml/xml.contribution'
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution'
import type { GitFileDiff } from '@/api/git'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import {
  buildUnifiedDiff,
  collapseUnifiedDiff,
  type UnifiedDiffBlock,
  type UnifiedDiffRow,
} from '@/utils/unifiedDiff'

/** 折叠区在编辑器里占一行，行号留空。 */
interface GapRow {
  kind: 'gap'
  blockIndex: number
  hiddenCount: number
}

type DisplayRow = UnifiedDiffRow | GapRow

const props = withDefaults(defineProps<{
  diff: GitFileDiff | null
  loading?: boolean
  error?: string
}>(), {
  loading: false,
  error: '',
})
const { t } = useI18n()
const uiStore = useUiStore()
const host = ref<HTMLElement | null>(null)
const editorTheme = computed(() => uiStore.actualTheme === 'dark' ? 'vs-dark' : 'vs')
const expandedGaps = ref<Set<number>>(new Set())
const blocks = computed<UnifiedDiffBlock[]>(() => (
  props.diff
    ? collapseUnifiedDiff(buildUnifiedDiff(props.diff.old_content ?? '', props.diff.new_content ?? ''))
    : []
))
const displayRows = computed<DisplayRow[]>(() => {
  const rows: DisplayRow[] = []
  blocks.value.forEach((block, blockIndex) => {
    if (block.kind === 'rows' || expandedGaps.value.has(blockIndex)) {
      rows.push(...block.rows)
      return
    }
    rows.push({ kind: 'gap', blockIndex, hiddenCount: block.rows.length })
  })
  return rows
})
const hiddenLineCount = computed(() => blocks.value.reduce(
  (total, block, blockIndex) => (
    block.kind === 'gap' && !expandedGaps.value.has(blockIndex) ? total + block.rows.length : total
  ),
  0,
))
const hasGaps = computed(() => blocks.value.some(block => block.kind === 'gap'))
const allExpanded = computed(() => hiddenLineCount.value === 0)
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let model: monaco.editor.ITextModel | null = null
let decorations: monaco.editor.IEditorDecorationsCollection | null = null

self.MonacoEnvironment = {
  getWorker: (_moduleId, label) => (
    label === 'json' ? new JsonWorker() : new EditorWorker()
  ),
}

watch(host, (element) => {
  disposeEditor()
  if (!element) return
  editor = monaco.editor.create(element, {
    theme: editorTheme.value,
    automaticLayout: true,
    readOnly: true,
    minimap: { enabled: false },
    overviewRulerLanes: 0,
    hideCursorInOverviewRuler: true,
    overviewRulerBorder: false,
    fontFamily: "'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace",
    fontSize: 12,
    lineHeight: 20,
    lineNumbers: lineNumber => {
      const row = displayRows.value[lineNumber - 1]
      return row && row.kind !== 'gap' ? String(row.lineNumber) : ''
    },
    lineNumbersMinChars: 4,
    glyphMargin: false,
    folding: false,
    lineDecorationsWidth: 14,
    padding: { top: 10, bottom: 10 },
    scrollBeyondLastLine: false,
    scrollBeyondLastColumn: 4,
    wordWrap: 'off',
    stickyScroll: { enabled: false },
    scrollbar: {
      horizontal: 'auto',
      vertical: 'auto',
      horizontalScrollbarSize: 9,
      verticalScrollbarSize: 9,
      useShadows: false,
      alwaysConsumeMouseWheel: false,
    },
  })
  // 折叠区整行可点，点击即展开。
  editor.onMouseDown((event) => {
    const lineNumber = event.target.position?.lineNumber
    if (lineNumber === undefined) return
    const row = displayRows.value[lineNumber - 1]
    if (row?.kind === 'gap') expandGap(row.blockIndex, lineNumber)
  })
  renderRows({ revealFirstChange: true })
}, { flush: 'post' })

watch(() => props.diff, () => {
  expandedGaps.value = new Set()
  renderRows({ revealFirstChange: true })
})
watch(editorTheme, theme => monaco.editor.setTheme(theme))

function renderRows(options: { revealFirstChange?: boolean; revealLine?: number } = {}) {
  if (!editor) return
  const rows = displayRows.value
  const language = languageForPath(props.diff?.path || '')
  const text = rows.map(row => (row.kind === 'gap' ? gapLabel(row.hiddenCount) : row.text)).join('\n')
  if (model) model.setValue(text)
  else {
    model = monaco.editor.createModel(text, language)
    editor.setModel(model)
  }
  decorations?.clear()
  decorations = editor.createDecorationsCollection(
    rows.flatMap((row, index) => (
      row.kind === 'context'
        ? []
        : [{
            range: new monaco.Range(index + 1, 1, index + 1, 1),
            options: {
              isWholeLine: true,
              className: `git-diff-${row.kind}-line`,
              linesDecorationsClassName: `git-diff-${row.kind}-marker`,
            },
          }]
    )),
  )
  if (options.revealLine !== undefined) {
    editor.setScrollPosition({ scrollLeft: 0 })
    editor.revealLineInCenter(options.revealLine)
    return
  }
  if (options.revealFirstChange) revealFirstChange(rows)
}

function revealFirstChange(rows: DisplayRow[]) {
  if (!editor) return
  const index = rows.findIndex(row => row.kind === 'added' || row.kind === 'removed')
  if (index < 0) {
    editor.setScrollPosition({ scrollTop: 0, scrollLeft: 0 })
    return
  }
  editor.setScrollPosition({ scrollLeft: 0 })
  editor.revealLineInCenter(index + 1)
}

function expandGap(blockIndex: number, gapLineNumber: number) {
  if (expandedGaps.value.has(blockIndex)) return
  const next = new Set(expandedGaps.value)
  next.add(blockIndex)
  expandedGaps.value = next
  // 展开后把该区块的首行居中，保持阅读位置。
  renderRows({ revealLine: gapLineNumber })
}

function toggleAllGaps() {
  // allExpanded 为真时按钮是「折叠未变更」，否则是「展开全部」。
  expandedGaps.value = allExpanded.value
    ? new Set()
    : new Set(blocks.value.flatMap((block, index) => (block.kind === 'gap' ? [index] : [])))
  renderRows({ revealFirstChange: true })
}

function gapLabel(count: number): string {
  return t('git.hiddenLines', { count })
}

function languageForPath(path: string): string {
  const filename = path.split('/').at(-1)?.toLocaleLowerCase() || ''
  const extension = filename.includes('.') ? filename.split('.').at(-1) || '' : ''
  const exact: Record<string, string> = { dockerfile: 'dockerfile' }
  const byExtension: Record<string, string> = {
    bash: 'shell', c: 'cpp', cc: 'cpp', cpp: 'cpp', cs: 'csharp', css: 'css',
    go: 'go', h: 'cpp', hpp: 'cpp', htm: 'html', html: 'html', java: 'java',
    js: 'javascript', json: 'json', jsx: 'javascript', kt: 'kotlin', kts: 'kotlin',
    md: 'markdown', php: 'php', py: 'python', rb: 'ruby', rs: 'rust',
    sh: 'shell', sql: 'sql', swift: 'swift', ts: 'typescript', tsx: 'typescript',
    vue: 'html', xml: 'xml', yaml: 'yaml', yml: 'yaml', zsh: 'shell',
  }
  return exact[filename] || byExtension[extension] || 'plaintext'
}

function disposeModel() {
  decorations?.clear()
  decorations = null
  editor?.setModel(null)
  model?.dispose()
  model = null
}

function disposeEditor() {
  disposeModel()
  editor?.dispose()
  editor = null
}

onBeforeUnmount(disposeEditor)
</script>

<style scoped>
.git-diff-viewer { width: 100%; height: 100%; min-width: 0; min-height: 0; }
.unified-diff {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}
.diff-editor-host { grid-row: 2; width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; }
.git-diff-toolbar {
  grid-row: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--app-border);
}
.git-diff-toolbar-text { color: var(--app-text-muted); font-size: 11px; }
.git-diff-toolbar-action {
  padding: 0;
  border: 0;
  background: none;
  color: var(--app-text);
  cursor: pointer;
  font-size: 11px;
}
.git-diff-toolbar-action:hover { text-decoration: underline; }
.diff-editor-host :deep(.git-diff-added-line) { background: var(--app-diff-addition-surface); }
.diff-editor-host :deep(.git-diff-removed-line) { background: var(--app-diff-deletion-surface); }
.diff-editor-host :deep(.git-diff-added-marker)::before { content: '+'; color: var(--app-diff-addition); font-weight: 700; }
.diff-editor-host :deep(.git-diff-removed-marker)::before { content: '−'; color: var(--app-diff-deletion); font-weight: 700; }
/* 折叠区：整行可点，点击展开。 */
.diff-editor-host :deep(.git-diff-gap-line) {
  background: var(--app-divider);
  color: var(--app-text-muted);
  cursor: pointer;
  font-style: italic;
}
.diff-editor-host :deep(.git-diff-gap-marker)::before { content: '⋯'; color: var(--app-text-muted); font-weight: 700; }
.git-diff-truncated {
  grid-row: 3;
  margin: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 11px;
}
.git-diff-state { display: grid; place-items: center; overflow: hidden; border: 1px solid var(--app-border); border-radius: var(--app-radius-lg); color: var(--app-text-muted); }
.git-diff-state.error { color: var(--app-error); }
</style>
