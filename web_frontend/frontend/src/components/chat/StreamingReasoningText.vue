<template>
  <div ref="contentRef" class="reasoning-markdown reasoning-plain">{{ text }}</div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{ text: string }>()
const contentRef = ref<HTMLElement | null>(null)

watch(
  () => props.text.length,
  () => {
    const element = contentRef.value
    if (!element) return
    const pinned = element.scrollHeight - element.scrollTop - element.clientHeight < 28
    if (!pinned) return
    nextTick(() => {
      if (contentRef.value) contentRef.value.scrollTop = contentRef.value.scrollHeight
    })
  },
)
</script>

<style scoped>
.reasoning-markdown {
  max-block-size: min(42vh, 32rem);
  overflow: auto;
  overscroll-behavior: contain;
  padding: 0 var(--app-space-md) var(--app-space-md);
  color: var(--app-text-muted);
}

.reasoning-plain {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  contain: content;
}
</style>
