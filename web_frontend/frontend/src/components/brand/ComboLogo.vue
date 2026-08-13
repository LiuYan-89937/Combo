<template>
  <span
    class="combo-logo"
    :style="{ width: `${size}px`, height: `${size}px` }"
    role="img"
    aria-label="Combo"
  />
</template>

<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 30 })
</script>

<style scoped>
.combo-logo {
  display: inline-block;
  flex: none;
  background: currentColor;
  mask: url('/brand/combo/logo-mark.png') center / contain no-repeat;
  -webkit-mask: url('/brand/combo/logo-mark.png') center / contain no-repeat;
}
</style>
