<template>
  <Transition name="floating-activity-detail" @after-enter="emit('opened')">
    <div v-if="open" class="floating-activity-detail-shell">
      <component
        :is="as"
        class="floating-activity-detail-panel"
        :class="{ scrollable }"
        v-bind="$attrs"
      >
        <slot />
      </component>
    </div>
  </Transition>
</template>

<script setup lang="ts">
defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  open: boolean
  scrollable?: boolean
  as?: string
}>(), {
  scrollable: false,
  as: 'section',
})

const emit = defineEmits<{ opened: [] }>()
</script>

<style>
.floating-activity-frame {
  width: min(340px, calc(100vw - 20px));
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--app-text);
  transition: width .26s cubic-bezier(.16, 1, .3, 1);
}

.floating-activity-frame.expanded {
  width: min(460px, calc(100vw - 20px));
}

.floating-activity-frame.dragging {
  transition: none;
  user-select: none;
}

.floating-activity-shell {
  position: fixed;
  z-index: 35;
}

.floating-activity-detail-panel {
  width: 100%;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-elevated);
  box-shadow: var(--app-shadow-lg);
}
</style>

<style scoped>
.floating-activity-detail-shell {
  width: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: 1fr;
  transform-origin: top center;
}

.floating-activity-detail-panel.scrollable {
  max-height: min(65vh, 640px);
  overflow: auto;
}

.floating-activity-detail-enter-active {
  transition:
    grid-template-rows .36s cubic-bezier(.16, 1, .3, 1),
    opacity .22s ease,
    transform .36s cubic-bezier(.16, 1, .3, 1);
}

.floating-activity-detail-leave-active {
  transition:
    grid-template-rows .26s cubic-bezier(.7, 0, .84, 0),
    opacity .18s ease,
    transform .26s ease;
}

.floating-activity-detail-enter-from,
.floating-activity-detail-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
  transform: translateY(-7px) scale(.985);
}

@media (prefers-reduced-motion: reduce) {
  .floating-activity-detail-enter-active,
  .floating-activity-detail-leave-active {
    transition-duration: .01ms;
  }
}
</style>
