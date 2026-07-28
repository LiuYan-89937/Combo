<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import SiteHeader from '@/components/layout/SiteHeader.vue'
import SiteFooter from '@/components/layout/SiteFooter.vue'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'

const { t } = useI18n()
const auth = useAuthStore()
const config = useConfigStore()

// Resolve session + public config once at boot; both fail soft.
onMounted(() => {
  void config.ensure()
  void auth.ensure()
})
</script>

<template>
  <a href="#main" class="skip-link">{{ t('nav.menu') }}</a>
  <SiteHeader />
  <main id="main" class="app-main">
    <RouterView v-slot="{ Component }">
      <Transition name="route" mode="out-in">
        <component :is="Component" />
      </Transition>
    </RouterView>
  </main>
  <SiteFooter />
</template>

<style scoped>
.app-main {
  flex: 1 0 auto;
}
.route-enter-active,
.route-leave-active {
  transition: opacity var(--dur-base) var(--ease-out);
}
.route-enter-from,
.route-leave-to {
  opacity: 0;
}
@media (prefers-reduced-motion: reduce) {
  .route-enter-active,
  .route-leave-active {
    transition: none;
  }
}
</style>
