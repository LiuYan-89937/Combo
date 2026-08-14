<template>
  <n-config-provider
    :theme="naiveTheme"
    :theme-overrides="themeOverrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
  >
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <div class="showcase-root">
            <AppContent :runtime-services-enabled="false" />
          </div>
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watchEffect } from 'vue'
import { darkTheme, dateEnUS, dateZhCN, enUS, zhCN } from 'naive-ui'
import AppContent from '@/layouts/AppContent.vue'
import { applyPaletteToRoot } from '@/theme/cssVariables'
import { createThemeOverrides } from '@/theme/naiveTheme'
import { getPalette } from '@/theme/palette'
import { useUiStore } from '@/stores/ui'
import { useShowcaseDirector } from './director'

const uiStore = useUiStore()
const requestedTheme = new URLSearchParams(window.location.search).get('theme')
uiStore.setThemeMode(requestedTheme === 'dark' ? 'dark' : 'light')
const isDark = computed(() => uiStore.actualTheme === 'dark')
const palette = computed(() => getPalette(isDark.value))
const naiveTheme = computed(() => isDark.value ? darkTheme : null)
const themeOverrides = computed(() => createThemeOverrides(palette.value))
const requestedLanguage = new URLSearchParams(window.location.search).get('lang')
uiStore.setLocale(requestedLanguage === 'en' ? 'en-US' : 'zh-CN')
const naiveLocale = computed(() => uiStore.locale === 'en-US' ? enUS : zhCN)
const naiveDateLocale = computed(() => uiStore.locale === 'en-US' ? dateEnUS : dateZhCN)
const director = useShowcaseDirector()

document.documentElement.lang = uiStore.locale

watchEffect(() => {
  applyPaletteToRoot(palette.value)
  document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light'
  document.documentElement.style.colorScheme = isDark.value ? 'dark' : 'light'
})

onMounted(() => director.start())
onBeforeUnmount(() => director.stop())
</script>

<style scoped>
.showcase-root {
  width: 100%;
  height: 100%;
  opacity: 1;
  pointer-events: none;
  user-select: none;
}
</style>
