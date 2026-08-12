<template>
  <span class="combo-logo" :style="{ width: `${size}px`, height: `${size}px` }">
    <img class="logo-light" src="/brand/combo/logo-light.png" alt="Combo" />
    <img class="logo-dark" src="/brand/combo/logo-dark.png" alt="Combo" />
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 30 })
</script>

<style scoped>
.combo-logo { position: relative; display: inline-block; flex: none; overflow: hidden; border-radius: 22%; }
.combo-logo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.logo-dark { display: none; }
:root[data-theme='dark'] .logo-light { display: none; }
:root[data-theme='dark'] .logo-dark { display: block; }
</style>
