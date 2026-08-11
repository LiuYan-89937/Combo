<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { darkTheme, NConfigProvider, NMessageProvider } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { getPalette } from '@/theme/palette'
import { applyPaletteToRoot } from '@/theme/cssVariables'
import { createThemeOverrides } from '@/theme/naiveTheme'

const ui = useUiStore()
const dark = computed(() => ui.actualTheme === 'dark')
const palette = computed(() => getPalette(dark.value))
const naiveTheme = computed(() => dark.value ? darkTheme : null)
const themeOverrides = computed(() => createThemeOverrides(palette.value))

watchEffect(() => {
  applyPaletteToRoot(palette.value)
  document.documentElement.dataset.theme = dark.value ? 'dark' : 'light'
})
</script>

<style>
* { box-sizing: border-box; }
html, body, #app { width: 100%; height: 100%; margin: 0; overflow: hidden; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--app-surface); }
button, input, textarea { font: inherit; }
</style>
