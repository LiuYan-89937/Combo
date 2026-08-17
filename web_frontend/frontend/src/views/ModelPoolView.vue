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

    <n-tabs v-model:value="activeTab" type="line" animated>
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
                    <n-tag size="small" :bordered="false">
                      {{ profile.kind === 'image_generation'
                        ? t('modelPool.imageGenerationModel')
                        : profile.kind === 'embedding' ? t('modelPool.embeddingModel') : t('modelPool.chatModel') }}
                    </n-tag>
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
                    <n-button
                      size="small"
                      :loading="testingProfileId === profile.profile_id"
                      @click="pingProfile(profile)"
                    >
                      <template #icon>
                        <n-icon><Pulse /></n-icon>
                      </template>
                      {{ t('modelPool.testConnection') }}
                    </n-button>
                    <n-button size="small" @click="openProfile(profile)">{{ t('common.edit') }}</n-button>
                    <n-button
                      size="small"
                      tertiary
                      type="error"
                      :loading="deletingProfileId === profile.profile_id"
                      @click="confirmDeleteProfile(profile)"
                    >
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

          <div ref="infrastructureBindingsPanel" class="role-binding-panel" tabindex="-1">
            <div class="content-header">
              <div class="context-title">
                <n-text strong>{{ t('modelPool.infrastructureBindings') }}</n-text>
              </div>
              <n-button type="primary" :loading="savingBindings" @click="saveInfrastructureBindings">
                {{ t('common.save') }}
              </n-button>
            </div>
            <div class="form-grid role-binding-grid">
              <n-form-item :label="t('modelPool.taskModel')">
                <n-select v-model:value="taskModelBinding" clearable :options="bindingOptions('chat')" />
              </n-form-item>
              <n-form-item :label="t('modelPool.embeddingModel')">
                <n-select v-model:value="embeddingBinding" clearable :options="bindingOptions('embedding')" />
              </n-form-item>
              <n-form-item :label="t('modelPool.defaultImageGenerationModel')">
                <n-select v-model:value="imageGenerationBinding" clearable :options="bindingOptions('image_generation')" />
              </n-form-item>
            </div>
          </div>
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
                    <n-button
                      size="small"
                      tertiary
                      type="error"
                      :loading="deletingCredentialId === credential.credential_id"
                      @click="confirmDeleteCredential(credential)"
                    >
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

      <n-tab-pane name="usage" :tab="t('modelPool.usage')">
        <div class="tab-content">
          <div class="content-header">
            <n-space align="center" wrap>
              <n-radio-group v-model:value="usageGroupBy" class="soft-segmented-control" @update:value="loadUsage">
                <n-radio-button value="model">{{ t('modelPool.usageByModel') }}</n-radio-button>
                <n-radio-button value="credential">{{ t('modelPool.usageByCredential') }}</n-radio-button>
              </n-radio-group>
              <n-radio-group v-model:value="usageChartType" class="soft-segmented-control">
                <n-radio-button value="line">{{ t('modelPool.usageLineChart') }}</n-radio-button>
                <n-radio-button value="bar">{{ t('modelPool.usageBarChart') }}</n-radio-button>
              </n-radio-group>
              <n-select
                v-model:value="usageDays"
                class="usage-range-select"
                :options="usageDayOptions"
                @update:value="loadUsage"
              />
            </n-space>
            <n-button @click="loadUsage" :loading="usageLoading">
              <template #icon>
                <n-icon><Refresh /></n-icon>
              </template>
              {{ t('common.refresh') }}
            </n-button>
          </div>

          <div class="usage-overview">
            <div class="usage-metric">
              <span>{{ t('modelPool.usageCalls') }}</span>
              <strong>{{ formatNumber(usageSummary?.totals.call_count || 0) }}</strong>
            </div>
            <div class="usage-metric">
              <span>{{ t('modelPool.usageTotalTokens') }}</span>
              <strong>{{ formatTokens(usageSummary?.totals.total_tokens || 0) }}</strong>
            </div>
            <div class="usage-metric">
              <span>{{ t('modelPool.usageCacheHit') }}</span>
              <strong>{{ formatPercent(usageSummary?.totals.cache_hit_ratio) }}</strong>
            </div>
            <div class="usage-metric">
              <span>{{ t('modelPool.usageCost') }}</span>
              <strong>{{ formatCost(usageSummary?.totals.estimated_cost) }}</strong>
            </div>
          </div>

          <div class="usage-chart-panel">
            <v-chart v-if="usageSummary?.series.length" class="usage-chart" :option="usageChartOptions" autoresize />
            <n-empty v-else class="manager-empty" :description="t('modelPool.noUsage')" />
          </div>

          <n-data-table
            :columns="usageColumns"
            :data="usageSummary?.groups || []"
            :loading="usageLoading"
            :row-key="(row) => row.key"
            size="small"
          />
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal
      v-model:show="credentialModalOpen"
      preset="card"
      class="editor-modal-shell model-editor-modal model-credential-modal"
      :bordered="false"
      :title="credentialEditing ? t('modelPool.editCredential') : t('modelPool.addCredential')"
    >
      <n-form
        ref="credentialFormRef"
        :model="credentialForm"
        :rules="credentialRules"
        label-placement="top"
        class="credential-editor-form"
      >
        <section class="model-editor-pane">
          <header class="model-editor-pane__header">
            <span>01</span>
            <div>
              <strong>{{ t('modelPool.identitySection') }}</strong>
              <small>{{ t('modelPool.identitySectionHint') }}</small>
            </div>
          </header>
          <n-form-item :label="t('modelPool.displayName')" path="display_name">
            <n-input v-model:value="credentialForm.display_name" :placeholder="t('modelPool.credentialNamePlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('modelPool.provider')" path="provider">
            <n-select v-model:value="credentialForm.provider" :options="providerOptions" :placeholder="t('modelPool.providerPlaceholder')" />
          </n-form-item>
        </section>
        <section class="model-editor-pane">
          <header class="model-editor-pane__header">
            <span>02</span>
            <div>
              <strong>{{ t('modelPool.connectionSection') }}</strong>
              <small>{{ t('modelPool.connectionSectionHint') }}</small>
            </div>
          </header>
          <n-form-item :label="t('modelPool.baseUrl')" path="base_url">
            <n-input v-model:value="credentialForm.base_url" :placeholder="t('modelPool.baseUrlPlaceholder')" />
          </n-form-item>
          <n-form-item
            :label="credentialEditing ? t('modelPool.replaceApiKey') : t('modelPool.apiKey')"
            path="api_key"
          >
            <n-input v-model:value="credentialForm.api_key" type="password" show-password-on="mousedown" :placeholder="t('modelPool.apiKeyPlaceholder')" />
          </n-form-item>
        </section>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="credentialModalOpen = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="saving" @click="saveCredential">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal
      v-model:show="profileModalOpen"
      preset="card"
      class="editor-modal-shell model-editor-modal model-profile-modal"
      :bordered="false"
      :title="profileEditing ? t('modelPool.editProfile') : t('modelPool.addProfile')"
    >
      <n-form
        ref="profileFormRef"
        :model="profileForm"
        :rules="profileRules"
        label-placement="top"
        class="profile-editor-form"
      >
        <section class="model-editor-pane">
          <header class="model-editor-pane__header">
            <span>01</span>
            <div>
              <strong>{{ t('modelPool.identitySection') }}</strong>
              <small>{{ t('modelPool.identitySectionHint') }}</small>
            </div>
          </header>
          <n-form-item :label="t('modelPool.displayName')" path="display_name">
            <n-input v-model:value="profileForm.display_name" :placeholder="t('modelPool.profileNamePlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('modelPool.profileDescription')">
            <n-input
              v-model:value="profileForm.description"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              :placeholder="t('modelPool.profileDescriptionPlaceholder')"
            />
          </n-form-item>
          <div class="model-editor-field-grid">
            <n-form-item :label="t('modelPool.modelType')" path="kind">
              <n-select v-model:value="profileForm.kind" :options="modelKindOptions" />
            </n-form-item>
            <n-form-item :label="t('modelPool.credential')" path="credential_id">
              <n-select v-model:value="profileForm.credential_id" :options="credentialOptions" :placeholder="t('modelPool.credentialPlaceholder')" />
            </n-form-item>
          </div>
          <n-form-item :label="t('modelPool.modelName')" path="model_name">
            <n-input v-model:value="profileForm.model_name" :placeholder="t('modelPool.modelNamePlaceholder')" />
          </n-form-item>
        </section>
        <section class="model-editor-pane">
          <header class="model-editor-pane__header">
            <span>02</span>
            <div>
              <strong>{{ t('modelPool.runtimeSection') }}</strong>
              <small>{{ t('modelPool.runtimeSectionHint') }}</small>
            </div>
          </header>
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('modelPool.capabilities')" class="model-capability-field">
            <n-space>
              <n-checkbox v-model:checked="profileForm.tool_calling">{{ t('modelPool.toolCalling') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.image_input">{{ t('modelPool.imageInput') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.image_output">{{ t('modelPool.imageOutput') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.audio_input">{{ t('modelPool.audioInput') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.audio_output">{{ t('modelPool.audioOutput') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.reasoning_supported">{{ t('modelPool.reasoning') }}</n-checkbox>
            </n-space>
          </n-form-item>
          <n-form-item v-else-if="profileForm.kind === 'image_generation'" :label="t('modelPool.imageCapabilities')" class="model-capability-field">
            <n-space>
              <n-checkbox v-model:checked="profileForm.text_to_image" :disabled="!providerImageCapability('text_to_image')">{{ t('modelPool.textToImage') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.image_to_image" :disabled="!providerImageCapability('image_to_image')">{{ t('modelPool.imageToImage') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.image_edit" :disabled="!providerImageCapability('image_edit')">{{ t('modelPool.imageEdit') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.multi_image_reference" :disabled="!providerImageCapability('multi_image_reference')">{{ t('modelPool.multiImageReference') }}</n-checkbox>
              <n-checkbox v-model:checked="profileForm.batch_generation" :disabled="!providerImageCapability('batch_generation')">{{ t('modelPool.batchGeneration') }}</n-checkbox>
              <n-text depth="3">{{ t('modelPool.imageCapabilitiesDeclarationHint') }}</n-text>
            </n-space>
          </n-form-item>
          <div v-if="profileForm.kind === 'chat'" class="form-grid">
          <n-form-item :label="t('modelPool.maxInput')">
            <n-input-number v-model:value="profileForm.max_input_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.compressionTrigger')">
            <n-input-number
              v-model:value="profileForm.compression_trigger_tokens"
              :min="1"
              :max="profileForm.max_input_tokens || undefined"
              clearable
            />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxOutput')">
            <n-input-number v-model:value="profileForm.max_output_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.temperature')">
            <n-input-number
              v-model:value="profileForm.temperature"
              :min="0"
              :step="0.1"
              clearable
              :placeholder="t('modelPool.providerDefault')"
            />
          </n-form-item>
          <n-form-item :label="t('modelPool.inputPrice')">
            <n-input-number v-model:value="profileForm.input_per_1m_tokens" :min="0" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.outputPrice')">
            <n-input-number v-model:value="profileForm.output_per_1m_tokens" :min="0" clearable />
          </n-form-item>
          </div>
          <div v-else-if="profileForm.kind === 'embedding'" class="form-grid">
          <n-form-item :label="t('modelPool.embeddingDimensions')" path="embedding_dimensions">
            <n-input-number v-model:value="profileForm.embedding_dimensions" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.embeddingBatchSize')" path="embedding_batch_size">
            <n-input-number v-model:value="profileForm.embedding_batch_size" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.timeoutSeconds')">
            <n-input-number v-model:value="profileForm.timeout_seconds" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.inputPrice')">
            <n-input-number v-model:value="profileForm.input_per_1m_tokens" :min="0" clearable />
          </n-form-item>
          </div>
          <div v-else class="form-grid">
          <n-form-item :label="t('modelPool.defaultImageCount')">
            <n-input-number v-model:value="profileForm.max_output_tokens" :min="1" :max="4" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.timeoutSeconds')">
            <n-input-number v-model:value="profileForm.timeout_seconds" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.imageOutputPrice')">
            <n-input-number v-model:value="profileForm.image_output_unit_price" :min="0" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.imageEditPrice')">
            <n-input-number v-model:value="profileForm.image_edit_unit_price" :min="0" clearable />
          </n-form-item>
          </div>
          <n-form-item :label="t('modelPool.notes')">
            <n-input v-model:value="profileForm.notes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" :placeholder="t('modelPool.notesPlaceholder')" />
          </n-form-item>
        </section>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="profileModalOpen = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="saving" @click="saveProfile">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>
    <n-modal
      :show="Boolean(imageTestPreview)"
      preset="card"
      :title="t('modelPool.imageTestPreview')"
      :style="{ width: 'min(640px, calc(100vw - 40px))' }"
      @update:show="value => { if (!value) imageTestPreview = null }"
    >
      <div v-if="imageTestPreview" class="image-test-preview">
        <img :src="imageTestPreview.url" :alt="imageTestPreview.model" />
        <n-text depth="3">{{ imageTestPreview.model }}</n-text>
      </div>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { use } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import {
  NButton,
  NCheckbox,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NInputNumber,
  NList,
  NListItem,
  NModal,
  NRadioButton,
  NRadioGroup,
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
  type DataTableColumns,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { Add, Pulse, Refresh } from '@/components/icons'
import {
  modelPoolApi,
  type ModelPoolCredential,
  type ModelPoolProfile,
  type ModelPoolDefaults,
  type ModelProviderProfile,
  type ModelUsageGroup,
  type ModelUsageGroupBy,
  type ModelUsageSummary,
} from '@/api/modelPool'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { getPalette } from '@/theme/palette'
import {
  requiredHttpUrlRule,
  requiredTextRule,
  requiredValueRule,
  validateForm,
} from '@/utils/formValidation'

use([BarChart, CanvasRenderer, GridComponent, LegendComponent, LineChart, TooltipComponent])

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()
const route = useRoute()
const router = useRouter()
const uiStore = useUiStore()
const chartPalette = computed(() => getPalette(uiStore.actualTheme === 'dark'))

const loading = ref(false)
const activeTab = ref('profiles')
const infrastructureBindingsPanel = ref<HTMLElement | null>(null)
const embeddingSetupRequested = computed(() => route.query.setup === 'embedding')
const saving = ref(false)
const savingBindings = ref(false)
const deletingCredentialId = ref<string | null>(null)
const deletingProfileId = ref<string | null>(null)
const testingProfileId = ref<string | null>(null)
const imageTestPreview = ref<{ url: string; model: string } | null>(null)
const providers = ref<ModelProviderProfile[]>([])
const credentials = ref<ModelPoolCredential[]>([])
const profiles = ref<ModelPoolProfile[]>([])
const modelDefaults = ref<ModelPoolDefaults | null>(null)
const taskModelBinding = ref<string | null>(null)
const embeddingBinding = ref<string | null>(null)
const imageGenerationBinding = ref<string | null>(null)
const usageLoading = ref(false)
const usageGroupBy = ref<ModelUsageGroupBy>('model')
const usageChartType = ref<'line' | 'bar'>('line')
const usageDays = ref(14)
const usageSummary = ref<ModelUsageSummary | null>(null)
const credentialModalOpen = ref(false)
const profileModalOpen = ref(false)
const credentialEditing = ref<ModelPoolCredential | null>(null)
const profileEditing = ref<ModelPoolProfile | null>(null)
const credentialFormRef = ref<FormInst | null>(null)
const profileFormRef = ref<FormInst | null>(null)

const credentialForm = reactive({
  display_name: '',
  provider: '',
  base_url: '',
  api_key: '',
})

const profileForm = reactive({
  kind: 'chat' as 'chat' | 'embedding' | 'image_generation',
  display_name: '',
  description: '',
  credential_id: '',
  model_name: '',
  embedding_dimensions: null as number | null,
  embedding_batch_size: null as number | null,
  tool_calling: true,
  reasoning_supported: false,
  image_input: false,
  image_output: false,
  audio_input: false,
  audio_output: false,
  text_to_image: true,
  image_to_image: false,
  image_edit: false,
  multi_image_reference: false,
  batch_generation: true,
  max_input_tokens: null as number | null,
  compression_trigger_tokens: null as number | null,
  max_output_tokens: null as number | null,
  temperature: null as number | null,
  timeout_seconds: null as number | null,
  input_per_1m_tokens: null as number | null,
  output_per_1m_tokens: null as number | null,
  image_output_unit_price: null as number | null,
  image_edit_unit_price: null as number | null,
  notes: '',
})

const modelKindOptions = computed(() => [
  { label: t('modelPool.chatModel'), value: 'chat' },
  { label: t('modelPool.embeddingModel'), value: 'embedding' },
  { label: t('modelPool.imageGenerationModel'), value: 'image_generation' },
])
const providerOptions = computed(() =>
  uniqueProviders().map((item) => ({ label: item.display_name, value: item.provider_id })),
)
const credentialOptions = computed(() =>
  credentials.value
    .filter((item) => providerSupportsKind(item.provider, profileForm.kind))
    .map((item) => ({ label: `${item.display_name} · ${providerLabel(item.provider)}`, value: item.credential_id })),
)
const usageDayOptions = computed(() => [
  { label: t('modelPool.usageLast7Days'), value: 7 },
  { label: t('modelPool.usageLast14Days'), value: 14 },
  { label: t('modelPool.usageLast30Days'), value: 30 },
  { label: t('modelPool.usageLast90Days'), value: 90 },
])
const credentialRules = computed<FormRules>(() => ({
  display_name: [requiredTextRule(t('validation.required'))],
  provider: [requiredValueRule(t('validation.selectionRequired'))],
  base_url: [
    requiredHttpUrlRule(
      t('validation.required'),
      t('validation.url'),
    ),
  ],
  api_key: credentialEditing.value
    ? []
    : [requiredTextRule(t('validation.required'))],
}))
const profileRules = computed<FormRules>(() => ({
  display_name: [requiredTextRule(t('validation.required'))],
  kind: [requiredValueRule(t('validation.selectionRequired'))],
  credential_id: [requiredValueRule(t('modelPool.selectCredentialFirst'))],
  model_name: [requiredTextRule(t('validation.required'))],
  embedding_dimensions: profileForm.kind === 'embedding'
    ? [requiredValueRule(t('validation.required'))]
    : [],
  embedding_batch_size: profileForm.kind === 'embedding'
    ? [requiredValueRule(t('validation.required'))]
    : [],
}))
const usageColumns = computed<DataTableColumns<ModelUsageGroup>>(() => [
  { title: t('modelPool.usageName'), key: 'label', minWidth: 180, ellipsis: { tooltip: true } },
  { title: t('modelPool.usageCalls'), key: 'call_count', width: 96, render: (row) => formatNumber(row.totals.call_count) },
  { title: t('modelPool.usageInput'), key: 'input_tokens', width: 120, render: (row) => formatTokens(row.totals.input_tokens) },
  { title: t('modelPool.usageOutput'), key: 'output_tokens', width: 120, render: (row) => formatTokens(row.totals.output_tokens) },
  { title: t('modelPool.usageTotalTokens'), key: 'total_tokens', width: 120, render: (row) => formatTokens(row.totals.total_tokens) },
  { title: t('modelPool.usageReasoning'), key: 'reasoning_tokens', width: 120, render: (row) => formatTokens(row.totals.reasoning_tokens) },
  { title: t('modelPool.usageCacheHit'), key: 'cache_hit_ratio', width: 110, render: (row) => formatPercent(row.totals.cache_hit_ratio) },
  { title: t('modelPool.usageCost'), key: 'estimated_cost', width: 110, render: (row) => formatCost(row.totals.estimated_cost) },
])
const usageChartOptions = computed(() => {
  const summary = usageSummary.value
  const chartType = usageChartType.value
  const colors = chartPalette.value
  const buckets = Array.from(
    new Set((summary?.series || []).flatMap((item) => item.points.map((point) => point.bucket))),
  ).sort()
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => formatTokens(value),
    },
    legend: {
      top: 0,
      type: 'scroll',
      textStyle: { color: colors.textSecondary },
    },
    grid: {
      left: 18,
      right: 42,
      top: 48,
      bottom: 32,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: chartType === 'bar',
      data: buckets,
      axisLabel: {
        hideOverlap: true,
        margin: 12,
        color: colors.textMuted,
      },
      axisLine: { lineStyle: { color: colors.border } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (value: number) => formatTokens(value),
        color: colors.textMuted,
      },
      axisLine: { lineStyle: { color: colors.border } },
      splitLine: {
        lineStyle: {
          color: colors.divider,
        },
      },
    },
    series: (summary?.series || []).map((item) => {
      const pointsByBucket = new Map(item.points.map((point) => [point.bucket, point]))
      return {
        name: item.label,
        type: chartType,
        smooth: chartType === 'line',
        symbol: chartType === 'line' ? 'circle' : undefined,
        symbolSize: chartType === 'line' ? 6 : undefined,
        barMaxWidth: chartType === 'bar' ? 28 : undefined,
        barCategoryGap: chartType === 'bar' ? '32%' : undefined,
        data: buckets.map((bucket) => pointsByBucket.get(bucket)?.total_tokens || 0),
      }
    }),
  }
})

onMounted(async () => {
  await refresh()
  await focusRequestedSetup()
})

watch(
  () => route.query.setup,
  () => { void focusRequestedSetup() },
)

async function focusRequestedSetup(): Promise<void> {
  if (!embeddingSetupRequested.value) return
  activeTab.value = 'profiles'
  await nextTick()
  infrastructureBindingsPanel.value?.focus({ preventScroll: true })
  infrastructureBindingsPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (!profiles.value.some((profile) => profile.kind === 'embedding' && profile.enabled)) {
    openProfile()
    profileForm.kind = 'embedding'
  }
  await router.replace({ query: { ...route.query, setup: undefined } })
}

watch(
  () => profileForm.kind,
  (kind) => {
    if (!profileModalOpen.value) return
    const selected = credentials.value.find((item) => item.credential_id === profileForm.credential_id)
    if (selected && providerSupportsKind(selected.provider, kind)) return
    profileForm.credential_id = firstCredentialForKind(kind)?.credential_id || ''
  },
)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [providerData, credentialData, profileData, defaultsData, usageData] = await Promise.all([
      modelPoolApi.providers(),
      modelPoolApi.credentials(),
      modelPoolApi.profiles(),
      modelPoolApi.infrastructureBindings(),
      modelPoolApi.usage({ groupBy: usageGroupBy.value, days: usageDays.value }),
    ])
    providers.value = providerData.providers
    credentials.value = credentialData.credentials
    profiles.value = profileData.profiles
    modelDefaults.value = defaultsData.defaults
    taskModelBinding.value = defaultsData.bindings.task || null
    embeddingBinding.value = defaultsData.bindings.embedding || null
    imageGenerationBinding.value = defaultsData.bindings.image_generation || null
    usageSummary.value = usageData
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    loading.value = false
  }
}

function upsertCredential(credential: ModelPoolCredential): void {
  const index = credentials.value.findIndex(item => item.credential_id === credential.credential_id)
  if (index < 0) credentials.value.unshift(credential)
  else credentials.value.splice(index, 1, credential)
  profiles.value = profiles.value.map(profile => (
    profile.credential_id === credential.credential_id
      ? { ...profile, credential }
      : profile
  ))
}

function upsertProfile(profile: ModelPoolProfile): void {
  const index = profiles.value.findIndex(item => item.profile_id === profile.profile_id)
  if (index < 0) profiles.value.unshift(profile)
  else profiles.value.splice(index, 1, profile)
}

async function loadUsage(): Promise<void> {
  usageLoading.value = true
  try {
    usageSummary.value = await modelPoolApi.usage({ groupBy: usageGroupBy.value, days: usageDays.value })
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    usageLoading.value = false
  }
}

async function saveInfrastructureBindings(): Promise<void> {
  savingBindings.value = true
  try {
    const response = await modelPoolApi.saveInfrastructureBindings({
      task: taskModelBinding.value,
      embedding: embeddingBinding.value,
      image_generation: imageGenerationBinding.value,
    })
    taskModelBinding.value = response.bindings.task || null
    embeddingBinding.value = response.bindings.embedding || null
    imageGenerationBinding.value = response.bindings.image_generation || null
    message.success(t('modelPool.bindingsSaved'))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    savingBindings.value = false
  }
}

function openCredential(item?: ModelPoolCredential): void {
  credentialEditing.value = item || null
  credentialForm.display_name = item?.display_name || ''
  credentialForm.provider = item?.provider || providers.value[0]?.provider_id || ''
  credentialForm.base_url = item?.base_url || ''
  credentialForm.api_key = ''
  credentialModalOpen.value = true
  void nextTick(() => credentialFormRef.value?.restoreValidation())
}

async function saveCredential(): Promise<void> {
  if (!await validateForm(credentialFormRef.value)) return
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
      payload.expected_revision = credentialEditing.value.revision
      const response = await modelPoolApi.patchCredential(credentialEditing.value.credential_id, payload)
      upsertCredential(response.credential)
    } else {
      const response = await modelPoolApi.saveCredential(payload)
      upsertCredential(response.credential)
    }
    credentialModalOpen.value = false
    message.success(t('modelPool.credentialSaved'))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    saving.value = false
  }
}

function openProfile(item?: ModelPoolProfile): void {
  profileEditing.value = item || null
  profileForm.kind = item?.kind || 'chat'
  profileForm.display_name = item?.display_name || ''
  profileForm.description = item?.description || ''
  profileForm.credential_id = item?.credential_id || firstCredentialForKind(profileForm.kind)?.credential_id || ''
  profileForm.model_name = item?.model_name || ''
  profileForm.embedding_dimensions = item?.embedding_dimensions ?? null
  profileForm.embedding_batch_size = item?.embedding_batch_size
    ?? modelDefaults.value?.embedding_batch_size
    ?? null
  profileForm.tool_calling = item?.capabilities.tool_calling ?? true
  profileForm.reasoning_supported = item?.capabilities.reasoning_supported ?? false
  profileForm.image_input = item?.capabilities.input_modalities.includes('image') ?? false
  profileForm.image_output = item?.capabilities.output_modalities.includes('image') ?? false
  profileForm.audio_input = item?.capabilities.input_modalities.includes('audio') ?? false
  profileForm.audio_output = item?.capabilities.output_modalities.includes('audio') ?? false
  profileForm.text_to_image = item?.capabilities.text_to_image ?? true
  profileForm.image_to_image = item?.capabilities.image_to_image ?? false
  profileForm.image_edit = item?.capabilities.image_edit ?? false
  profileForm.multi_image_reference = item?.capabilities.multi_image_reference ?? false
  profileForm.batch_generation = item?.capabilities.batch_generation ?? true
  profileForm.max_input_tokens = item?.limits.max_input_tokens ?? modelDefaults.value?.context_window_tokens ?? null
  profileForm.compression_trigger_tokens = item?.limits.compression_trigger_tokens
    ?? modelDefaults.value?.compression_trigger_tokens
    ?? null
  profileForm.max_output_tokens = item?.limits.max_output_tokens ?? null
  profileForm.temperature = item?.settings.temperature ?? null
  profileForm.timeout_seconds = item?.limits.timeout_seconds ?? null
  profileForm.input_per_1m_tokens = item?.pricing.input_per_1m_tokens ?? null
  profileForm.output_per_1m_tokens = item?.pricing.output_per_1m_tokens ?? null
  profileForm.image_output_unit_price = item?.pricing.image_output_unit_price ?? null
  profileForm.image_edit_unit_price = item?.pricing.image_edit_unit_price ?? null
  profileForm.notes = item?.notes || ''
  profileModalOpen.value = true
  void nextTick(() => profileFormRef.value?.restoreValidation())
}

async function saveProfile(): Promise<void> {
  if (!await validateForm(profileFormRef.value)) return
  const credential = credentials.value.find((item) => item.credential_id === profileForm.credential_id)
  if (!credential) {
    message.error(t('modelPool.selectCredentialFirst'))
    return
  }
  if (!providerSupportsKind(credential.provider, profileForm.kind)) {
    message.error(t('modelPool.credentialKindMismatch'))
    return
  }
  saving.value = true
  try {
    const isImageModel = profileForm.kind === 'image_generation'
    const isEmbeddingModel = profileForm.kind === 'embedding'
    const inputModalities = ['text']
    const outputModalities = isImageModel ? ['image'] : ['text']
    if (!isImageModel && !isEmbeddingModel && profileForm.image_input) inputModalities.push('image')
    if (!isImageModel && !isEmbeddingModel && profileForm.image_output) outputModalities.push('image')
    if (!isImageModel && !isEmbeddingModel && profileForm.audio_input) inputModalities.push('audio')
    if (!isImageModel && !isEmbeddingModel && profileForm.audio_output) outputModalities.push('audio')
    if (isImageModel && (profileForm.image_to_image || profileForm.image_edit)) inputModalities.push('image')
    const payload = {
      display_name: profileForm.display_name,
      description: profileForm.description,
      kind: profileForm.kind,
      provider: credential.provider,
      credential_id: profileForm.credential_id,
      model_name: profileForm.model_name,
      embedding_dimensions: isEmbeddingModel ? profileForm.embedding_dimensions : null,
      embedding_batch_size: isEmbeddingModel ? profileForm.embedding_batch_size : null,
      enabled: profileEditing.value?.enabled ?? true,
      capabilities: {
        input_modalities: inputModalities,
        output_modalities: outputModalities,
        tool_calling: !isImageModel && !isEmbeddingModel && profileForm.tool_calling,
        streaming_tool_calls: false,
        strict_tool_schema: false,
        structured_output_methods: isImageModel || isEmbeddingModel ? [] : ['json_mode', 'function_calling'],
        reasoning_supported: !isImageModel && !isEmbeddingModel && profileForm.reasoning_supported,
        reasoning_efforts: [],
        reasoning_content: !isImageModel && !isEmbeddingModel && profileForm.reasoning_supported,
        cache_usage: false,
        text_to_image: isImageModel && profileForm.text_to_image,
        image_to_image: isImageModel && profileForm.image_to_image,
        image_edit: isImageModel && profileForm.image_edit,
        multi_image_reference: isImageModel && profileForm.multi_image_reference,
        batch_generation: isImageModel && profileForm.batch_generation,
      },
      limits: {
        max_input_tokens: isImageModel || isEmbeddingModel ? null : profileForm.max_input_tokens,
        compression_trigger_tokens: isImageModel || isEmbeddingModel ? null : profileForm.compression_trigger_tokens,
        max_output_tokens: isImageModel || isEmbeddingModel ? null : profileForm.max_output_tokens,
        timeout_seconds: profileForm.timeout_seconds,
      },
      settings: {
        temperature: isImageModel || isEmbeddingModel ? null : profileForm.temperature,
      },
      pricing: {
        currency: 'CNY',
        input_per_1m_tokens: isImageModel ? null : profileForm.input_per_1m_tokens,
        output_per_1m_tokens: isImageModel || isEmbeddingModel ? null : profileForm.output_per_1m_tokens,
        image_output_unit_price: isImageModel ? profileForm.image_output_unit_price : null,
        image_edit_unit_price: isImageModel ? profileForm.image_edit_unit_price : null,
      },
      notes: profileForm.notes,
    }
    if (profileEditing.value) {
      Object.assign(payload, { expected_revision: profileEditing.value.revision })
      const response = await modelPoolApi.patchProfile(profileEditing.value.profile_id, payload)
      upsertProfile(response.profile)
    } else {
      const response = await modelPoolApi.saveProfile(payload)
      upsertProfile(response.profile)
    }
    profileModalOpen.value = false
    message.success(t('modelPool.profileSaved'))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    saving.value = false
  }
}

async function setCredentialEnabled(item: ModelPoolCredential, enabled: boolean): Promise<void> {
  try {
    const response = await modelPoolApi.patchCredential(item.credential_id, {
      enabled,
      expected_revision: item.revision,
    })
    upsertCredential(response.credential)
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  }
}

async function setProfileEnabled(item: ModelPoolProfile, enabled: boolean): Promise<void> {
  try {
    const response = await modelPoolApi.patchProfile(item.profile_id, {
      enabled,
      expected_revision: item.revision,
    })
    upsertProfile(response.profile)
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  }
}

async function pingProfile(profile: ModelPoolProfile): Promise<void> {
  testingProfileId.value = profile.profile_id
  try {
    const result = await modelPoolApi.pingProfile(profile.profile_id)
    if (profile.kind === 'image_generation' && result.image_base64 && result.mime_type) {
      imageTestPreview.value = {
        url: `data:${result.mime_type};base64,${result.image_base64}`,
        model: profile.display_name,
      }
    }
    message.success(profile.kind === 'embedding'
      ? t('modelPool.embeddingConnectionSucceeded', { latency: result.latency_ms, dimensions: result.dimensions || '-' })
      : profile.kind === 'image_generation'
        ? t('modelPool.imageConnectionSucceeded', { latency: result.latency_ms })
        : t('modelPool.connectionSucceeded', { latency: result.latency_ms }))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.requestFailed'))
  } finally {
    testingProfileId.value = null
  }
}

function confirmDeleteCredential(item: ModelPoolCredential): void {
  dialog.warning({
    title: t('modelPool.deleteCredential'),
    content: item.display_name,
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      deletingCredentialId.value = item.credential_id
      try {
        const response = await modelPoolApi.deleteCredential(item.credential_id)
        if (response.deleted) {
          credentials.value = credentials.value.filter(
            credential => credential.credential_id !== item.credential_id,
          )
        }
        message.success(t('modelPool.credentialDeleted'))
      } catch (error) {
        message.error(error instanceof Error ? error.message : t('common.requestFailed'))
        return false
      } finally {
        deletingCredentialId.value = null
      }
      return true
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
      deletingProfileId.value = item.profile_id
      try {
        const response = await modelPoolApi.deleteProfile(item.profile_id)
        if (response.deleted) {
          profiles.value = profiles.value.filter(profile => profile.profile_id !== item.profile_id)
        }
        message.success(t('modelPool.profileDeleted'))
      } catch (error) {
        message.error(error instanceof Error ? error.message : t('common.requestFailed'))
        return false
      } finally {
        deletingProfileId.value = null
      }
      return true
    },
  })
}

function providerLabel(providerId: string): string {
  return providers.value.find((item) => item.provider_id === providerId)?.display_name || providerId
}

function providerSupportsKind(providerId: string, kind: 'chat' | 'embedding' | 'image_generation'): boolean {
  return providers.value.some((item) => {
    if (item.provider_id !== providerId) return false
    return item.supported_kinds?.includes(kind) ?? item.kind === kind
  })
}

function providerImageCapability(name: string): boolean {
  const credential = credentials.value.find(item => item.credential_id === profileForm.credential_id)
  const provider = providers.value.find(item => item.provider_id === credential?.provider && item.kind === 'image_generation')
  return provider?.capabilities?.[name] === true
}

function firstCredentialForKind(kind: 'chat' | 'embedding' | 'image_generation'): ModelPoolCredential | undefined {
  return credentials.value.find((item) => providerSupportsKind(item.provider, kind))
}

function bindingOptions(kind: 'chat' | 'embedding' | 'image_generation'): Array<{ label: string; value: string }> {
  return profiles.value
    .filter((item) => item.kind === kind && item.enabled && item.credential?.enabled !== false && item.credential?.has_api_key)
    .map((item) => ({ label: `${item.display_name} · ${item.model_name}`, value: item.profile_id }))
}

function uniqueProviders(): ModelProviderProfile[] {
  const seen = new Set<string>()
  const result: ModelProviderProfile[] = []
  for (const provider of providers.value) {
    if (seen.has(provider.provider_id)) continue
    seen.add(provider.provider_id)
    result.push(provider)
  }
  return result
}

function capabilityTags(profile: ModelPoolProfile): string[] {
  const tags: string[] = []
  if (profile.kind === 'embedding') {
    if (profile.embedding_dimensions) tags.push(`${t('modelPool.embeddingDimensions')}: ${profile.embedding_dimensions}`)
    if (profile.embedding_batch_size) tags.push(`${t('modelPool.embeddingBatchSize')}: ${profile.embedding_batch_size}`)
    return tags
  }
  if (profile.kind === 'image_generation') {
    if (profile.capabilities.text_to_image) tags.push(t('modelPool.textToImage'))
    if (profile.capabilities.image_to_image) tags.push(t('modelPool.imageToImage'))
    if (profile.capabilities.image_edit) tags.push(t('modelPool.imageEdit'))
    if (profile.capabilities.multi_image_reference) tags.push(t('modelPool.multiImageReference'))
    return tags
  }
  if (profile.capabilities.tool_calling) tags.push(t('modelPool.toolsTag'))
  if (profile.capabilities.input_modalities.includes('image')) tags.push(t('modelPool.imageInput'))
  if (profile.capabilities.output_modalities.includes('image')) tags.push(t('modelPool.imageOutput'))
  if (profile.capabilities.input_modalities.includes('audio')) tags.push(t('modelPool.audioInput'))
  if (profile.capabilities.output_modalities.includes('audio')) tags.push(t('modelPool.audioOutput'))
  if (profile.capabilities.reasoning_supported) tags.push(t('modelPool.reasoning'))
  return tags
}

function formatTokens(value: number | null | undefined): string {
  const numeric = Number(value || 0)
  if (numeric >= 1000000) return `${Math.round(numeric / 100000) / 10}M`
  if (numeric >= 1000) return `${Math.round(numeric / 1000)}K`
  return String(numeric)
}

function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(Number(value || 0))
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `${Math.round(Number(value) * 1000) / 10}%`
}

function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(Number(value || 0))}`
}
</script>

<style scoped>
.model-pool-view {
  height: 100%;
  padding: clamp(20px, 3vw, 42px);
  overflow: auto;
  background: var(--app-surface);
}

.model-pool-view > * { width: min(1280px, 100%); margin-inline: auto; }

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
  overflow: hidden;
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.model-list :deep(.n-list-item) {
  padding: 18px 20px;
  transition: background-color var(--app-transition-fast);
}

.model-list :deep(.n-list-item:hover) { background: var(--app-surface-muted); }

.role-binding-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.role-binding-panel:focus {
  border-color: var(--app-border-focus);
  box-shadow: 0 0 0 3px var(--app-focus-shadow);
  outline: none;
}

.role-binding-grid {
  margin: 0;
}

.usage-range-select {
  width: 132px;
}

.usage-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.usage-metric {
  display: flex;
  min-height: 72px;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.usage-metric span {
  color: var(--app-text-muted);
  font-size: 12px;
}

.usage-metric strong {
  color: var(--app-text);
  font-size: 22px;
  font-weight: 650;
  line-height: 1.1;
}

.usage-chart-panel {
  min-height: 320px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.usage-chart {
  width: 100%;
  height: 320px;
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

.credential-editor-form,
.profile-editor-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  gap: 20px;
}

.model-credential-modal {
  --editor-modal-width: 900px;
}

.model-profile-modal {
  --editor-modal-width: 1120px;
}

.model-editor-pane {
  box-sizing: border-box;
  min-width: 0;
  height: 100%;
  padding: 20px;
  border: 1px solid var(--app-border);
  border-radius: 18px;
  background: var(--app-surface);
}

.model-editor-pane__header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 20px;
}

.model-editor-pane__header > span {
  display: grid;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 12px;
  color: var(--app-surface);
  background: var(--app-text);
  font-size: 11px;
  font-weight: 750;
}

.model-editor-pane__header > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.model-editor-pane__header strong {
  color: var(--app-text);
  font-size: 15px;
  line-height: 1.3;
}

.model-editor-pane__header small {
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.model-editor-field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.model-capability-field :deep(.n-space) {
  gap: 12px 20px !important;
}

.profile-editor-form .form-grid {
  gap: 0 14px;
  padding-top: 16px;
  border-top: 1px solid var(--app-divider);
}

.profile-editor-form :deep(.n-form-item),
.credential-editor-form :deep(.n-form-item) {
  min-width: 0;
}

.manager-empty {
  padding: 48px 0;
}
.image-test-preview { display: grid; gap: 10px; justify-items: center; }.image-test-preview img { display: block; max-width: 100%; max-height: 520px; object-fit: contain; }

@media (max-width: 720px) {
  .context-bar,
  .content-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .credential-editor-form,
  .profile-editor-form {
    grid-template-columns: 1fr;
  }

  .model-editor-field-grid {
    grid-template-columns: 1fr;
  }

  .usage-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
