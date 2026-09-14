<template>
  <div
    ref="element"
    class="viewport-content"
    :style="mounted ? undefined : { blockSize: `${height}px` }"
  >
    <slot v-if="mounted" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { provideDetailsState } from '@/composables/useAutoExpandedDetails'
import { useViewportContent } from '@/composables/useViewportContent'

const props = withDefaults(defineProps<{ active?: boolean }>(), { active: false })
const element = ref<HTMLElement | null>(null)
provideDetailsState()
const { mounted, height } = useViewportContent(element, () => props.active)
</script>

<style scoped>
.viewport-content {
  display: flow-root;
  min-inline-size: 0;
}
</style>
