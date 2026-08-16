<template>
  <div ref="host" class="code-editor-host" />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import { useUiStore } from '@/stores/ui'

const props = withDefaults(defineProps<{
  modelValue: string
  language?: string
  minHeight?: number
}>(), {
  language: 'python',
  minHeight: 560,
})
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const host = ref<HTMLElement | null>(null)
const uiStore = useUiStore()
const editorTheme = computed(() => uiStore.actualTheme === 'dark' ? 'vs-dark' : 'vs')
let editor: monaco.editor.IStandaloneCodeEditor | null = null

self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
}

onMounted(() => {
  if (!host.value) return
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: props.language,
    theme: editorTheme.value,
    automaticLayout: true,
    minimap: { enabled: false },
    fontFamily: "'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace",
    fontSize: 13,
    lineHeight: 21,
    lineNumbersMinChars: 3,
    padding: { top: 14, bottom: 2 },
    scrollBeyondLastLine: false,
    scrollBeyondLastColumn: 0,
    scrollbar: {
      horizontal: 'hidden',
      horizontalScrollbarSize: 0,
      verticalScrollbarSize: 8,
      useShadows: false,
      alwaysConsumeMouseWheel: false,
    },
    tabSize: 4,
    insertSpaces: true,
    wordWrap: 'on',
  })
  editor.onDidChangeModelContent(() => emit('update:modelValue', editor?.getValue() || ''))
})

watch(() => props.modelValue, (value) => {
  if (editor && editor.getValue() !== value) editor.setValue(value)
})

watch(() => props.language, (language) => {
  const model = editor?.getModel()
  if (model) monaco.editor.setModelLanguage(model, language)
})

watch(editorTheme, (theme) => monaco.editor.setTheme(theme))

onBeforeUnmount(() => editor?.dispose())
</script>

<style scoped>
.code-editor-host {
  min-height: v-bind('`${minHeight}px`');
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface);
}
</style>
