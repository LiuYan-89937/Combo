<template>
  <n-dropdown
    trigger="click"
    placement="bottom-end"
    :show-arrow="false"
    :options="options"
    @select="handleSelect"
    @update:show="handleVisibility"
  >
    <button
      type="button"
      class="file-open-menu-trigger"
      :class="{ 'is-loading': loading }"
      :disabled="!path"
      :title="t('fileOpenMenu.trigger')"
      @click.stop
    >
      <span>{{ t('fileOpenMenu.trigger') }}</span>
      <span class="file-open-menu-chevron" aria-hidden="true">⌄</span>
    </button>
  </n-dropdown>
</template>

<script setup lang="ts">
import { computed, h, ref, type VNodeChild } from 'vue'
import { useMessage } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { openWithApi, type OpenWithApplication } from '@/api/openWith'
import { revealNativePath, saveNativeFileAs } from '@/api/desktopWorkspaceFiles'

const props = defineProps<{
  /** Absolute native path of the file to open. */
  path: string
}>()

const { t } = useI18n()
const message = useMessage()

const applications = ref<OpenWithApplication[]>([])
const loading = ref(false)
const loadError = ref('')
const loaded = ref(false)

type MenuOption =
  | { key: string; label: string; disabled?: boolean; icon?: () => VNodeChild }
  | { key: string; type: 'divider' }

const options = computed<MenuOption[]>(() => {
  const items: MenuOption[] = []
  if (loadError.value) {
    items.push({ key: 'error', label: loadError.value, disabled: true })
  } else if (loading.value) {
    items.push({ key: 'loading', label: t('fileOpenMenu.loading'), disabled: true })
  } else if (applications.value.length === 0) {
    items.push({ key: 'empty', label: t('fileOpenMenu.empty'), disabled: true })
  } else {
    applications.value.forEach((application) => {
      const icon = application.icon_data_url
      items.push({
        key: `app:${application.path}`,
        label: application.is_default
          ? `${application.name}${t('fileOpenMenu.defaultSuffix')}`
          : application.name,
        ...(icon
          ? {
              // Inline styles: the dropdown renders in a teleported layer, so this
              // component's scoped styles would not reach the icon.
              icon: () =>
                h('img', {
                  src: icon,
                  alt: '',
                  style: 'width:16px;height:16px;border-radius:3px;object-fit:contain;flex:none;',
                }),
            }
          : {}),
      })
    })
  }
  items.push({ key: 'divider-actions', type: 'divider' })
  items.push({ key: 'reveal', label: t('workspace.revealInFileManager') })
  items.push({ key: 'saveAs', label: t('workspace.saveAs') })
  return items
})

/**
 * Enumerating handlers hits LaunchServices, so the list is fetched only when the
 * menu is opened and then cached for this file.
 */
async function handleVisibility(visible: boolean): Promise<void> {
  if (!visible || loaded.value || loading.value || !props.path) return
  loading.value = true
  loadError.value = ''
  try {
    applications.value = await openWithApi.list(props.path)
    loaded.value = true
  } catch (error) {
    loadError.value = t('fileOpenMenu.listFailed', {
      reason: error instanceof Error ? error.message : String(error),
    })
  } finally {
    loading.value = false
  }
}

async function handleSelect(key: string): Promise<void> {
  if (key === 'reveal') {
    await run(() => revealNativePath(props.path))
    return
  }
  if (key === 'saveAs') {
    await run(() => saveNativeFileAs(props.path))
    return
  }
  if (key.startsWith('app:')) {
    await run(() => openWithApi.open(props.path, key.slice(4)))
  }
}

async function run(action: () => Promise<unknown>): Promise<void> {
  try {
    await action()
  } catch (error) {
    message.error(t('fileOpenMenu.failed', {
      reason: error instanceof Error ? error.message : String(error),
    }))
  }
}
</script>

<style scoped>
.file-open-menu-trigger {
  appearance: none;
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  gap: 4px;
  padding: 0 9px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font: 11px/1 var(--app-font-sans);
  white-space: nowrap;
  cursor: pointer;
  transition: border-color var(--app-transition-fast), color var(--app-transition-fast), background-color var(--app-transition-fast);
}

.file-open-menu-trigger:hover:not(:disabled) {
  border-color: var(--app-text);
  background: var(--app-surface-hover);
  color: var(--app-text);
}

.file-open-menu-trigger:disabled {
  cursor: default;
  opacity: 0.5;
}

.file-open-menu-chevron {
  font-size: 12px;
  line-height: 1;
}
</style>
