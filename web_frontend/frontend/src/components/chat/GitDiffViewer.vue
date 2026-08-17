<template>
  <div v-if="loading" class="git-diff-viewer git-diff-state">{{ t('git.loadingDiff') }}</div>
  <div v-else-if="error" class="git-diff-viewer git-diff-state error">{{ error }}</div>
  <div v-else-if="diff?.binary" class="git-diff-viewer git-diff-state">{{ t('git.binaryDiff') }}</div>
  <div v-else class="git-diff-viewer unified-diff">
    <div ref="host" class="diff-editor-host" />
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
import { buildUnifiedDiff, type UnifiedDiffRow } from '@/utils/unifiedDiff'

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
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let model: monaco.editor.ITextModel | null = null
let decorations: monaco.editor.IEditorDecorationsCollection | null = null
let displayedRows: UnifiedDiffRow[] = []

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
    lineNumbers: lineNumber => String(displayedRows[lineNumber - 1]?.lineNumber || ''),
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
  updateModels()
}, { flush: 'post' })

watch(() => props.diff, updateModels)
watch(editorTheme, theme => monaco.editor.setTheme(theme))

function updateModels() {
  if (!editor || !props.diff) return
  disposeModel()
  displayedRows = buildUnifiedDiff(props.diff.old_content, props.diff.new_content)
  const language = languageForPath(props.diff.path)
  model = monaco.editor.createModel(displayedRows.map(row => row.text).join('\n'), language)
  editor.setModel(model)
  decorations = editor.createDecorationsCollection(
    displayedRows.flatMap((row, index) => (
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
  editor.setScrollPosition({ scrollTop: 0, scrollLeft: 0 })
}

function disposeModel() {
  decorations?.clear()
  decorations = null
  editor?.setModel(null)
  model?.dispose()
  model = null
  displayedRows = []
}

function disposeEditor() {
  disposeModel()
  editor?.dispose()
  editor = null
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

onBeforeUnmount(disposeEditor)
</script>

<style scoped>
.git-diff-viewer { width: 100%; height: 100%; min-width: 0; min-height: 0; }
.unified-diff { overflow: hidden; border: 1px solid var(--app-border); border-radius: 18px; background: var(--app-surface); }
.diff-editor-host { width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; }
.diff-editor-host :deep(.git-diff-added-line) { background: var(--app-diff-addition-surface); }
.diff-editor-host :deep(.git-diff-removed-line) { background: var(--app-diff-deletion-surface); }
.diff-editor-host :deep(.git-diff-added-marker)::before { content: '+'; color: var(--app-diff-addition); font-weight: 700; }
.diff-editor-host :deep(.git-diff-removed-marker)::before { content: '−'; color: var(--app-diff-deletion); font-weight: 700; }
.git-diff-state { display: grid; place-items: center; overflow: hidden; border: 1px solid var(--app-border); border-radius: 18px; color: var(--app-text-muted); }
.git-diff-state.error { color: var(--app-error); }
</style>
