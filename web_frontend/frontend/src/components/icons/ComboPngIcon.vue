<template>
  <span
    class="combo-png-icon"
    :class="`is-${tone}`"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      '--combo-icon-mask': `url(/brand/combo/ui-icons/mask/${name}.png)`,
    }"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
export type ComboPngIconName =
  | 'plan'
  | 'permission'
  | 'collaboration'
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
  background: currentColor;
  mask: var(--combo-icon-mask) center / contain no-repeat;
  -webkit-mask: var(--combo-icon-mask) center / contain no-repeat;
  user-select: none;
}

.combo-png-icon.is-black { color: #000; }
.combo-png-icon.is-white { color: #fff; }

</style>
