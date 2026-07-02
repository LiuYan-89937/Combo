<template>
  <div class="model-pool-view">
    <div class="context-bar">
      <div class="context-title">
        <n-text strong>{{ t('modelPool.title') }}</n-text>
        <n-text depth="3" class="context-subtitle">{{ t('modelPool.subtitle') }}</n-text>
      </div>
      <n-button @click="refresh" :loading="loading">
        <template #icon>
          <n-icon><Refresh /></n-icon>
        </template>
        {{ t('common.refresh') }}
      </n-button>
    </div>

    <n-tabs type="line" animated>
      <n-tab-pane name="profiles" :tab="t('modelPool.profiles')">
        <div class="tab-content">
          <div class="content-header">
            <n-text>{{ t('modelPool.profileHint') }}</n-text>
            <n-button type="primary" @click="openProfile()">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              {{ t('modelPool.addProfile') }}
            </n-button>
          </div>

          <n-list v-if="profiles.length" bordered class="model-list">
            <n-list-item v-for="profile in profiles" :key="profile.profile_id">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ profile.display_name }}</n-text>
                    <n-tag size="small" :bordered="false">{{ profile.model_name }}</n-tag>
                    <n-tag size="small" :type="profile.enabled ? 'success' : 'default'">
                      {{ profile.enabled ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div class="item-meta">
                    {{ providerLabel(profile.provider) }}
                    <span v-if="profile.limits.max_input_tokens"> · {{ formatTokens(profile.limits.max_input_tokens) }}</span>
                  </div>
                  <div class="capabilities">
                    <n-tag v-for="item in capabilityTags(profile)" :key="item" size="small" :bordered="false">
                      {{ item }}
                    </n-tag>
                  </div>
                </template>
                <template #action>
                  <n-space>
                    <n-switch :value="profile.enabled" @update:value="(value) => setProfileEnabled(profile, value)" />
                    <n-button size="small" @click="openProfile(profile)">{{ t('common.edit') }}</n-button>
                    <n-button size="small" tertiary type="error" @click="confirmDeleteProfile(profile)">
                      {{ t('common.delete') }}
                    </n-button>
                  </n-space>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>

          <n-empty v-else class="manager-empty" :description="t('modelPool.noProfiles')">
            <template #extra>
              <n-button type="primary" @click="openProfile()">{{ t('modelPool.addProfile') }}</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>

      <n-tab-pane name="credentials" :tab="t('modelPool.credentials')">
        <div class="tab-content">
          <div class="content-header">
            <n-text>{{ t('modelPool.credentialHint') }}</n-text>
            <n-button type="primary" @click="openCredential()">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              {{ t('modelPool.addCredential') }}
            </n-button>
          </div>

          <n-list v-if="credentials.length" bordered class="model-list">
            <n-list-item v-for="credential in credentials" :key="credential.credential_id">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ credential.display_name }}</n-text>
                    <n-tag size="small">{{ providerLabel(credential.provider) }}</n-tag>
                    <n-tag size="small" :type="credential.enabled ? 'success' : 'default'">
                      {{ credential.enabled ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div class="item-meta">{{ credential.base_url }}</div>
                  <div class="item-meta">
                    {{ credential.api_key_masked || t('modelPool.noApiKey') }}
                    <span v-if="credential.api_key_fingerprint"> · {{ credential.api_key_fingerprint }}</span>
                  </div>
                </template>
                <template #action>
                  <n-space>
                    <n-switch :value="credential.enabled" @update:value="(value) => setCredentialEnabled(credential, value)" />
                    <n-button size="small" @click="openCredential(credential)">{{ t('common.edit') }}</n-button>
                    <n-button size="small" tertiary type="error" @click="confirmDeleteCredential(credential)">
                      {{ t('common.delete') }}
                    </n-button>
                  </n-space>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>

          <n-empty v-else class="manager-empty" :description="t('modelPool.noCredentials')">
            <template #extra>
              <n-button type="primary" @click="openCredential()">{{ t('modelPool.addCredential') }}</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="credentialModalOpen"
      preset="dialog"
      :title="credentialEditing ? t('modelPool.editCredential') : t('modelPool.addCredential')"
    >
      <n-form label-placement="top">
        <n-form-item :label="t('modelPool.displayName')">
          <n-input v-model:value="credentialForm.display_name" :placeholder="t('modelPool.credentialNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('modelPool.provider')">
          <n-select v-model:value="credentialForm.provider" :options="providerOptions" :placeholder="t('modelPool.providerPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('modelPool.baseUrl')">
          <n-input v-model:value="credentialForm.base_url" :placeholder="t('modelPool.baseUrlPlaceholder')" />
        </n-form-item>
        <n-form-item :label="credentialEditing ? t('modelPool.replaceApiKey') : t('modelPool.apiKey')">
          <n-input v-model:value="credentialForm.api_key" type="password" show-password-on="mousedown" :placeholder="t('modelPool.apiKeyPlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="credentialModalOpen = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="saving" @click="saveCredential">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal
      v-model:show="profileModalOpen"
      preset="dialog"
      :title="profileEditing ? t('modelPool.editProfile') : t('modelPool.addProfile')"
      style="width: min(720px, 92vw)"
    >
      <n-form label-placement="top">
        <n-form-item :label="t('modelPool.displayName')">
          <n-input v-model:value="profileForm.display_name" :placeholder="t('modelPool.profileNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('modelPool.credential')">
          <n-select v-model:value="profileForm.credential_id" :options="credentialOptions" :placeholder="t('modelPool.credentialPlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('modelPool.modelName')">
          <n-input v-model:value="profileForm.model_name" :placeholder="t('modelPool.modelNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('modelPool.capabilities')">
          <n-space vertical>
            <n-checkbox v-model:checked="profileForm.tool_calling">{{ t('modelPool.toolCalling') }}</n-checkbox>
            <n-checkbox v-model:checked="profileForm.image_input">{{ t('modelPool.imageInput') }}</n-checkbox>
            <n-checkbox v-model:checked="profileForm.image_output">{{ t('modelPool.imageOutput') }}</n-checkbox>
            <n-checkbox v-model:checked="profileForm.audio_input">{{ t('modelPool.audioInput') }}</n-checkbox>
            <n-checkbox v-model:checked="profileForm.audio_output">{{ t('modelPool.audioOutput') }}</n-checkbox>
            <n-checkbox v-model:checked="profileForm.reasoning_supported">{{ t('modelPool.reasoning') }}</n-checkbox>
          </n-space>
        </n-form-item>
        <div class="form-grid">
          <n-form-item :label="t('modelPool.maxInput')">
            <n-input-number v-model:value="profileForm.max_input_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxOutput')">
            <n-input-number v-model:value="profileForm.max_output_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.inputPrice')">
            <n-input-number v-model:value="profileForm.input_per_1m_tokens" :min="0" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.outputPrice')">
            <n-input-number v-model:value="profileForm.output_per_1m_tokens" :min="0" clearable />
          </n-form-item>
        </div>
        <n-form-item :label="t('common.description')">
          <n-input v-model:value="profileForm.notes" type="textarea" :placeholder="t('modelPool.notesPlaceholder')" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="profileModalOpen = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="saving" @click="saveProfile">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NInputNumber,
  NList,
  NListItem,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NText,
  NThing,
  useDialog,
  useMessage,
} from 'naive-ui'
import { Add, Refresh } from '@vicons/ionicons5'
import { modelPoolApi, type ModelPoolCredential, type ModelPoolProfile, type ModelProviderProfile } from '@/api/modelPool'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

const loading = ref(false)
const saving = ref(false)
const providers = ref<ModelProviderProfile[]>([])
const credentials = ref<ModelPoolCredential[]>([])
const profiles = ref<ModelPoolProfile[]>([])
const credentialModalOpen = ref(false)
const profileModalOpen = ref(false)
const credentialEditing = ref<ModelPoolCredential | null>(null)
const profileEditing = ref<ModelPoolProfile | null>(null)

const credentialForm = reactive({
  display_name: '',
  provider: '',
  base_url: '',
  api_key: '',
})

const profileForm = reactive({
  display_name: '',
  credential_id: '',
  model_name: '',
  tool_calling: true,
  reasoning_supported: false,
  image_input: false,
  image_output: false,
  audio_input: false,
  audio_output: false,
  max_input_tokens: null as number | null,
  max_output_tokens: null as number | null,
  input_per_1m_tokens: null as number | null,
  output_per_1m_tokens: null as number | null,
  notes: '',
})

const providerOptions = computed(() =>
  providers.value.map((item) => ({ label: item.display_name, value: item.provider_id })),
)
const credentialOptions = computed(() =>
  credentials.value.map((item) => ({ label: `${item.display_name} · ${providerLabel(item.provider)}`, value: item.credential_id })),
)

onMounted(refresh)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [providerData, credentialData, profileData] = await Promise.all([
      modelPoolApi.providers(),
      modelPoolApi.credentials(),
      modelPoolApi.profiles(),
    ])
    providers.value = providerData.providers
    credentials.value = credentialData.credentials
    profiles.value = profileData.profiles.filter((item) => item.kind === 'chat')
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    loading.value = false
  }
}

function openCredential(item?: ModelPoolCredential): void {
  credentialEditing.value = item || null
  credentialForm.display_name = item?.display_name || ''
  credentialForm.provider = item?.provider || providers.value[0]?.provider_id || ''
  credentialForm.base_url = item?.base_url || ''
  credentialForm.api_key = ''
  credentialModalOpen.value = true
}

async function saveCredential(): Promise<void> {
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      display_name: credentialForm.display_name,
      provider: credentialForm.provider,
      base_url: credentialForm.base_url,
      enabled: credentialEditing.value?.enabled ?? true,
    }
    if (credentialForm.api_key.trim()) payload.api_key = credentialForm.api_key.trim()
    if (credentialEditing.value) {
      await modelPoolApi.patchCredential(credentialEditing.value.credential_id, payload)
    } else {
      await modelPoolApi.saveCredential(payload)
    }
    credentialModalOpen.value = false
    await refresh()
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    saving.value = false
  }
}

function openProfile(item?: ModelPoolProfile): void {
  profileEditing.value = item || null
  profileForm.display_name = item?.display_name || ''
  profileForm.credential_id = item?.credential_id || credentials.value[0]?.credential_id || ''
  profileForm.model_name = item?.model_name || ''
  profileForm.tool_calling = item?.capabilities.tool_calling ?? true
  profileForm.reasoning_supported = item?.capabilities.reasoning_supported ?? false
  profileForm.image_input = item?.capabilities.input_modalities.includes('image') ?? false
  profileForm.image_output = item?.capabilities.output_modalities.includes('image') ?? false
  profileForm.audio_input = item?.capabilities.input_modalities.includes('audio') ?? false
  profileForm.audio_output = item?.capabilities.output_modalities.includes('audio') ?? false
  profileForm.max_input_tokens = item?.limits.max_input_tokens ?? null
  profileForm.max_output_tokens = item?.limits.max_output_tokens ?? null
  profileForm.input_per_1m_tokens = item?.pricing.input_per_1m_tokens ?? null
  profileForm.output_per_1m_tokens = item?.pricing.output_per_1m_tokens ?? null
  profileForm.notes = item?.notes || ''
  profileModalOpen.value = true
}

async function saveProfile(): Promise<void> {
  const credential = credentials.value.find((item) => item.credential_id === profileForm.credential_id)
  if (!credential) {
    message.error(t('modelPool.selectCredentialFirst'))
    return
  }
  saving.value = true
  try {
    const inputModalities = ['text']
    const outputModalities = ['text']
    if (profileForm.image_input) inputModalities.push('image')
    if (profileForm.image_output) outputModalities.push('image')
    if (profileForm.audio_input) inputModalities.push('audio')
    if (profileForm.audio_output) outputModalities.push('audio')
    const payload = {
      display_name: profileForm.display_name,
      kind: 'chat',
      provider: credential.provider,
      credential_id: profileForm.credential_id,
      model_name: profileForm.model_name,
      enabled: profileEditing.value?.enabled ?? true,
      capabilities: {
        input_modalities: inputModalities,
        output_modalities: outputModalities,
        tool_calling: profileForm.tool_calling,
        streaming_tool_calls: false,
        strict_tool_schema: false,
        structured_output_methods: ['json_mode', 'function_calling'],
        reasoning_supported: profileForm.reasoning_supported,
        reasoning_efforts: [],
        reasoning_content: profileForm.reasoning_supported,
        cache_usage: false,
      },
      limits: {
        max_input_tokens: profileForm.max_input_tokens,
        max_output_tokens: profileForm.max_output_tokens,
      },
      pricing: {
        currency: 'CNY',
        input_per_1m_tokens: profileForm.input_per_1m_tokens,
        output_per_1m_tokens: profileForm.output_per_1m_tokens,
      },
      notes: profileForm.notes,
    }
    if (profileEditing.value) {
      await modelPoolApi.patchProfile(profileEditing.value.profile_id, payload)
    } else {
      await modelPoolApi.saveProfile(payload)
    }
    profileModalOpen.value = false
    await refresh()
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    saving.value = false
  }
}

async function setCredentialEnabled(item: ModelPoolCredential, enabled: boolean): Promise<void> {
  try {
    await modelPoolApi.patchCredential(item.credential_id, { enabled })
    await refresh()
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  }
}

async function setProfileEnabled(item: ModelPoolProfile, enabled: boolean): Promise<void> {
  try {
    await modelPoolApi.patchProfile(item.profile_id, { enabled })
    await refresh()
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  }
}

function confirmDeleteCredential(item: ModelPoolCredential): void {
  dialog.warning({
    title: t('modelPool.deleteCredential'),
    content: item.display_name,
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      await modelPoolApi.deleteCredential(item.credential_id)
      await refresh()
    },
  })
}

function confirmDeleteProfile(item: ModelPoolProfile): void {
  dialog.warning({
    title: t('modelPool.deleteProfile'),
    content: item.display_name,
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      await modelPoolApi.deleteProfile(item.profile_id)
      await refresh()
    },
  })
}

function providerLabel(providerId: string): string {
  return providers.value.find((item) => item.provider_id === providerId)?.display_name || providerId
}

function capabilityTags(profile: ModelPoolProfile): string[] {
  const tags: string[] = []
  if (profile.capabilities.tool_calling) tags.push(t('modelPool.toolsTag'))
  if (profile.capabilities.input_modalities.includes('image')) tags.push(t('modelPool.imageInput'))
  if (profile.capabilities.output_modalities.includes('image')) tags.push(t('modelPool.imageOutput'))
  if (profile.capabilities.input_modalities.includes('audio')) tags.push(t('modelPool.audioInput'))
  if (profile.capabilities.output_modalities.includes('audio')) tags.push(t('modelPool.audioOutput'))
  if (profile.capabilities.reasoning_supported) tags.push(t('modelPool.reasoning'))
  return tags
}

function formatTokens(value: number): string {
  if (value >= 1000000) return `${Math.round(value / 100000) / 10}M`
  if (value >= 1000) return `${Math.round(value / 1000)}K`
  return String(value)
}
</script>

<style scoped>
.model-pool-view {
  height: 100%;
  padding: 18px 20px;
  overflow: auto;
  background: var(--app-surface);
}

.context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.context-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.context-subtitle,
.item-meta {
  font-size: 12px;
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.model-list {
  background: var(--app-panel);
}

.capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.manager-empty {
  padding: 48px 0;
}

@media (max-width: 720px) {
  .context-bar,
  .content-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
