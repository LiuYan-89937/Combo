<template>
  <img
    class="combo-empty-state-icon"
    :src="`/brand/combo/ui-icons/empty-${kind}.png`"
    alt=""
    :style="{ width: `${size}px`, height: `${size}px` }"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
export type ComboEmptyStateKind = 'skill' | 'mcp' | 'scheduler' | 'knowledge'

withDefaults(defineProps<{
  kind: ComboEmptyStateKind
  size?: number
}>(), {
  size: 112,
})
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

:global([data-theme='dark']) .combo-empty-state-icon {
  filter: invert(1);
}
</style>
