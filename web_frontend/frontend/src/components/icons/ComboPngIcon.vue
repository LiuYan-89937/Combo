<template>
  <img
    class="combo-png-icon"
    :class="`is-${tone}`"
    :src="tone === 'white'
      ? `/brand/combo/ui-icons/white/${name}.png`
      : `/brand/combo/ui-icons/${name}.png`"
    alt=""
    :width="size"
    :height="size"
    draggable="false"
  />
</template>

<script setup lang="ts">
export type ComboPngIconName =
  | 'plan'
  | 'permission'
  | 'send'
  | 'context'
  | 'finish-flag'
  | 'empty-session'
  | 'empty-memory'
  | 'empty-workspace'

withDefaults(defineProps<{
  name: ComboPngIconName
  size?: number
  tone?: 'auto' | 'black' | 'white'
}>(), {
  size: 20,
  tone: 'auto',
})
</script>

<style scoped>
.combo-png-icon {
  display: block;
  flex: none;
  object-fit: contain;
  object-position: center;
  user-select: none;
}

:root[data-theme='dark'] .combo-png-icon.is-auto {
  filter: invert(1);
}

</style>
