<template>
  <n-drawer v-model:show="show" :width="400" placement="right">
    <n-drawer-content :title="t('settings.title')">
      <n-space vertical :size="20">
        <div>
          <n-text strong>{{ t('settings.language') }}</n-text>
          <n-radio-group v-model:value="locale" style="margin-top: 8px">
            <n-radio-button
              v-for="option in localeOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </n-radio-button>
          </n-radio-group>
        </div>

        <div>
          <n-text strong>{{ t('settings.contextWindow') }}</n-text>
          <n-space vertical style="margin-top: 8px">
            <n-text depth="3">
              {{ t('settings.contextCurrent', { tokens: contextWindowTokensText, source: contextWindowSourceText }) }}
            </n-text>
            <n-input-number
              v-model:value="contextWindowTokensDraft"
              :min="1"
              :precision="0"
              clearable
              :placeholder="t('settings.contextPlaceholder')"
            />
            <n-space>
              <n-button type="primary" @click="saveContextWindowTokens">
                {{ t('common.save') }}
              </n-button>
              <n-button @click="resetContextWindowTokens">
                {{ t('settings.useEnvDefault') }}
              </n-button>
            </n-space>
          </n-space>
        </div>

        <div>
          <n-text strong>{{ t('settings.envOverrides') }}</n-text>
          <n-space vertical style="margin-top: 8px">
            <n-text depth="3">
              {{ t('settings.envOverridesHint') }}
            </n-text>
            <n-input
              v-model:value="envOverridesDraft"
              type="textarea"
              :rows="6"
              :placeholder="t('settings.envOverridesPlaceholder')"
            />
            <n-text depth="3">
              {{ envOverridesStatusText }}
            </n-text>
            <n-text v-if="envOverrideKeysText" depth="3">
              {{ t('settings.envOverridesKeys', { keys: envOverrideKeysText }) }}
            </n-text>
            <n-space>
              <n-button type="primary" @click="saveEnvOverrides">
                {{ t('common.save') }}
              </n-button>
              <n-button @click="resetEnvOverrides">
                {{ t('settings.resetEnvOverrides') }}
              </n-button>
            </n-space>
          </n-space>
        </div>

        <div>
          <n-text strong>{{ t('settings.about') }}</n-text>
          <n-text depth="3" style="display: block; margin-top: 8px">
            FastAgentFactory v2.0.0
          </n-text>
          <n-text depth="3" style="display: block">
            {{ t('settings.description') }}
          </n-text>
        </div>
      </n-space>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NInput,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSpace,
  NText,
} from 'naive-ui'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import type { Locale } from '@/i18n'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const commands = useCommand()
const { localeOptions, t } = useI18n()
const contextWindowTokensDraft = ref<number | null>(null)
const envOverridesDraft = ref('')

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const locale = computed({
  get: () => uiStore.locale,
  set: (value: Locale) => uiStore.setLocale(value),
})

const contextWindowTokensText = computed(() => {
  const value = runtimeStore.runtimeOptions.context_window_tokens
  return typeof value === 'number' ? new Intl.NumberFormat(locale.value).format(value) : t('common.unset')
})

const contextWindowSourceText = computed(() => {
  const source = runtimeStore.runtimeOptions.context_window_tokens_source
  const labels: Record<string, string> = {
    env: t('settings.sourceEnv'),
    web: t('settings.sourceWeb'),
    web_env: t('settings.sourceWebEnv'),
    unset: t('settings.sourceUnset'),
  }
  return labels[source] || source
})

const envOverrideKeys = computed(() => runtimeStore.runtimeOptions.env_override_keys || [])

const envOverridesStatusText = computed(() => {
  const count = runtimeStore.runtimeOptions.env_override_count || envOverrideKeys.value.length
  return t('settings.envOverridesActive', { count })
})

const envOverrideKeysText = computed(() => envOverrideKeys.value.join(', '))

function saveContextWindowTokens() {
  commands.setRuntimeOptions({
    context_window_tokens: contextWindowTokensDraft.value,
  })
}

function resetContextWindowTokens() {
  contextWindowTokensDraft.value = null
  commands.setRuntimeOptions({
    context_window_tokens: null,
  })
}

function saveEnvOverrides() {
  commands.setRuntimeOptions({
    env_overrides: envOverridesDraft.value,
  })
}

function resetEnvOverrides() {
  envOverridesDraft.value = ''
  commands.setRuntimeOptions({
    env_overrides: {},
  })
}

watch(
  () => runtimeStore.runtimeOptions.context_window_tokens,
  (value) => {
    contextWindowTokensDraft.value = value
  },
  { immediate: true }
)
</script>
