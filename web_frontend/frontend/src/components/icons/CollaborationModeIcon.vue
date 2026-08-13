<template>
  <ComboPngIcon class="collaboration-mode-icon" name="collaboration" :size="42" />
</template>

<script setup lang="ts">
import ComboPngIcon from './ComboPngIcon.vue'
</script>

<style scoped>
.collaboration-mode-icon {
  transition: transform var(--app-transition-fast);
}
</style>
