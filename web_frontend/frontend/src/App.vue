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
          <n-loading-bar-provider>
            <AppContent />
          </n-loading-bar-provider>
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { darkTheme, dateEnUS, dateZhCN, enUS, zhCN, type GlobalThemeOverrides } from 'naive-ui'
import { routeTitleKey } from '@/i18n'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { getPalette, type AppPalette } from '@/theme/palette'
import { applyPaletteToRoot } from '@/theme/cssVariables'
import AppContent from '@/layouts/AppContent.vue'

const route = useRoute()
const { locale, t } = useI18n()
const uiStore = useUiStore()

const isDark = computed(() => uiStore.actualTheme === 'dark')
const palette = computed(() => getPalette(isDark.value))
const naiveTheme = computed(() => (isDark.value ? darkTheme : null))
const naiveLocale = computed(() => (locale.value === 'zh-CN' ? zhCN : enUS))
const naiveDateLocale = computed(() => (locale.value === 'zh-CN' ? dateZhCN : dateEnUS))
const themeOverrides = computed<GlobalThemeOverrides>(() => createThemeOverrides(palette.value))

// 主题变化时同步注入 CSS 变量到 :root，并给 <html> 打上主题标记
watchEffect(() => {
  applyPaletteToRoot(palette.value)
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light'
  }
})

watchEffect(() => {
  if (typeof document !== 'undefined') {
    document.title = `${t(routeTitleKey(route.name))} - ${t('app.name')}`
  }
})

function createThemeOverrides(p: AppPalette): GlobalThemeOverrides {
  return {
    common: {
      baseColor: p.surface,
      bodyColor: p.surface,
      cardColor: p.surface,
      modalColor: p.surfaceElevated,
      popoverColor: p.surfaceElevated,
      tableColor: p.surface,
      invertedColor: p.text,
      hoverColor: p.surfaceHover,
      borderColor: p.border,
      dividerColor: p.divider,
      textColorBase: p.text,
      textColor1: p.text,
      textColor2: p.textSecondary,
      textColor3: p.textMuted,
      placeholderColor: p.textPlaceholder,
      primaryColor: p.primary,
      primaryColorHover: p.primaryHover,
      primaryColorPressed: p.primaryPressed,
      primaryColorSuppl: p.primarySuppl,
      successColor: p.success,
      successColorHover: p.successHover,
      successColorPressed: p.successPressed,
      infoColor: p.info,
      infoColorHover: p.infoHover,
      infoColorPressed: p.infoPressed,
      warningColor: p.warning,
      warningColorHover: p.warningHover,
      warningColorPressed: p.warningPressed,
      errorColor: p.error,
      errorColorHover: p.errorHover,
      errorColorPressed: p.errorPressed,
    },
    Button: {
      color: p.transparent,
      colorHover: p.surfaceMuted,
      colorPressed: p.surfacePressed,
      colorFocus: p.surfaceMuted,
      colorDisabled: p.surfaceMuted,
      textColor: p.text,
      textColorHover: p.textStrong,
      textColorPressed: p.textStrong,
      textColorFocus: p.textStrong,
      textColorDisabled: p.textDisabled,
      textColorText: p.text,
      textColorTextHover: p.textStrong,
      textColorTextPressed: p.textStrong,
      textColorTextFocus: p.textStrong,
      textColorTextDisabled: p.textDisabled,
      textColorGhost: p.text,
      textColorGhostHover: p.textStrong,
      textColorGhostPressed: p.textStrong,
      textColorGhostFocus: p.textStrong,
      textColorGhostDisabled: p.textDisabled,
      border: `1px solid ${p.border}`,
      borderHover: `1px solid ${p.borderHover}`,
      borderPressed: `1px solid ${p.textStrong}`,
      borderFocus: `1px solid ${p.textStrong}`,
      borderDisabled: `1px solid ${p.border}`,
      textColorPrimary: p.textInverse,
      textColorHoverPrimary: p.textInverse,
      textColorPressedPrimary: p.textInverse,
      textColorFocusPrimary: p.textInverse,
      textColorDisabledPrimary: p.textInverse,
      textColorTextPrimary: p.text,
      textColorTextHoverPrimary: p.textStrong,
      textColorTextPressedPrimary: p.textStrong,
      textColorTextFocusPrimary: p.textStrong,
      textColorTextDisabledPrimary: p.textDisabled,
      colorPrimary: p.primary,
      colorHoverPrimary: p.primaryHover,
      colorPressedPrimary: p.primaryPressed,
      colorFocusPrimary: p.primaryHover,
      colorDisabledPrimary: p.borderHover,
      borderPrimary: `1px solid ${p.primary}`,
      borderHoverPrimary: `1px solid ${p.primaryHover}`,
      borderPressedPrimary: `1px solid ${p.primaryPressed}`,
      borderFocusPrimary: `1px solid ${p.primaryHover}`,
      borderDisabledPrimary: `1px solid ${p.borderHover}`,
    },
    Input: {
      color: p.surface,
      colorFocus: p.surface,
      textColor: p.text,
      placeholderColor: p.textPlaceholder,
      border: `1px solid ${p.border}`,
      borderHover: `1px solid ${p.borderHover}`,
      borderFocus: `1px solid ${p.borderFocus}`,
      boxShadowFocus: `0 0 0 2px ${p.focusShadow}`,
    },
    Menu: {
      itemColorActive: p.surfacePressed,
      itemColorActiveHover: p.surfaceActiveHover,
      itemColorHover: p.surfaceMuted,
      itemTextColor: p.text,
      itemTextColorHover: p.textStrong,
      itemTextColorActive: p.textStrong,
      itemTextColorActiveHover: p.textStrong,
      itemIconColor: p.textSecondary,
      itemIconColorHover: p.textStrong,
      itemIconColorActive: p.textStrong,
      itemIconColorActiveHover: p.textStrong,
    },
    Tabs: {
      tabTextColorActiveLine: p.text,
      tabTextColorHoverLine: p.text,
      barColor: p.text,
    },
    Card: {
      color: p.surface,
      colorEmbedded: p.surfaceMuted,
      borderColor: p.border,
    },
    Drawer: {
      color: p.surface,
    },
    Modal: {
      color: p.surfaceElevated,
    },
  }
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
  color: var(--app-text);
  background-color: var(--app-surface);
  transition: background-color 0.24s ease, color 0.24s ease;
}

code {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
}

/* 全局滚动条美化 */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--app-border);
  border-radius: 5px;
  border: 2px solid transparent;
  background-clip: padding-box;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--app-border-hover);
  background-clip: padding-box;
  border: 2px solid transparent;
}

::-webkit-scrollbar-corner {
  background: transparent;
}

/* 可视化焦点环，键盘导航更友好 */
:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
  border-radius: 4px;
}

/* 输入框、按钮已有 Naive 样式，避免额外描边 */
.n-input:focus-visible,
.n-button:focus-visible,
.n-base-selection:focus-visible {
  outline: none;
}

/* 通用工具类 */
.app-scroll-y {
  overflow-y: auto;
  overflow-x: hidden;
}

.app-elevated {
  background: var(--app-surface-elevated);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
}

/* 骨架条基础动画 */
@keyframes app-skeleton-shimmer {
  0% { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}

.app-skeleton {
  background: linear-gradient(
    90deg,
    var(--app-surface-muted) 0%,
    var(--app-surface-pressed) 50%,
    var(--app-surface-muted) 100%
  );
  background-size: 400px 100%;
  animation: app-skeleton-shimmer 1.4s ease-in-out infinite;
  border-radius: var(--app-radius-md);
}

/* 全局进入动画 */
@keyframes app-fade-in-up {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes app-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes app-pop-in {
  0% {
    opacity: 0;
    transform: scale(0.94);
  }
  60% {
    opacity: 1;
    transform: scale(1.02);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes app-pulse-soft {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.app-fade-in-up {
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.app-fade-in {
  animation: app-fade-in 0.24s ease both;
}

.app-pop-in {
  animation: app-pop-in 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.app-pulse-soft {
  animation: app-pulse-soft 1.6s ease-in-out infinite;
}

/* 尊重用户的减少动画偏好 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}

/* 全局 n-empty 增强 */
.n-empty {
  padding: var(--app-space-xl) var(--app-space-lg);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-md);
}

.n-empty .n-empty__icon {
  opacity: 0.5;
  margin-bottom: 0;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.n-empty .n-empty__description {
  color: var(--app-text-secondary);
  font-size: var(--app-font-md);
  line-height: var(--app-leading-normal);
  margin-top: 0;
  text-align: center;
}

.n-empty .n-empty__extra {
  margin-top: var(--app-space-sm);
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
