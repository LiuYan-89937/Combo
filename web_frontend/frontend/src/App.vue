<template>
  <n-config-provider :theme="themeConfig" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <n-loading-bar-provider>
            <AppContent />
          </n-loading-bar-provider>
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { darkTheme, type GlobalThemeOverrides } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { appPalette as palette } from '@/theme/palette'
import AppContent from '@/layouts/AppContent.vue'

const uiStore = useUiStore()

const themeConfig = computed(() => {
  return uiStore.actualTheme === 'dark' ? darkTheme : null
})

const themeOverrides: GlobalThemeOverrides = {
  common: {
    baseColor: palette.surface,
    bodyColor: palette.surface,
    cardColor: palette.surface,
    modalColor: palette.surface,
    popoverColor: palette.surface,
    tableColor: palette.surface,
    invertedColor: palette.text,
    hoverColor: palette.surfaceMuted,
    borderColor: palette.border,
    dividerColor: palette.divider,
    textColorBase: palette.text,
    textColor1: palette.text,
    textColor2: palette.textSecondary,
    textColor3: palette.textMuted,
    placeholderColor: palette.textPlaceholder,
    primaryColor: palette.primary,
    primaryColorHover: palette.primaryHover,
    primaryColorPressed: palette.primaryPressed,
    primaryColorSuppl: palette.primarySuppl,
  },
  Button: {
    color: palette.transparent,
    colorHover: palette.surfaceMuted,
    colorPressed: palette.surfacePressed,
    colorFocus: palette.surfaceMuted,
    colorDisabled: palette.surfaceMuted,
    textColor: palette.text,
    textColorHover: palette.textStrong,
    textColorPressed: palette.textStrong,
    textColorFocus: palette.textStrong,
    textColorDisabled: palette.textDisabled,
    textColorText: palette.text,
    textColorTextHover: palette.textStrong,
    textColorTextPressed: palette.textStrong,
    textColorTextFocus: palette.textStrong,
    textColorTextDisabled: palette.textDisabled,
    textColorGhost: palette.text,
    textColorGhostHover: palette.textStrong,
    textColorGhostPressed: palette.textStrong,
    textColorGhostFocus: palette.textStrong,
    textColorGhostDisabled: palette.textDisabled,
    border: `1px solid ${palette.border}`,
    borderHover: `1px solid ${palette.borderHover}`,
    borderPressed: `1px solid ${palette.textStrong}`,
    borderFocus: `1px solid ${palette.textStrong}`,
    borderDisabled: `1px solid ${palette.border}`,
    textColorPrimary: palette.surface,
    textColorHoverPrimary: palette.surface,
    textColorPressedPrimary: palette.surface,
    textColorFocusPrimary: palette.surface,
    textColorDisabledPrimary: palette.surface,
    textColorTextPrimary: palette.text,
    textColorTextHoverPrimary: palette.textStrong,
    textColorTextPressedPrimary: palette.textStrong,
    textColorTextFocusPrimary: palette.textStrong,
    textColorTextDisabledPrimary: palette.textDisabled,
    colorPrimary: palette.primary,
    colorHoverPrimary: palette.primaryHover,
    colorPressedPrimary: palette.primaryPressed,
    colorFocusPrimary: palette.primaryHover,
    colorDisabledPrimary: palette.borderHover,
    borderPrimary: `1px solid ${palette.primary}`,
    borderHoverPrimary: `1px solid ${palette.primaryHover}`,
    borderPressedPrimary: `1px solid ${palette.primaryPressed}`,
    borderFocusPrimary: `1px solid ${palette.primaryHover}`,
    borderDisabledPrimary: `1px solid ${palette.borderHover}`,
  },
  Input: {
    color: palette.surface,
    colorFocus: palette.surface,
    textColor: palette.text,
    placeholderColor: palette.textPlaceholder,
    border: `1px solid ${palette.border}`,
    borderHover: `1px solid ${palette.borderHover}`,
    borderFocus: `1px solid ${palette.text}`,
    boxShadowFocus: `0 0 0 2px ${palette.focusShadow}`,
  },
  Menu: {
    itemColorActive: palette.surfacePressed,
    itemColorActiveHover: palette.surfaceActiveHover,
    itemColorHover: palette.surfaceMuted,
    itemTextColor: palette.text,
    itemTextColorHover: palette.textStrong,
    itemTextColorActive: palette.textStrong,
    itemTextColorActiveHover: palette.textStrong,
    itemIconColor: palette.textSecondary,
    itemIconColorHover: palette.textStrong,
    itemIconColorActive: palette.textStrong,
    itemIconColorActiveHover: palette.textStrong,
  },
  Tabs: {
    tabTextColorActiveLine: palette.text,
    tabTextColorHoverLine: palette.text,
    barColor: palette.text,
  },
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app {
  height: 100%;
  width: 100%;
  overflow: hidden;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol',
    'Noto Color Emoji';
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

code {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
}

.n-button {
  color: var(--n-text-color);
  background-color: var(--n-color);
}

.n-button:not(.n-button--disabled):focus {
  color: var(--n-text-color-focus);
  background-color: var(--n-color-focus);
}

.n-button:not(.n-button--disabled):hover {
  color: var(--n-text-color-hover);
  background-color: var(--n-color-hover);
}

.n-button:not(.n-button--disabled):active,
.n-button.n-button--pressed {
  color: var(--n-text-color-pressed);
  background-color: var(--n-color-pressed);
}

.n-button.n-button--disabled {
  color: var(--n-text-color-disabled);
  background-color: var(--n-color-disabled);
}
</style>
