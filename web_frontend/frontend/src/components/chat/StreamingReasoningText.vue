<template>
  <div ref="contentRef" class="reasoning-markdown reasoning-plain">{{ text }}</div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { usePinnedScroll } from '@/composables/usePinnedScroll'

const props = defineProps<{ text: string }>()
const contentRef = ref<HTMLElement | null>(null)

usePinnedScroll(contentRef, () => props.text.length)
</script>

<style scoped>
.reasoning-markdown {
  max-block-size: var(--app-chat-detail-max-block-size);
  overflow: auto;
  overscroll-behavior-x: contain;
  padding: 0 var(--app-space-md) var(--app-space-md);
  color: var(--app-text-muted);
}

.reasoning-plain {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  contain: content;
}
</style>
