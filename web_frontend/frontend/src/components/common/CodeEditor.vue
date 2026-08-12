<template>
  <div ref="host" class="code-editor-host" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'

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
let editor: monaco.editor.IStandaloneCodeEditor | null = null

self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
}

onMounted(() => {
  if (!host.value) return
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: props.language,
    theme: 'vs',
    automaticLayout: true,
    minimap: { enabled: false },
    fontFamily: "'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace",
    fontSize: 13,
    lineHeight: 21,
    lineNumbersMinChars: 3,
    padding: { top: 14, bottom: 14 },
    scrollBeyondLastLine: false,
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

onBeforeUnmount(() => editor?.dispose())
</script>

<style scoped>
.code-editor-host {
  min-height: v-bind('`${minHeight}px`');
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 10px;
}
</style>
