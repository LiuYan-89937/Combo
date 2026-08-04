<script setup lang="ts">
/*
 * Getting-started guide. A linear, numbered path from install to publish.
 * Copy stays honest about what the product does; deep technical docs live in
 * the repo, linked at the end.
 */
import { storeToRefs } from 'pinia'
import BaseButton from '@/components/base/BaseButton.vue'
import { useI18n } from '@/i18n'
import { useSeo } from '@/composables/useSeo'
import { useConfigStore } from '@/stores/config'

const { t } = useI18n()
const { config } = storeToRefs(useConfigStore())

const steps = ['install', 'model', 'agent', 'workspace', 'import', 'publish', 'review']

useSeo(() => ({
  title: t('guide.title'),
  description: t('guide.subtitle'),
  path: '/guide',
}))
</script>

<template>
  <div class="guide">
    <section class="guide__head">
      <div class="container">
        <h1 class="guide__title">{{ t('guide.title') }}</h1>
        <p class="guide__subtitle">{{ t('guide.subtitle') }}</p>
      </div>
    </section>

    <section class="container guide__body">
      <ol class="steps">
        <li v-for="(key, i) in steps" :key="key" class="step">
          <span class="step__num mono">{{ String(i + 1).padStart(2, '0') }}</span>
          <div class="step__content">
            <h2 class="step__title">{{ t(`guide.steps.${key}.title`) }}</h2>
            <p class="step__body">{{ t(`guide.steps.${key}.body`) }}</p>
          </div>
        </li>
      </ol>

      <div class="guide__footer">
        <p class="guide__docs">{{ t('guide.fullDocs') }}</p>
        <div class="guide__cta">
          <BaseButton to="/#download" icon="download">{{ t('nav.download') }}</BaseButton>
          <BaseButton :href="config.githubRepoUrl" external variant="secondary" icon="github">
            GitHub
          </BaseButton>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.guide__head {
  padding-block: var(--space-18) var(--space-8);
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.guide__title {
  font-size: clamp(30px, 5vw, 46px);
  letter-spacing: -0.03em;
  font-weight: 680;
  color: var(--text-strong);
}
.guide__subtitle {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: 17px;
  max-width: 560px;
}
.guide__body {
  padding-block: var(--space-12) var(--space-24);
  max-width: var(--width-reading);
}
.steps {
  list-style: none;
  display: flex;
  flex-direction: column;
}
.step {
  display: flex;
  gap: var(--space-6);
  padding-block: var(--space-8);
  border-bottom: 1px solid var(--border);
}
.step:first-child {
  padding-top: 0;
}
.step__num {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-muted);
  padding-top: 3px;
  flex-shrink: 0;
}
.step__title {
  font-size: 20px;
  font-weight: 640;
  color: var(--text-strong);
}
.step__body {
  margin-top: var(--space-2);
  color: var(--text-secondary);
  line-height: 1.7;
}
.guide__footer {
  margin-top: var(--space-12);
  padding: var(--space-8);
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.guide__docs {
  color: var(--text-secondary);
  margin-bottom: var(--space-6);
}
.guide__cta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
</style>
