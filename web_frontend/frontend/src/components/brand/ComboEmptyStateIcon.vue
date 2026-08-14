<template>
  <img
    class="combo-empty-state-icon"
    :src="`/brand/combo/ui-icons/empty-${kind}.png`"
    alt=""
    :style="iconStyle"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useUiStore } from '@/stores/ui'

export type ComboEmptyStateKind = 'skill' | 'mcp' | 'scheduler' | 'knowledge'

const props = withDefaults(defineProps<{
  kind: ComboEmptyStateKind
  size?: number
}>(), {
  size: 112,
})

const uiStore = useUiStore()
const iconStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  filter: uiStore.actualTheme === 'dark' ? 'invert(1)' : 'none',
}))
</script>

<style scoped>
.combo-empty-state-icon {
  display: block;
  object-fit: contain;
  user-select: none;
}

:global(.n-empty__icon:has(> .combo-empty-state-icon)) {
  width: auto !important;
  height: auto !important;
}

</style>
