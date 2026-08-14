<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = defineProps<{ source: string }>()

marked.use({
  gfm: true,
  breaks: true,
})

const html = computed(() => {
  const rendered = marked.parse(props.source || '', { async: false })
  return DOMPurify.sanitize(String(rendered), {
    USE_PROFILES: { html: true },
  })
})
</script>

<template>
  <div class="markdown" v-html="html" />
</template>

<style scoped>
.markdown {
  color: var(--text);
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  margin: 1.6em 0 0.55em;
  color: var(--text-strong);
  line-height: 1.25;
  letter-spacing: -0.025em;
}
.markdown :deep(h1:first-child),
.markdown :deep(h2:first-child),
.markdown :deep(h3:first-child) {
  margin-top: 0;
}
.markdown :deep(h1) {
  font-size: 1.65rem;
}
.markdown :deep(h2) {
  font-size: 1.35rem;
}
.markdown :deep(h3) {
  font-size: 1.1rem;
}
.markdown :deep(p),
.markdown :deep(ul),
.markdown :deep(ol),
.markdown :deep(pre),
.markdown :deep(blockquote) {
  margin: 0.8em 0;
}
.markdown :deep(ul),
.markdown :deep(ol) {
  padding-left: 1.35em;
}
.markdown :deep(a) {
  color: var(--text-strong);
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.markdown :deep(code) {
  padding: 0.15em 0.4em;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-subtle);
  font-family: var(--font-mono);
  font-size: 0.88em;
}
.markdown :deep(pre) {
  overflow-x: auto;
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-subtle);
}
.markdown :deep(pre code) {
  padding: 0;
  border: 0;
  background: none;
}
.markdown :deep(blockquote) {
  padding-left: var(--space-4);
  border-left: 2px solid var(--border-strong);
  color: var(--text-secondary);
}
</style>

