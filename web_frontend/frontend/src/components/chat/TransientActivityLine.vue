<template>
  <Transition name="activity-line">
    <div
      v-if="label"
      class="transient-activity-line"
      role="status"
      aria-live="polite"
    >
      <span class="activity-mark" aria-hidden="true"></span>
      <span class="activity-label">{{ label }}</span>
    </div>
  </Transition>
</template>

<script setup lang="ts">
defineProps<{
  label: string
}>()
</script>

<style scoped>
.transient-activity-line {
  display: flex;
  min-height: 22px;
  align-items: center;
  gap: 8px;
  padding: 0 4px 4px;
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 18px;
}

.activity-mark {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
  animation: activity-pulse 1.4s ease-in-out infinite;
}

.activity-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-line-enter-active,
.activity-line-leave-active {
  transition: opacity 140ms ease, transform 140ms ease;
}

.activity-line-enter-from,
.activity-line-leave-to {
  opacity: 0;
  transform: translateY(2px);
}

@keyframes activity-pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 0.9;
  }
}

@media (prefers-reduced-motion: reduce) {
  .activity-mark {
    animation: none;
  }
}
</style>
