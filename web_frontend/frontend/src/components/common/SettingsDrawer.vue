<template>
  <n-drawer v-model:show="show" :width="drawerWidth" placement="right" class="glass-drawer">
    <n-drawer-content :title="t('settings.title')" closable class="glass-drawer-content">
      <div class="settings-body">
        <!-- 分组：外观与语言 -->
        <section class="settings-group">
          <header class="group-header">
            <div class="group-icon" aria-hidden="true">
              <n-icon size="18"><ColorPalette /></n-icon>
            </div>
            <div class="group-title-block">
              <div class="group-title">{{ t('settings.groupAppearance') }}</div>
              <div class="group-desc">{{ t('settings.groupAppearanceDesc') }}</div>
            </div>
          </header>

          <div class="group-body">
            <div class="field-row">
              <label class="field-label">{{ t('settings.theme') }}</label>
              <n-radio-group v-model:value="themeMode" size="small" class="field-control">
                <n-radio-button
                  v-for="option in themeOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </n-radio-button>
              </n-radio-group>
            </div>

            <div class="field-divider" aria-hidden="true"></div>

            <div class="field-row">
              <label class="field-label">{{ t('settings.language') }}</label>
              <n-radio-group v-model:value="locale" size="small" class="field-control">
                <n-radio-button
                  v-for="option in localeOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </n-radio-button>
              </n-radio-group>
            </div>
          </div>
        </section>

        <!-- 页脚：关于 -->
        <footer class="settings-footer">
          <div class="footer-title">{{ t('settings.about') }}</div>
          <div class="footer-brand">FastAgentFactory <span class="footer-version">v2.0.0</span></div>
          <div class="footer-desc">{{ t('settings.description') }}</div>
        </footer>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  NDrawer,
  NDrawerContent,
  NIcon,
  NRadioButton,
  NRadioGroup,
} from 'naive-ui'
import { ColorPalette } from '@vicons/ionicons5'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import type { Locale } from '@/i18n'
import type { ThemeMode } from '@/stores/ui'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const uiStore = useUiStore()
const { localeOptions, t } = useI18n()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const drawerWidth = computed(() => {
  if (typeof window === 'undefined') return 460
  return Math.min(460, window.innerWidth - 24)
})

const locale = computed({
  get: () => uiStore.locale,
  set: (value: Locale) => uiStore.setLocale(value),
})

const themeMode = computed({
  get: () => uiStore.themeMode,
  set: (value: ThemeMode) => uiStore.setThemeMode(value),
})

const themeOptions = computed<Array<{ label: string; value: ThemeMode }>>(() => [
  { label: t('settings.themeLight'), value: 'light' },
  { label: t('settings.themeDark'), value: 'dark' },
  { label: t('settings.themeAuto'), value: 'auto' },
])
</script>

<style scoped>
.settings-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xl);
  padding-bottom: var(--app-space-lg);
}

/* ========== 分组 ========== */
.settings-group {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  overflow: hidden;
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.settings-group + .settings-group {
  animation-delay: 0.06s;
}

.group-header {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  background: var(--app-surface-muted);
  border-bottom: 1px solid var(--app-divider);
}

.group-icon {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-md);
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
}

.group-title-block {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-title {
  font-size: var(--app-font-lg);
  font-weight: 600;
  color: var(--app-text-strong);
  letter-spacing: -0.01em;
}

.group-desc {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  line-height: var(--app-leading-normal);
}

.group-body {
  padding: var(--app-space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-lg);
}

/* ========== 简单一行字段（label + control） ========== */
.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  flex-wrap: wrap;
}

.field-label {
  flex-shrink: 0;
  font-size: var(--app-font-md);
  font-weight: 500;
  color: var(--app-text);
}

.field-control {
  flex-shrink: 0;
}

/* ========== 分隔线 ========== */
.field-divider {
  height: 1px;
  background: var(--app-divider);
  margin: 0 calc(var(--app-space-lg) * -1);
}

/* ========== 复合字段块（含提示、当前值、输入、按钮） ========== */
.field-block {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.field-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
}

.field-badge {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.field-hint {
  margin: 0;
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  line-height: var(--app-leading-normal);
}

.field-current {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
}

.field-current-label {
  font-size: var(--app-font-xs);
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.field-current-value {
  font-size: var(--app-font-md);
  font-weight: 600;
  color: var(--app-text-strong);
  font-variant-numeric: tabular-nums;
}

.field-input {
  width: 100%;
}

.env-textarea :deep(.n-input__textarea-el) {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: var(--app-font-sm);
  line-height: 1.55;
}

.field-meta {
  margin: 0;
  padding: var(--app-space-xs) var(--app-space-md);
  font-size: var(--app-font-xs);
  color: var(--app-text-muted);
  background: var(--app-surface-muted);
  border-left: 2px solid var(--app-border);
  border-radius: 0 var(--app-radius-sm) var(--app-radius-sm) 0;
  word-break: break-all;
}

.field-actions {
  display: flex;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-xxs);
}

/* ========== 页脚：关于 ========== */
.settings-footer {
  padding-top: var(--app-space-lg);
  border-top: 1px solid var(--app-divider);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xxs);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) 0.12s both;
}

.footer-title {
  font-size: var(--app-font-xs);
  font-weight: 600;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: var(--app-space-xxs);
}

.footer-brand {
  font-size: var(--app-font-lg);
  font-weight: 600;
  color: var(--app-text-strong);
  display: flex;
  align-items: baseline;
  gap: var(--app-space-sm);
}

.footer-version {
  font-size: var(--app-font-sm);
  font-weight: 400;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
}

.footer-desc {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  line-height: var(--app-leading-normal);
}

/* ========== 窄屏 ========== */
@media (max-width: 480px) {
  .field-row {
    flex-direction: column;
    align-items: stretch;
  }
  .field-control {
    width: 100%;
  }
  .group-body {
    padding: var(--app-space-md);
  }
  .group-header {
    padding: var(--app-space-sm) var(--app-space-md);
  }
}

/* ========== 液态玻璃抽屉 ========== */
:deep(.glass-drawer .n-drawer-body-content-wrapper) {
  background: var(--app-glass-background);
  backdrop-filter: var(--app-glass-blur);
  -webkit-backdrop-filter: var(--app-glass-blur);
}

@supports not (backdrop-filter: blur(1px)) {
  :deep(.glass-drawer .n-drawer-body-content-wrapper) {
    background: var(--app-surface-elevated);
  }
}
</style>
