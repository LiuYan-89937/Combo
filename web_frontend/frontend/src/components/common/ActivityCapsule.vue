<template>
  <div class="activity-capsule" :class="{ active, expanded }">
    <button class="capsule-select" type="button" :aria-expanded="expanded" @click="emit('select')">
      <slot name="leading" />
      <span class="capsule-copy"><strong>{{ title }}</strong><small v-if="subtitle">{{ subtitle }}</small></span>
    </button>
    <div class="capsule-actions"><slot name="actions" /></div>
  </div>
</template>
<script setup lang="ts">
defineProps<{ title: string; subtitle?: string; active?: boolean; expanded?: boolean }>()
const emit = defineEmits<{ select: [] }>()
</script>
<style scoped>
.activity-capsule { width: min(100%, 360px); height: 48px; display: flex; align-items: center; overflow: hidden; border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); background: var(--app-surface); color: var(--app-text); box-shadow: var(--app-shadow-sm); transition: width .26s cubic-bezier(.16, 1, .3, 1), border-color .2s ease, box-shadow .2s ease; }
.activity-capsule.active, .activity-capsule.expanded { width: 100%; border-color: var(--app-border-hover); box-shadow: var(--app-shadow-md); }
.capsule-select { min-width: 0; flex: 1; display: flex; align-items: center; gap: 9px; padding: 9px 8px 9px 13px; text-align: left; border: 0; background: transparent; color: inherit; cursor: pointer; font: inherit; }
.capsule-copy { min-width: 0; display: grid; gap: 1px; }
.capsule-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.capsule-copy small { overflow: hidden; color: var(--app-text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.capsule-actions { flex: 0 0 auto; display: flex; align-items: center; gap: 1px; padding-right: 7px; }
.capsule-actions :slotted(button) { padding: 5px 7px; font-size: 11px; }
@media (prefers-reduced-motion: reduce) { .activity-capsule { transition: none; } }
</style>
