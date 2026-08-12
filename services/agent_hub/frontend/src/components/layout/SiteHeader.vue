<script setup lang="ts">
/*
 * Sticky site header: brand, primary nav, theme/language toggles and the auth
 * affordance. Collapses into a disclosure menu below the tablet breakpoint.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import BaseIcon from '@/components/base/BaseIcon.vue'
import ThemeToggle from './ThemeToggle.vue'
import LangToggle from './LangToggle.vue'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'

const { t } = useI18n()
const route = useRoute()
const auth = useAuthStore()
const { user, isAuthenticated, isAdmin } = storeToRefs(auth)
const configStore = useConfigStore()
const { config } = storeToRefs(configStore)

const menuOpen = ref(false)

const links = computed(() => [
  { to: '/', label: t('nav.product'), exact: true },
  { to: '/changelog', label: t('nav.changelog') },
  { to: '/guide', label: t('nav.guide') },
])

// Close the mobile menu on any route change.
watch(
  () => route.fullPath,
  () => (menuOpen.value = false),
)

function signIn() {
  auth.login()
}
</script>

<template>
  <header class="header">
    <div class="container header__inner">
      <RouterLink to="/" class="brand" aria-label="Combo">
        <span class="brand__mark" aria-hidden="true">
          <img src="/brand-mark.png" alt="" width="34" height="34" />
        </span>
        <span class="brand__wordmark" aria-hidden="true">
          <span class="brand__name">Combo</span>
          <span class="brand__factory">AGENT RUNTIME</span>
        </span>
      </RouterLink>

      <nav class="nav" :aria-label="t('nav.menu')">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="nav__link"
          :class="{ 'nav__link--active': link.exact ? route.path === '/' : route.path.startsWith(link.to) }"
        >
          {{ link.label }}
        </RouterLink>
        <a class="nav__link" :href="config.githubRepoUrl" target="_blank" rel="noopener noreferrer">
          {{ t('nav.github') }}
          <BaseIcon name="arrow-up-right" :size="14" />
        </a>
      </nav>

      <div class="header__actions">
        <LangToggle />
        <ThemeToggle />
        <RouterLink v-if="isAdmin" to="/admin" class="header__publish">{{ t('nav.admin') }}</RouterLink>
        <template v-if="isAuthenticated && user">
          <RouterLink to="/admin" class="header__user" :title="user.display_name || user.github_login">
            <img
              v-if="user.avatar_url"
              :src="user.avatar_url"
              :alt="''"
              class="header__avatar"
              width="28"
              height="28"
              aria-hidden="true"
            />
            <span class="header__user-name">{{ user.display_name || user.github_login }}</span>
          </RouterLink>
        </template>
        <button v-else type="button" class="header__login" @click="signIn">
          <BaseIcon name="github" :size="17" />
          {{ t('nav.login') }}
        </button>
      </div>

      <button
        type="button"
        class="header__burger"
        :aria-expanded="menuOpen"
        :aria-label="t('nav.menu')"
        @click="menuOpen = !menuOpen"
      >
        <BaseIcon :name="menuOpen ? 'close' : 'menu'" :size="22" />
      </button>
    </div>

    <Transition name="sheet">
      <div v-if="menuOpen" class="sheet">
        <div class="container sheet__inner">
          <RouterLink
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            class="sheet__link"
          >
            {{ link.label }}
          </RouterLink>
          <RouterLink v-if="isAdmin" to="/admin" class="sheet__link">{{ t('nav.admin') }}</RouterLink>
          <a class="sheet__link" :href="config.githubRepoUrl" target="_blank" rel="noopener noreferrer">
            {{ t('nav.github') }}
            <BaseIcon name="arrow-up-right" :size="15" />
          </a>
          <div class="sheet__row">
            <LangToggle />
            <ThemeToggle />
            <button v-if="!isAuthenticated" type="button" class="header__login" @click="signIn">
              <BaseIcon name="github" :size="17" />
              {{ t('nav.login') }}
            </button>
            <span v-else class="sheet__user">{{ user?.display_name || user?.github_login }}</span>
          </div>
        </div>
      </div>
    </Transition>
  </header>
</template>

<style scoped>
.header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: color-mix(in srgb, var(--surface) 78%, transparent);
  backdrop-filter: saturate(1.5) blur(18px);
  border-bottom: 1px solid var(--border);
}
.header__inner {
  display: flex;
  align-items: center;
  gap: clamp(var(--space-4), 2vw, var(--space-6));
  height: var(--header-height);
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--text-strong);
  text-decoration: none;
  flex-shrink: 0;
}
.brand__mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  transition: transform var(--dur-base) var(--ease-out);
}
.brand:hover .brand__mark {
  transform: rotate(-3deg) translateY(-1px);
}
.brand__mark img {
  width: 34px;
  height: 34px;
  object-fit: contain;
  filter: var(--brand-mark-filter);
}
.brand__wordmark {
  display: flex;
  flex-direction: column;
  justify-content: center;
  line-height: 1;
}
.brand__name {
  font-size: 16px;
  font-weight: 760;
  letter-spacing: -0.055em;
}
.brand__name span {
  font-weight: 420;
}
.brand__factory {
  margin-top: 4px;
  padding-left: 1px;
  font-family: var(--font-mono);
  font-size: 7px;
  font-weight: 650;
  letter-spacing: 0.31em;
  color: var(--text-muted);
}

.nav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-right: auto;
}
.nav__link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 15px;
  font-weight: 500;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.nav__link:hover {
  color: var(--text-strong);
  background: var(--surface-subtle);
}
.nav__link--active {
  color: var(--text-strong);
}

.header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
.header__publish {
  padding: 8px var(--space-3);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 15px;
  font-weight: 500;
  border-radius: var(--radius-sm);
}
.header__publish:hover {
  color: var(--text-strong);
  background: var(--surface-subtle);
}
.header__login {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding-inline: var(--space-4);
  background: var(--primary);
  color: var(--on-primary);
  border: none;
  border-radius: var(--radius-pill);
  font-family: inherit;
  font-size: 14px;
  font-weight: 550;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.header__login:hover {
  background: var(--primary-hover);
}
.header__user {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding: 4px 12px 4px 5px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  color: var(--text-strong);
  text-decoration: none;
  font-size: 14px;
  font-weight: 550;
  max-width: 180px;
}
.header__user:hover {
  background: var(--surface-subtle);
}
.header__avatar {
  border-radius: 50%;
  flex-shrink: 0;
}
.header__user-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header__burger {
  display: none;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  margin-left: auto;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-strong);
  cursor: pointer;
}

.sheet {
  border-top: 1px solid var(--border);
  background: var(--surface);
  overflow: hidden;
}
.sheet__inner {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-block: var(--space-3) var(--space-4);
}
.sheet__link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px var(--space-2);
  color: var(--text);
  text-decoration: none;
  font-size: 16px;
  font-weight: 500;
  border-radius: var(--radius-sm);
}
.sheet__link:hover {
  background: var(--surface-subtle);
}
.sheet__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
}
.sheet__user {
  font-size: 14px;
  color: var(--text-secondary);
  font-weight: 550;
}

.sheet-enter-active,
.sheet-leave-active {
  transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
}
.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 1023px) {
  .nav,
  .header__publish,
  .header__actions {
    display: none;
  }
  .header__burger {
    display: inline-flex;
  }
}
@media (prefers-reduced-motion: reduce) {
  .brand__mark {
    transition: none;
  }
  .sheet-enter-active,
  .sheet-leave-active {
    transition: none;
  }
}
</style>
