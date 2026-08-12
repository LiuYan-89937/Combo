<template>
  <Teleport to="body">
    <div v-if="show" class="first-run-guide" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div v-if="!targetRect" class="guide-backdrop" />
      <div v-else class="guide-focus" :style="focusStyle" aria-hidden="true" />

      <section :key="currentStep.id" class="guide-bubble" :class="`placement-${currentStep.placement}`">
        <div class="guide-mascot" aria-hidden="true">
          <ComboFrameAnimation
            :character="currentStep.character"
            :action="currentStep.action"
            :size="currentStep.size"
            :loop="currentStep.loop"
          />
        </div>
        <div class="guide-copy">
          <span class="guide-step">{{ activeStep + 1 }} / {{ steps.length }}</span>
          <h2 :id="titleId">{{ t(currentStep.titleKey) }}</h2>
          <p>{{ t(currentStep.descriptionKey) }}</p>
        </div>
        <footer>
          <div class="guide-secondary-actions">
            <button class="guide-skip" type="button" @click="finish">{{ t('onboarding.skip') }}</button>
            <button v-if="activeStep > 0" class="guide-back" type="button" @click="activeStep -= 1">
              {{ t('onboarding.back') }}
            </button>
          </div>
          <div class="guide-progress" aria-hidden="true">
            <span v-for="step in steps" :key="step.id" :class="{ active: step.id === currentStep.id }" />
          </div>
          <button class="guide-next" type="button" @click="advance">
            {{ isLastStep ? t('onboarding.finish') : t('onboarding.next') }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import { useI18n } from '@/composables/useI18n'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import type { ComboAnimationAction, ComboCharacter } from '@/components/brand/comboMascotAssets'

type GuidePlacement = 'center' | 'input' | 'library' | 'dock'

type GuideStep = {
  id: string
  titleKey: Parameters<ReturnType<typeof useI18n>['t']>[0]
  descriptionKey: Parameters<ReturnType<typeof useI18n>['t']>[0]
  character: ComboCharacter
  action: ComboAnimationAction
  size: number
  placement: GuidePlacement
  loop: boolean
  target?: string
}

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  'update:show': [show: boolean]
  complete: []
}>()
const { t } = useI18n()
const activeStep = ref(0)
const targetRect = ref<DOMRect | null>(null)
const titleId = 'combo-first-run-guide-title'

const steps: GuideStep[] = [
  {
    id: 'welcome',
    titleKey: 'onboarding.welcome.title',
    descriptionKey: 'onboarding.welcome.description',
    character: 'paired',
    action: 'idle',
    size: 118,
    placement: 'center',
    loop: true,
  },
  {
    id: 'conversation',
    titleKey: 'onboarding.conversation.title',
    descriptionKey: 'onboarding.conversation.description',
    character: 'lead',
    action: 'running',
    size: 104,
    placement: 'input',
    loop: true,
    target: '[data-onboarding="message-input"]',
  },
  {
    id: 'library',
    titleKey: 'onboarding.library.title',
    descriptionKey: 'onboarding.library.description',
    character: 'companion',
    action: 'jumping',
    size: 96,
    placement: 'library',
    loop: true,
    target: '[data-onboarding="capability-library"]',
  },
  {
    id: 'background-work',
    titleKey: 'onboarding.background.title',
    descriptionKey: 'onboarding.background.description',
    character: 'companion',
    action: 'running',
    size: 96,
    placement: 'dock',
    loop: true,
    target: '[data-onboarding="activity-dock"]',
  },
  {
    id: 'feedback',
    titleKey: 'onboarding.feedback.title',
    descriptionKey: 'onboarding.feedback.description',
    character: 'paired',
    action: 'complete',
    size: 112,
    placement: 'center',
    loop: true,
  },
]

const currentStep = computed(() => steps[activeStep.value])
const isLastStep = computed(() => activeStep.value === steps.length - 1)
const focusStyle = computed<CSSProperties>(() => {
  const rect = targetRect.value
  if (!rect) return {}
  const padding = 8
  return {
    top: `${rect.top - padding}px`,
    left: `${rect.left - padding}px`,
    width: `${rect.width + padding * 2}px`,
    height: `${rect.height + padding * 2}px`,
  }
})

watch(
  [() => props.show, activeStep],
  async ([show]) => {
    if (!show) {
      targetRect.value = null
      return
    }
    await nextTick()
    updateTargetRect()
  },
  { immediate: true },
)

if (typeof window !== 'undefined') {
  window.addEventListener('resize', updateTargetRect)
  window.addEventListener('scroll', updateTargetRect, true)
}

onBeforeUnmount(() => {
  if (typeof window === 'undefined') return
  window.removeEventListener('resize', updateTargetRect)
  window.removeEventListener('scroll', updateTargetRect, true)
})

function updateTargetRect() {
  const selector = currentStep.value.target
  const element = selector ? document.querySelector<HTMLElement>(selector) : null
  const rect = element?.getBoundingClientRect()
  targetRect.value = rect && rect.width > 0 && rect.height > 0 ? rect : null
}

function advance() {
  if (isLastStep.value) {
    finish()
    return
  }
  activeStep.value += 1
}

function finish() {
  emit('update:show', false)
  emit('complete')
}
</script>

<style scoped>
.first-run-guide {
  position: fixed;
  z-index: calc(var(--app-z-modal) + 20);
  inset: 0;
}

.guide-backdrop {
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--app-text) 14%, transparent);
  backdrop-filter: blur(2px);
}

.guide-focus {
  position: fixed;
  border: 1px solid color-mix(in srgb, var(--app-text) 36%, transparent);
  border-radius: 18px;
  box-shadow: 0 0 0 9999px color-mix(in srgb, var(--app-text) 14%, transparent);
  pointer-events: none;
  transition: inset .22s ease, width .22s ease, height .22s ease;
}

.guide-bubble {
  position: absolute;
  z-index: 1;
  display: grid;
  width: min(468px, calc(100vw - 32px));
  grid-template-columns: 104px minmax(0, 1fr);
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--app-border);
  border-radius: 24px;
  color: var(--app-text);
  background: var(--app-surface);
  box-shadow: 0 28px 90px color-mix(in srgb, var(--app-text) 24%, transparent);
  animation: guide-bubble-in .28s cubic-bezier(.16, 1, .3, 1) both;
}

.guide-bubble::after {
  position: absolute;
  width: 18px;
  height: 18px;
  border-right: 1px solid var(--app-border);
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface);
  content: '';
}

.placement-center { top: 50%; left: 50%; transform: translate(-50%, -50%); }
.placement-center::after { display: none; }
.placement-input { bottom: 164px; left: 50%; transform: translateX(-50%); }
.placement-input::after { right: 54px; bottom: -10px; transform: rotate(45deg); }
.placement-library { top: 70px; right: 18px; }
.placement-library::after { top: -10px; right: 58px; transform: rotate(225deg); }
.placement-dock { top: 50%; left: 72px; transform: translateY(-50%); }
.placement-dock::after { top: 50%; left: -10px; transform: translateY(-50%) rotate(135deg); }

.guide-mascot {
  display: grid;
  min-height: 110px;
  overflow: hidden;
  place-items: center;
  border-radius: 17px;
  background: var(--app-surface-muted);
}

.guide-copy { align-self: center; }
.guide-step { color: var(--app-text-muted); font-size: 9px; font-weight: 700; letter-spacing: .14em; }
.guide-copy h2 { margin: 6px 0 7px; font-size: 21px; letter-spacing: -.035em; }
.guide-copy p { margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.65; }

.guide-bubble footer {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 14px;
  padding-top: 4px;
}

.guide-bubble button {
  min-height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.guide-secondary-actions { display: flex; align-items: center; gap: 2px; }
.guide-skip, .guide-back { border: 0; color: var(--app-text-muted); background: transparent; }
.guide-next { justify-self: end; border: 1px solid var(--app-text); color: var(--app-surface); background: var(--app-text); }
.guide-progress { display: flex; gap: 5px; }
.guide-progress span { width: 5px; height: 5px; border-radius: 999px; background: var(--app-border-hover); transition: width var(--app-transition-base), background var(--app-transition-fast); }
.guide-progress span.active { width: 18px; background: var(--app-text); }

@keyframes guide-bubble-in {
  from { opacity: 0; scale: .96; }
  to { opacity: 1; scale: 1; }
}

@media (max-width: 600px) {
  .guide-bubble { grid-template-columns: 86px minmax(0, 1fr); }
  .guide-mascot { min-height: 96px; }
  .placement-input { bottom: 132px; }
  .placement-library { right: 16px; }
  .placement-dock { left: 16px; }
  .guide-secondary-actions { gap: 0; }
  .guide-bubble button { padding-inline: 9px; }
}

@media (prefers-reduced-motion: reduce) {
  .guide-bubble { animation: none; }
  .guide-focus { transition: none; }
}
</style>
