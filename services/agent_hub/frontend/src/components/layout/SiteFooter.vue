<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import BaseIcon from '@/components/base/BaseIcon.vue'
import { useI18n } from '@/i18n'
import { useConfigStore } from '@/stores/config'

const { t } = useI18n()
const { config } = storeToRefs(useConfigStore())
const year = computed(() => new Date().getFullYear())
</script>

<template>
  <footer class="footer">
    <div class="container footer__inner">
      <div class="footer__brand">
        <span class="footer__name">FastAgentFactory</span>
        <p class="footer__tagline">{{ t('footer.tagline') }}</p>
      </div>

      <nav class="footer__cols" :aria-label="t('footer.product')">
        <div class="footer__col">
          <p class="footer__heading">{{ t('footer.product') }}</p>
          <RouterLink to="/hub" class="footer__link">{{ t('nav.hub') }}</RouterLink>
          <RouterLink to="/publish" class="footer__link">{{ t('nav.publish') }}</RouterLink>
          <RouterLink to="/#download" class="footer__link">{{ t('nav.download') }}</RouterLink>
          <RouterLink to="/changelog" class="footer__link">{{ t('nav.changelog') }}</RouterLink>
        </div>
        <div class="footer__col">
          <p class="footer__heading">{{ t('footer.resources') }}</p>
          <RouterLink to="/guide" class="footer__link">{{ t('nav.guide') }}</RouterLink>
          <a class="footer__link" :href="config.githubRepoUrl" target="_blank" rel="noopener noreferrer">
            GitHub
            <BaseIcon name="arrow-up-right" :size="13" />
          </a>
        </div>
      </nav>
    </div>

    <div class="container footer__base">
      <span>© {{ year }} FastAgentFactory. {{ t('footer.rights') }}</span>
    </div>
  </footer>
</template>

<style scoped>
.footer {
  margin-top: auto;
  border-top: 1px solid var(--border);
  background: var(--surface-subtle);
}
.footer__inner {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-12);
  padding-block: var(--space-18) var(--space-8);
}
.footer__brand {
  max-width: 320px;
}
.footer__name {
  font-weight: 650;
  font-size: 16px;
  color: var(--text-strong);
}
.footer__tagline {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
}
.footer__cols {
  display: flex;
  gap: var(--space-18);
}
.footer__heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: var(--space-3);
}
.footer__col {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.footer__link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  transition: color var(--dur-fast) var(--ease-out);
}
.footer__link:hover {
  color: var(--text-strong);
}
.footer__base {
  padding-block: var(--space-6);
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 13px;
}
@media (max-width: 640px) {
  .footer__cols {
    gap: var(--space-12);
  }
}
</style>
