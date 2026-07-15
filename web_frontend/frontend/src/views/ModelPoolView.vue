<template>
  <div class="local-model-view app-scroll-y">
    <div class="context-bar">
      <div class="context-title">
        <div class="title-line">
          <span class="title-icon"><n-icon><HardwareChipOutline /></n-icon></span>
          <n-text strong class="page-title">{{ t('localModel.title') }}</n-text>
        </div>
        <n-text depth="3" class="context-subtitle">{{ t('localModel.subtitle') }}</n-text>
      </div>
      <n-button secondary :loading="loading" @click="refresh">
        <template #icon><n-icon><Refresh /></n-icon></template>
        {{ t('common.refresh') }}
      </n-button>
    </div>

    <section class="overview-grid">
      <article class="overview-card runtime-card" :class="rocm?.available ? 'is-ready' : 'is-warning'">
        <div class="overview-icon"><n-icon><HardwareChipOutline /></n-icon></div>
        <div class="overview-copy">
          <div class="overview-label">{{ t('localModel.rocmRuntime') }}</div>
          <div v-if="rocm?.available" class="overview-value">
            ROCm {{ rocm.rocm_version || '—' }}
          </div>
          <div v-else class="overview-value">{{ t('localModel.rocmUnchecked') }}</div>
          <div v-if="rocm?.available" class="overview-detail">
            PyTorch {{ rocm.torch_version }} · HIP {{ rocm.hip_version }} ·
            {{ t('localModel.deviceCount', { count: rocm.device_count }) }}
          </div>
          <div v-else class="overview-detail">{{ rocm?.error || t('localModel.rocmUnchecked') }}</div>
          <div v-if="rocm?.available && rocm.devices.length" class="runtime-device-list">
            <div v-for="device in rocm.devices" :key="device.index" class="runtime-device">
              <div class="runtime-device-heading">
                <strong>{{ device.name }}</strong>
                <span>{{ device.pci_bus || `GPU ${device.index}` }}</span>
              </div>
              <div class="runtime-metrics">
                <span>{{ t('localModel.gpuUsage') }} {{ formatPercent(device.gpu_utilization_percent) }}</span>
                <span>{{ t('localModel.vramUsage') }} {{ formatMemoryUsage(device) }}</span>
                <span>{{ t('localModel.gpuTemperature') }} {{ formatTemperature(device.temperature_hotspot_celsius) }}</span>
                <span>{{ t('localModel.gpuPower') }} {{ formatPower(device.power_watts) }}</span>
                <span v-if="device.architecture">{{ device.architecture }}</span>
                <span v-if="device.compute_units">{{ device.compute_units }} CU</span>
                <span v-if="device.vram_type">{{ device.vram_type }}</span>
              </div>
            </div>
          </div>
        </div>
        <span class="status-dot" aria-hidden="true" />
      </article>

      <article class="overview-card">
        <div class="overview-icon"><n-icon><LayersOutline /></n-icon></div>
        <div class="overview-copy">
          <div class="overview-label">{{ t('localModel.profiles') }}</div>
          <div class="overview-value">{{ profiles.length }}</div>
          <div class="overview-detail">{{ t('localModel.profileHint') }}</div>
        </div>
      </article>

      <article class="overview-card">
        <div class="overview-icon"><n-icon><FolderOpenOutline /></n-icon></div>
        <div class="overview-copy">
          <div class="overview-label">{{ t('localModel.artifacts') }}</div>
          <div class="overview-value">{{ artifacts.length }}</div>
          <div class="overview-detail">{{ t('localModel.artifactHint') }}</div>
        </div>
      </article>
    </section>

    <section class="model-panel">
      <n-alert v-if="modelStorage?.remote_error" type="warning" :show-icon="true" class="remote-endpoint-alert">
        {{ modelStorage.remote_error }}
      </n-alert>
      <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="profiles" :tab="t('localModel.profiles')">
        <div class="tab-content">
          <div class="content-header">
            <div>
              <n-text strong class="section-title">{{ t('localModel.profiles') }}</n-text>
              <div class="section-description">{{ t('localModel.profileHint') }}</div>
            </div>
            <n-button type="primary" :disabled="!artifacts.length" @click="openProfile()">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ t('localModel.addProfile') }}
            </n-button>
          </div>
          <div v-if="profiles.length" class="resource-grid">
            <article v-for="profile in profiles" :key="profile.profile_id" class="resource-card">
              <header class="resource-header">
                <div class="resource-identity">
                  <span class="resource-icon"><n-icon><CubeOutline /></n-icon></span>
                  <div class="resource-title-block">
                    <div class="resource-title">{{ profile.display_name }}</div>
                    <div class="resource-id">{{ profile.profile_id }}</div>
                  </div>
                </div>
                <div class="profile-status-tags">
                  <n-tag size="small" :bordered="false" :type="profile.enabled ? 'success' : 'default'">
                    {{ profile.enabled ? t('common.enabled') : t('common.disabled') }}
                  </n-tag>
                  <n-tag size="small" :bordered="false" :type="runtimeTagType(profile)">
                    {{ runtimePhaseLabel(profile) }}
                  </n-tag>
                </div>
              </header>

              <div class="tag-row">
                <n-tag size="small" :bordered="false">{{ kindLabel(profile.kind) }}</n-tag>
                <n-tag size="small" :bordered="false" type="info">{{ engineLabel(profile.engine) }}</n-tag>
                <n-tag v-if="profile.capabilities.input_modalities.includes('image')" size="small" :bordered="false" type="success">
                  {{ t('localModel.imageInput') }}
                </n-tag>
                <n-tag
                  v-for="role in profileDefaultRoles(profile.profile_id)"
                  :key="role"
                  size="small"
                  :bordered="false"
                  type="success"
                >
                  {{ defaultRoleLabel(role) }}
                </n-tag>
              </div>

              <div class="model-name">{{ profile.served_model_name }}</div>
              <div class="path-line" :title="artifactLocation(profile.artifact)">
                <n-icon><FolderOpenOutline /></n-icon>
                <span>{{ artifactLocation(profile.artifact) }}</span>
              </div>

              <div v-if="profileRuntime(profile)" class="profile-runtime-panel">
                <div class="profile-runtime-heading">
                  <span>{{ runtimeStageLabel(profileRuntime(profile)?.stage) }}</span>
                  <strong>{{ rocm?.devices?.[0] ? formatMemoryUsage(rocm.devices[0]) : '—' }}</strong>
                </div>
                <n-progress
                  v-if="isRuntimeTransitioning(profile)"
                  type="line"
                  :percentage="profileRuntime(profile)?.progress_percent ?? 0"
                  :processing="profileRuntime(profile)?.progress_percent == null"
                  :show-indicator="profileRuntime(profile)?.progress_percent != null"
                  status="info"
                />
                <div v-if="profileRuntime(profile)?.error" class="runtime-error">
                  {{ profileRuntime(profile)?.error }}
                </div>
              </div>

              <div class="spec-grid">
                <template v-if="profile.kind === 'chat' && profile.engine !== 'external'">
                  <div class="spec-item"><span>{{ t('localModel.gpuLayers') }}</span><strong>{{ chatInference(profile)?.gpu_layers }}</strong></div>
                  <div class="spec-item"><span>{{ t('localModel.parallelSlots') }}</span><strong>{{ chatInference(profile)?.parallel_slots }}</strong></div>
                  <div class="spec-item"><span>{{ t('localModel.kvCache') }}</span><strong>{{ chatInference(profile)?.cache_type_k }} / {{ chatInference(profile)?.cache_type_v }}</strong></div>
                </template>
                <div v-else-if="profile.engine === 'external'" class="spec-item"><span>{{ t('localModel.runtimeMode') }}</span><strong>{{ t('localModel.externalEndpoint') }}</strong></div>
                <div v-else class="spec-item"><span>{{ t('localModel.embeddingDimensions') }}</span><strong>{{ profile.embedding_dimensions || '—' }}</strong></div>
                <div class="spec-item"><span>{{ t('modelPool.maxInput') }}</span><strong>{{ formatTokens(profile.limits.max_input_tokens) }}</strong></div>
              </div>

              <footer class="resource-actions">
                <n-button
                  v-if="profileRuntime(profile)?.phase === 'ready'"
                  size="small"
                  secondary
                  @click="restartProfile(profile)"
                >
                  {{ t('localModel.restart') }}
                </n-button>
                <n-button
                  v-if="profileRuntime(profile)?.phase === 'ready'"
                  size="small"
                  secondary
                  @click="unloadProfile(profile)"
                >
                  {{ t('localModel.unload') }}
                </n-button>
                <n-button
                  v-else
                  size="small"
                  secondary
                  :disabled="!profile.enabled"
                  :loading="isRuntimeTransitioning(profile)"
                  @click="loadProfile(profile)"
                >
                  {{ t('localModel.load') }}
                </n-button>
                <n-dropdown
                  trigger="click"
                  :options="defaultRoleOptions(profile)"
                  @select="(role) => handleDefaultRoleSelect(role, profile)"
                >
                  <n-button size="small" quaternary :disabled="profileRuntime(profile)?.phase !== 'ready'">
                    {{ t('localModel.setDefault') }}
                  </n-button>
                </n-dropdown>
                <div class="action-spacer" />
                <n-button size="small" quaternary @click="openProfile(profile)">{{ t('common.edit') }}</n-button>
                <n-button size="small" type="error" quaternary @click="removeProfile(profile)">{{ t('common.delete') }}</n-button>
              </footer>
            </article>
          </div>
          <div v-else class="empty-panel">
            <span class="empty-icon"><n-icon><LayersOutline /></n-icon></span>
            <n-text strong>{{ t('localModel.noProfiles') }}</n-text>
            <p>{{ t('localModel.profileHint') }}</p>
            <n-button type="primary" @click="openProfileEmptyAction">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ artifacts.length ? t('localModel.addProfile') : t('localModel.addArtifact') }}
            </n-button>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="artifacts" :tab="t('localModel.artifacts')">
        <div class="tab-content">
          <div class="content-header">
            <div>
              <n-text strong class="section-title">{{ t('localModel.artifacts') }}</n-text>
              <div class="section-description">{{ t('localModel.artifactHint') }}</div>
              <div v-if="modelStorage?.inference_mode !== 'external'" class="storage-root">
                <span>{{ t('localModel.storageRoot') }}</span>
                <code>{{ modelStorage?.root_path || '—' }}</code>
              </div>
              <div v-else class="storage-root">
                <span>{{ t('localModel.runtimeMode') }}</span>
                <code>{{ t('localModel.externalEndpoint') }}</code>
              </div>
            </div>
            <n-button type="primary" @click="openArtifact()">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ t('localModel.addArtifact') }}
            </n-button>
          </div>
          <div v-if="artifacts.length" class="resource-grid">
            <article v-for="artifact in artifacts" :key="artifact.artifact_id" class="resource-card artifact-card">
              <header class="resource-header">
                <div class="resource-identity">
                  <span class="resource-icon"><n-icon><FolderOpenOutline /></n-icon></span>
                  <div class="resource-title-block">
                    <div class="resource-title">{{ artifact.display_name }}</div>
                    <div class="resource-id">{{ artifact.artifact_id }}</div>
                  </div>
                </div>
                <n-tag size="small" :bordered="false" :type="artifact.enabled ? 'success' : 'default'">
                  {{ artifact.enabled ? t('common.enabled') : t('common.disabled') }}
                </n-tag>
              </header>

              <div class="tag-row">
                <n-tag size="small" :bordered="false">{{ kindLabel(artifact.kind) }}</n-tag>
                <n-tag size="small" :bordered="false" type="info">{{ artifact.model_format }}</n-tag>
                <n-tag v-if="artifact.revision" size="small" :bordered="false">{{ artifact.revision }}</n-tag>
              </div>

              <div class="path-block" :title="artifactLocation(artifact)">
                <span>{{ artifact.source === 'external_endpoint' ? t('localModel.remoteModel') : t('localModel.localPath') }}</span>
                <code>{{ artifactLocation(artifact) }}</code>
              </div>
              <div v-if="artifact.checksum" class="checksum-line">
                <span>{{ t('localModel.checksum') }}</span>
                <code>{{ artifact.checksum }}</code>
              </div>

              <footer class="resource-actions">
                <div class="action-spacer" />
                <n-button size="small" quaternary @click="openArtifact(artifact)">{{ t('common.edit') }}</n-button>
                <n-button size="small" type="error" quaternary @click="removeArtifact(artifact)">{{ t('common.delete') }}</n-button>
              </footer>
            </article>
          </div>
          <div v-else class="empty-panel">
            <span class="empty-icon"><n-icon><FolderOpenOutline /></n-icon></span>
            <n-text strong>{{ t('localModel.noArtifacts') }}</n-text>
            <p>{{ t('localModel.artifactHint') }}</p>
            <n-button type="primary" @click="openArtifact()">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ t('localModel.addArtifact') }}
            </n-button>
          </div>
        </div>
      </n-tab-pane>
      </n-tabs>
    </section>

    <n-modal v-model:show="artifactModalOpen" preset="dialog" :title="t('localModel.artifactEditor')">
      <n-form label-placement="top">
        <n-form-item :label="t('localModel.displayName')"><n-input v-model:value="artifactForm.display_name" /></n-form-item>
        <n-form-item :label="t('localModel.kind')">
          <n-select v-model:value="artifactForm.kind" :options="kindOptions" @update:value="syncArtifactKind" />
        </n-form-item>
        <n-form-item v-if="externalInference" :label="t('localModel.remoteModel')">
          <n-select
            v-model:value="artifactForm.external_model_id"
            :options="remoteModelOptions"
            :placeholder="t('localModel.remoteModelPlaceholder')"
            filterable
            @update:value="syncRemoteModel"
          />
        </n-form-item>
        <div v-if="externalInference && selectedRemoteModel" class="model-directory-summary">
          <div class="model-directory-heading">
            <strong>{{ selectedRemoteModel.model_id }}</strong>
            <span>{{ kindLabel(selectedRemoteModel.kind) }}</span>
            <span v-if="selectedRemoteModel.format">{{ selectedRemoteModel.format }}</span>
            <span v-if="selectedRemoteModel.context_length">{{ formatTokens(selectedRemoteModel.context_length) }} context</span>
            <span v-if="selectedRemoteModel.embedding_dimensions">{{ selectedRemoteModel.embedding_dimensions }}D</span>
          </div>
          <code>{{ formatBytes(selectedRemoteModel.size_bytes) }}</code>
        </div>
        <n-form-item v-if="!externalInference" :label="t('localModel.detectedDirectory')">
          <n-select
            v-model:value="artifactForm.local_path"
            :options="modelDirectoryOptions"
            :placeholder="t('localModel.detectedDirectoryPlaceholder')"
            filterable
          />
        </n-form-item>
        <div v-if="selectedModelDirectory" class="model-directory-summary">
          <div class="model-directory-heading">
            <strong>{{ selectedModelDirectory.display_name }}</strong>
            <span v-if="selectedModelDirectory.model_type">{{ selectedModelDirectory.model_type }}</span>
            <span v-if="selectedModelDirectory.dtype">{{ selectedModelDirectory.dtype }}</span>
            <span v-for="architecture in selectedModelDirectory.architectures" :key="architecture">
              {{ architecture }}
            </span>
          </div>
          <code :title="selectedModelDirectory.relative_path">{{ selectedModelDirectory.relative_path }}</code>
        </div>
        <div v-if="!externalInference" class="storage-hint">
          {{ t('localModel.modelscopeCache') }}：<code>{{ modelStorage?.modelscope_cache_path || '—' }}</code>
        </div>
        <n-checkbox v-model:checked="artifactForm.enabled">{{ t('common.enabled') }}</n-checkbox>
      </n-form>
      <template #action>
        <n-button @click="artifactModalOpen = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="saving" @click="saveArtifact">{{ t('common.save') }}</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="profileModalOpen" preset="dialog" :title="t('localModel.profileEditor')" style="width: min(760px, 92vw)">
      <n-form label-placement="top">
        <n-form-item :label="t('localModel.displayName')"><n-input v-model:value="profileForm.display_name" /></n-form-item>
        <n-form-item :label="t('localModel.artifact')">
          <n-select v-model:value="profileForm.artifact_id" :options="artifactOptions" @update:value="syncProfileKind" />
        </n-form-item>
        <n-form-item :label="t('localModel.servedModelName')"><n-input v-model:value="profileForm.served_model_name" /></n-form-item>
        <div class="form-grid">
          <n-form-item v-if="profileForm.kind === 'chat' && !externalInference" :label="t('localModel.gpuLayers')">
            <n-input-number v-model:value="profileForm.gpu_layers" :min="0" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat' && !externalInference" :label="t('localModel.parallelSlots')">
            <n-input-number v-model:value="profileForm.parallel_slots" :min="1" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat' && !externalInference" :label="t('localModel.kCacheType')">
            <n-select v-model:value="profileForm.cache_type_k" :options="cacheTypeOptions" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat' && !externalInference" :label="t('localModel.vCacheType')">
            <n-select v-model:value="profileForm.cache_type_v" :options="cacheTypeOptions" />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxInput')">
            <n-input-number v-model:value="profileForm.max_input_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxOutput')">
            <n-input-number v-model:value="profileForm.max_output_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('localModel.contextCompressionThreshold')">
            <n-input-number v-model:value="profileForm.context_compression_threshold_tokens" :min="1000" clearable />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'embedding'" :label="t('localModel.embeddingDimensions')">
            <n-input-number v-model:value="profileForm.embedding_dimensions" :min="1" />
          </n-form-item>
        </div>
        <n-space vertical>
          <n-checkbox v-model:checked="profileForm.enabled">{{ t('localModel.loadWhenEnabled') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat' && !externalInference" v-model:checked="profileForm.flash_attention">{{ t('localModel.flashAttention') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'embedding'" v-model:checked="profileForm.trust_remote_code">{{ t('localModel.trustRemoteCode') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.tool_calling">{{ t('modelPool.toolCalling') }}</n-checkbox>
          <n-checkbox
            v-if="profileForm.kind === 'chat' && profileSupportsImage"
            v-model:checked="profileForm.image_input"
          >
            {{ t('localModel.imageInput') }}
          </n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.reasoning_supported">{{ t('modelPool.reasoning') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'embedding'" v-model:checked="profileForm.normalize_embeddings">{{ t('localModel.normalizeEmbeddings') }}</n-checkbox>
        </n-space>
      </n-form>
      <template #action>
        <n-button @click="profileModalOpen = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="saving" @click="saveProfile">{{ t('common.save') }}</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import {
  Add,
  CubeOutline,
  FolderOpenOutline,
  HardwareChipOutline,
  LayersOutline,
  Refresh,
} from '@/components/icons'
import {
  modelPoolApi,
  type LocalModelArtifact,
  type LocalModelDefaultRole,
  type LocalModelDefaults,
  type LocalModelStorage,
  type LocalModelKind,
  type LocalModelProfile,
  type LocalModelRuntime,
  type RocmRuntimeInfo,
} from '@/api/modelPool'

const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const runtimeRefreshing = ref(false)
const activeTab = ref<'profiles' | 'artifacts'>('profiles')
const artifacts = ref<LocalModelArtifact[]>([])
const profiles = ref<LocalModelProfile[]>([])
const runtimes = ref<LocalModelRuntime[]>([])
const defaults = ref<LocalModelDefaults>({
  main: null,
  task: null,
  compression: null,
  embedding: null,
})
const rocm = ref<RocmRuntimeInfo | null>(null)
const modelStorage = ref<LocalModelStorage | null>(null)
const artifactModalOpen = ref(false)
const profileModalOpen = ref(false)
const artifactEditing = ref<LocalModelArtifact | null>(null)
const profileEditing = ref<LocalModelProfile | null>(null)

const artifactForm = reactive({
  display_name: '', kind: 'chat' as LocalModelKind, local_path: '', external_model_id: '',
  revision: '', checksum: '', enabled: true,
})
const profileForm = reactive({
  display_name: '', artifact_id: '', kind: 'chat' as LocalModelKind,
  served_model_name: '', gpu_layers: 99, parallel_slots: 1,
  cache_type_k: 'f16', cache_type_v: 'f16', flash_attention: true,
  max_input_tokens: null as number | null,
  max_output_tokens: null as number | null, context_compression_threshold_tokens: null as number | null,
  embedding_dimensions: null as number | null,
  trust_remote_code: false, tool_calling: true, reasoning_supported: false,
  image_input: false,
  normalize_embeddings: true, enabled: true,
})

const kindOptions = computed(() => [
  { label: t('localModel.chat'), value: 'chat' },
  { label: t('localModel.embedding'), value: 'embedding' },
])
const artifactOptions = computed(() => artifacts.value.map((item) => ({
  label: `${item.display_name} · ${item.kind}`,
  value: item.artifact_id,
})))
const cacheTypeOptions = ['f16', 'bf16', 'q8_0', 'q4_0'].map((value) => ({ label: value.toUpperCase(), value }))
const externalInference = computed(() => modelStorage.value?.inference_mode === 'external')
const remoteModelOptions = computed(() => (modelStorage.value?.remote_models || [])
  .filter((item) => item.kind === artifactForm.kind)
  .map((item) => ({
    label: [
      item.model_id,
      item.format,
      item.kind === 'embedding' && item.embedding_dimensions
        ? `${item.embedding_dimensions}D`
        : formatTokens(item.context_length),
    ].filter(Boolean).join(' · '),
    value: item.model_id,
  })))
const modelDirectoryOptions = computed(() => {
  const options = (modelStorage.value?.directories || [])
    .filter((item) => item.supported_kinds.includes(artifactForm.kind))
    .map((item) => ({
      label: [item.display_name, item.model_type, item.dtype].filter(Boolean).join(' · '),
      value: item.absolute_path,
    }))
  const currentPath = artifactForm.local_path
  if (currentPath && !options.some((item) => item.value === currentPath)) {
    options.unshift({ label: currentPath, value: currentPath })
  }
  return options
})
const selectedModelDirectory = computed(() => (
  modelStorage.value?.directories.find((item) => item.absolute_path === artifactForm.local_path) || null
))
const selectedRemoteModel = computed(() => (
  modelStorage.value?.remote_models.find((item) => (
    item.model_id === artifactForm.external_model_id && item.kind === artifactForm.kind
  )) || null
))
const profileRemoteModel = computed(() => {
  const artifact = artifacts.value.find((item) => item.artifact_id === profileForm.artifact_id)
  return artifact ? remoteModelForArtifact(artifact) : null
})
const profileSupportsImage = computed(() => (
  profileRemoteModel.value?.capabilities.includes('multimodal') || false
))

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [artifactData, profileData, runtimeData, defaultData, storageData] = await Promise.all([
      modelPoolApi.artifacts(),
      modelPoolApi.profiles(),
      modelPoolApi.runtimes(),
      modelPoolApi.defaults(),
      modelPoolApi.storage(),
    ])
    artifacts.value = artifactData.artifacts
    profiles.value = profileData.profiles
    runtimes.value = runtimeData.runtimes
    rocm.value = runtimeData.rocm
    defaults.value = defaultData.defaults
    modelStorage.value = storageData
  } catch (error) {
    message.error(errorText(error))
  } finally {
    loading.value = false
  }
}

function openArtifact(item?: LocalModelArtifact): void {
  artifactEditing.value = item || null
  artifactForm.display_name = item?.display_name || ''
  artifactForm.kind = item?.kind || 'chat'
  artifactForm.local_path = item?.local_path || ''
  artifactForm.external_model_id = item?.external_model_id || ''
  artifactForm.revision = item?.revision || ''
  artifactForm.checksum = item?.checksum || ''
  artifactForm.enabled = item?.enabled ?? true
  artifactModalOpen.value = true
}

async function saveArtifact(): Promise<void> {
  saving.value = true
  try {
    const payload = {
      ...artifactForm,
      source: externalInference.value ? 'external_endpoint' : 'local_storage',
      local_path: externalInference.value ? null : artifactForm.local_path,
      model_format: externalInference.value
        ? selectedRemoteModel.value?.format || 'external'
        : artifactForm.kind === 'chat' ? 'llama_cpp' : 'transformers',
      artifact_id: artifactEditing.value?.artifact_id,
    }
    if (artifactEditing.value) await modelPoolApi.patchArtifact(artifactEditing.value.artifact_id, payload)
    else await modelPoolApi.saveArtifact(payload)
    artifactModalOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) } finally { saving.value = false }
}

function openProfile(item?: LocalModelProfile): void {
  const artifact = item?.artifact || artifacts.value[0]
  const kind = item?.kind || artifact?.kind || 'chat'
  const directory = artifact ? directoryForArtifact(artifact) : null
  const remoteModel = artifact ? remoteModelForArtifact(artifact) : null
  profileEditing.value = item || null
  profileForm.display_name = item?.display_name || artifact?.display_name || ''
  profileForm.artifact_id = item?.artifact_id || artifact?.artifact_id || ''
  profileForm.kind = kind
  profileForm.served_model_name = item?.served_model_name || artifact?.external_model_id || artifact?.display_name || ''
  const chatInference = item?.kind === 'chat' ? item.inference : null
  const embeddingInference = item?.kind === 'embedding' ? item.inference : null
  profileForm.gpu_layers = chatInference && 'gpu_layers' in chatInference ? chatInference.gpu_layers : 99
  profileForm.parallel_slots = chatInference && 'parallel_slots' in chatInference ? chatInference.parallel_slots : 1
  profileForm.cache_type_k = chatInference && 'cache_type_k' in chatInference ? chatInference.cache_type_k : 'f16'
  profileForm.cache_type_v = chatInference && 'cache_type_v' in chatInference ? chatInference.cache_type_v : 'f16'
  profileForm.flash_attention = chatInference && 'flash_attention' in chatInference ? chatInference.flash_attention : true
  profileForm.max_input_tokens = item?.limits.max_input_tokens ?? remoteModel?.context_length ?? null
  profileForm.max_output_tokens = item?.limits.max_output_tokens ?? null
  profileForm.context_compression_threshold_tokens = item?.limits.context_compression_threshold_tokens ?? null
  profileForm.embedding_dimensions = item?.embedding_dimensions
    ?? remoteModel?.embedding_dimensions
    ?? directory?.embedding_dimensions
    ?? null
  profileForm.trust_remote_code = embeddingInference && 'trust_remote_code' in embeddingInference
    ? embeddingInference.trust_remote_code
    : false
  profileForm.tool_calling = item?.capabilities.tool_calling ?? true
  profileForm.image_input = item?.capabilities.input_modalities.includes('image')
    ?? remoteModel?.capabilities.includes('multimodal')
    ?? false
  profileForm.reasoning_supported = item?.capabilities.reasoning_supported ?? false
  profileForm.normalize_embeddings = item?.normalize_embeddings ?? true
  profileForm.enabled = item?.enabled ?? true
  profileModalOpen.value = true
}

function syncProfileKind(artifactId: string): void {
  const artifact = artifacts.value.find((item) => item.artifact_id === artifactId)
  if (!artifact) return
  const directory = directoryForArtifact(artifact)
  const remoteModel = remoteModelForArtifact(artifact)
  profileForm.kind = artifact.kind
  profileForm.display_name = artifact.display_name
  profileForm.served_model_name = artifact.external_model_id || artifact.display_name
  profileForm.gpu_layers = 99
  profileForm.parallel_slots = 1
  profileForm.cache_type_k = 'f16'
  profileForm.cache_type_v = 'f16'
  profileForm.flash_attention = true
  profileForm.image_input = remoteModel?.capabilities.includes('multimodal') || false
  profileForm.embedding_dimensions = remoteModel?.embedding_dimensions ?? directory?.embedding_dimensions ?? null
}

function syncRemoteModel(modelId: string): void {
  const model = modelStorage.value?.remote_models.find((item) => (
    item.model_id === modelId && item.kind === artifactForm.kind
  ))
  if (!model) return
  artifactForm.display_name = model.model_id
  artifactForm.kind = model.kind
}

function syncArtifactKind(): void {
  artifactForm.external_model_id = ''
  artifactForm.local_path = ''
}

function directoryForArtifact(artifact: LocalModelArtifact) {
  return modelStorage.value?.directories.find((directory) => directory.absolute_path === artifact.local_path)
}

function remoteModelForArtifact(artifact: LocalModelArtifact) {
  return modelStorage.value?.remote_models.find((model) => (
    model.model_id === artifact.external_model_id && model.kind === artifact.kind
  ))
}

function openProfileEmptyAction(): void {
  if (artifacts.value.length) {
    openProfile()
    return
  }
  activeTab.value = 'artifacts'
  openArtifact()
}

async function saveProfile(): Promise<void> {
  saving.value = true
  try {
    const isChat = profileForm.kind === 'chat'
    const payload = {
      profile_id: profileEditing.value?.profile_id,
      display_name: profileForm.display_name,
      kind: profileForm.kind,
      artifact_id: profileForm.artifact_id,
      engine: externalInference.value ? 'external' : isChat ? 'llama_cpp_rocm' : 'transformers_rocm',
      served_model_name: profileForm.served_model_name,
      enabled: profileForm.enabled,
      capabilities: {
        input_modalities: isChat && profileForm.image_input ? ['text', 'image'] : ['text'],
        output_modalities: ['text'],
        tool_calling: isChat && profileForm.tool_calling,
        streaming_tool_calls: false, strict_tool_schema: false,
        structured_output_methods: isChat ? ['function_calling', 'json_mode'] : [],
        reasoning_supported: isChat && profileForm.reasoning_supported,
        reasoning_efforts: [], reasoning_content: isChat && profileForm.reasoning_supported,
        cache_usage: false,
      },
      limits: {
        max_input_tokens: profileForm.max_input_tokens,
        max_output_tokens: profileForm.max_output_tokens,
        timeout_seconds: null,
        context_compression_threshold_tokens: isChat ? profileForm.context_compression_threshold_tokens : null,
      },
      inference: externalInference.value
        ? { external: true }
        : isChat
        ? {
            gpu_layers: profileForm.gpu_layers,
            parallel_slots: profileForm.parallel_slots,
            cache_type_k: profileForm.cache_type_k,
            cache_type_v: profileForm.cache_type_v,
            flash_attention: profileForm.flash_attention,
          }
        : { trust_remote_code: profileForm.trust_remote_code },
      embedding_dimensions: isChat ? null : profileForm.embedding_dimensions,
      normalize_embeddings: profileForm.normalize_embeddings,
      notes: '',
    }
    const result = profileEditing.value
      ? await modelPoolApi.patchProfile(profileEditing.value.profile_id, payload)
      : await modelPoolApi.saveProfile(payload)
    upsertRuntime(result.runtime)
    if (result.runtime.phase === 'failed') message.error(result.runtime.error)
    else if (profileForm.enabled) message.info(t('localModel.runtimeLoading'))
    profileModalOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) } finally { saving.value = false }
}

async function loadProfile(profile: LocalModelProfile): Promise<void> {
  try {
    const result = await modelPoolApi.loadProfile(profile.profile_id)
    upsertRuntime(result.runtime)
    if (result.runtime.phase === 'failed') message.error(result.runtime.error)
  } catch (error) { message.error(errorText(error)) }
}

async function unloadProfile(profile: LocalModelProfile): Promise<void> {
  try {
    const result = await modelPoolApi.unloadProfile(profile.profile_id)
    upsertRuntime(result.runtime)
    await refreshRuntimeState()
  } catch (error) { message.error(errorText(error)) }
}

async function restartProfile(profile: LocalModelProfile): Promise<void> {
  try {
    const result = await modelPoolApi.restartProfile(profile.profile_id)
    upsertRuntime(result.runtime)
    if (result.runtime.phase === 'failed') message.error(result.runtime.error)
  } catch (error) { message.error(errorText(error)) }
}

function profileRuntime(profile: LocalModelProfile): LocalModelRuntime | undefined {
  return runtimes.value.find((runtime) => runtime.profile_id === profile.profile_id)
}

function isRuntimeTransitioning(profile: LocalModelProfile): boolean {
  return ['starting', 'loading', 'stopping'].includes(profileRuntime(profile)?.phase || '')
}

function runtimeTagType(profile: LocalModelProfile): 'default' | 'info' | 'success' | 'error' | 'warning' {
  const phase = profileRuntime(profile)?.phase
  if (phase === 'ready') return 'success'
  if (phase === 'failed') return 'error'
  if (phase === 'starting' || phase === 'loading' || phase === 'stopping') return 'info'
  return profile.enabled ? 'warning' : 'default'
}

function runtimePhaseLabel(profile: LocalModelProfile): string {
  const phase = profileRuntime(profile)?.phase
  if (phase === 'ready') return t('localModel.runtimeReady')
  if (phase === 'failed') return t('localModel.runtimeFailed')
  if (phase === 'starting' || phase === 'loading') return t('localModel.runtimeLoading')
  if (phase === 'stopping') return t('localModel.runtimeStopping')
  return t('localModel.runtimeNotLoaded')
}

function runtimeStageLabel(stage?: string): string {
  const labels: Record<string, string> = {
    validating_runtime: t('localModel.runtimeStageValidating'),
    process_started: t('localModel.runtimeStageStarting'),
    loading_weights: t('localModel.runtimeStageWeights'),
    initializing_engine: t('localModel.runtimeStageEngine'),
    initializing_service: t('localModel.runtimeStageService'),
    ready: t('localModel.runtimeReady'),
    failed: t('localModel.runtimeFailed'),
  }
  return labels[stage || ''] || t('localModel.runtimeLoading')
}

function upsertRuntime(runtime: LocalModelRuntime): void {
  if (runtime.phase === 'idle') {
    runtimes.value = runtimes.value.filter((item) => item.profile_id !== runtime.profile_id)
    return
  }
  const next = runtimes.value.filter((item) => item.kind !== runtime.kind)
  next.push(runtime)
  runtimes.value = next
}

async function refreshRuntimeState(): Promise<void> {
  if (runtimeRefreshing.value) return
  runtimeRefreshing.value = true
  try {
    const summary = await modelPoolApi.runtimes()
    runtimes.value = summary.runtimes
    rocm.value = summary.rocm
  } catch {
    // The full page refresh already owns user-visible transport errors.
  } finally {
    runtimeRefreshing.value = false
  }
}

function profileDefaultRoles(profileId: string): LocalModelDefaultRole[] {
  return (Object.entries(defaults.value) as Array<[LocalModelDefaultRole, string | null]>)
    .filter(([, defaultProfileId]) => defaultProfileId === profileId)
    .map(([role]) => role)
}

function defaultRoleOptions(profile: LocalModelProfile) {
  const roles: LocalModelDefaultRole[] = profile.kind === 'embedding'
    ? ['embedding']
    : ['main', 'task', 'compression']
  return roles.map((role) => ({
    key: role,
    label: defaultRoleLabel(role),
    disabled: defaults.value[role] === profile.profile_id,
  }))
}

function defaultRoleLabel(role: LocalModelDefaultRole): string {
  return t(`localModel.defaultRole.${role}`)
}

async function handleDefaultRoleSelect(
  role: string | number,
  profile: LocalModelProfile,
): Promise<void> {
  const normalizedRole = String(role) as LocalModelDefaultRole
  try {
    const result = await modelPoolApi.setDefault(normalizedRole, profile.profile_id)
    defaults.value = { ...defaults.value, [normalizedRole]: result.profile_id }
    message.success(t('localModel.defaultUpdated'))
  } catch (error) {
    message.error(errorText(error))
  }
}

function removeArtifact(item: LocalModelArtifact): void {
  dialog.warning({
    title: t('common.delete'), content: item.display_name,
    positiveText: t('common.delete'), negativeText: t('common.cancel'),
    onPositiveClick: async () => { await modelPoolApi.deleteArtifact(item.artifact_id); await refresh() },
  })
}

function removeProfile(item: LocalModelProfile): void {
  dialog.warning({
    title: t('common.delete'), content: item.display_name,
    positiveText: t('common.delete'), negativeText: t('common.cancel'),
    onPositiveClick: async () => { await modelPoolApi.deleteProfile(item.profile_id); await refresh() },
  })
}

function kindLabel(kind: LocalModelKind): string {
  return kind === 'chat' ? t('localModel.chat') : t('localModel.embedding')
}

function engineLabel(engine: LocalModelProfile['engine']): string {
  if (engine === 'external') return t('localModel.externalEndpoint')
  return engine === 'llama_cpp_rocm' ? 'llama.cpp · ROCm' : 'Transformers · ROCm'
}

function artifactLocation(artifact?: LocalModelArtifact | null): string {
  return artifact?.external_model_id || artifact?.local_path || '—'
}

function chatInference(profile: LocalModelProfile) {
  return profile.kind === 'chat' && 'gpu_layers' in profile.inference ? profile.inference : null
}

function formatPercent(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)}%` : '—'
}

function formatBytes(value?: number | null): string {
  if (typeof value !== 'number' || value < 0) return '—'
  return `${(value / 1024 ** 3).toFixed(1)} GiB`
}

function formatMemoryUsage(device: RocmRuntimeInfo['devices'][number]): string {
  const used = formatBytes(device.used_memory_bytes)
  const total = formatBytes(device.total_memory_bytes)
  if (used === '—') return total
  const ratio = device.total_memory_bytes > 0 && typeof device.used_memory_bytes === 'number'
    ? ` (${Math.round(device.used_memory_bytes / device.total_memory_bytes * 100)}%)`
    : ''
  return `${used} / ${total}${ratio}`
}

function formatTemperature(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)} °C` : '—'
}

function formatPower(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)} W` : '—'
}

function formatTokens(value?: number | null): string {
  if (!value) return '—'
  return value >= 1000 ? `${Math.round(value / 1024)}K` : String(value)
}

function errorText(error: unknown): string { return error instanceof Error ? error.message : String(error) }

let runtimePollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await refresh()
  runtimePollTimer = setInterval(refreshRuntimeState, 2000)
})

onBeforeUnmount(() => {
  if (runtimePollTimer) clearInterval(runtimePollTimer)
})
</script>

<style scoped>
.local-model-view {
  container-name: local-model;
  container-type: inline-size;
  height: 100%;
  padding: var(--app-space-xl);
  background: var(--app-surface);
}

.context-bar,
.content-header,
.resource-header,
.resource-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.context-bar { margin-bottom: var(--app-space-xl); }
.context-title { display: flex; flex-direction: column; gap: var(--app-space-xs); min-width: 0; }
.title-line { display: flex; align-items: center; gap: var(--app-space-sm); }
.title-icon,
.resource-icon,
.empty-icon,
.overview-icon {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text);
}
.title-icon { width: 34px; height: 34px; font-size: 19px; }
.page-title { font-size: var(--app-font-xl); }
.context-subtitle { padding-left: 42px; font-size: var(--app-font-sm); }

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) repeat(2, minmax(150px, 1fr));
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-xl);
}

.overview-card {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
  min-width: 0;
  padding: var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-sm);
}
.overview-icon { width: 42px; height: 42px; font-size: 22px; }
.overview-copy { min-width: 0; flex: 1; }
.overview-label,
.spec-item span,
.path-block span,
.checksum-line span { color: var(--app-text-muted); font-size: var(--app-font-sm); }
.overview-value { margin-top: 2px; color: var(--app-text-strong); font-size: var(--app-font-lg); font-weight: 650; }
.overview-detail { margin-top: 2px; overflow: hidden; color: var(--app-text-secondary); font-size: var(--app-font-sm); text-overflow: ellipsis; white-space: nowrap; }
.runtime-device-list { display: grid; gap: var(--app-space-sm); margin-top: var(--app-space-md); }
.runtime-device { padding: var(--app-space-sm); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface-muted); }
.runtime-device-heading { display: flex; align-items: baseline; justify-content: space-between; gap: var(--app-space-md); color: var(--app-text-strong); }
.runtime-device-heading span { color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.runtime-metrics { display: flex; flex-wrap: wrap; gap: var(--app-space-xs) var(--app-space-md); margin-top: var(--app-space-xs); color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.status-dot { width: 9px; height: 9px; flex: 0 0 auto; border-radius: 50%; background: var(--app-warning); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-warning) 14%, transparent); }
.runtime-card.is-ready .status-dot { background: var(--app-success); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-success) 14%, transparent); }
.runtime-card.is-ready .overview-icon { color: var(--app-success); background: color-mix(in srgb, var(--app-success) 10%, var(--app-surface)); }
.runtime-card.is-warning .overview-icon { color: var(--app-warning); background: color-mix(in srgb, var(--app-warning) 10%, var(--app-surface)); }

.model-panel {
  min-height: 420px;
  padding: 0 var(--app-space-lg) var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-sm);
}
.tab-content { padding: var(--app-space-lg) 0 0; }
.content-header { margin-bottom: var(--app-space-lg); flex-wrap: wrap; }
.section-title { display: block; font-size: var(--app-font-lg); }
.section-description { margin-top: var(--app-space-xs); color: var(--app-text-secondary); font-size: var(--app-font-sm); }

.resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-md); }
.resource-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  transition: border-color var(--app-transition-base), box-shadow var(--app-transition-base), transform var(--app-transition-base);
}
.resource-card:hover { transform: translateY(-1px); border-color: var(--app-border-hover); box-shadow: var(--app-shadow-md); }
.resource-identity { display: flex; align-items: center; gap: var(--app-space-sm); min-width: 0; }
.profile-status-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--app-space-xs); }
.resource-icon { width: 38px; height: 38px; font-size: 20px; }
.resource-title-block { min-width: 0; }
.resource-title { overflow: hidden; color: var(--app-text-strong); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.resource-id { margin-top: 2px; overflow: hidden; color: var(--app-text-muted); font-family: 'SF Mono', Monaco, monospace; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.tag-row { display: flex; flex-wrap: wrap; gap: var(--app-space-xs); margin-top: var(--app-space-md); }
.model-name { margin-top: var(--app-space-md); color: var(--app-text); font-family: 'SF Mono', Monaco, monospace; font-size: var(--app-font-sm); font-weight: 600; }
.path-line { display: flex; align-items: center; gap: var(--app-space-xs); min-width: 0; margin-top: var(--app-space-xs); color: var(--app-text-muted); font-size: var(--app-font-sm); }
.path-line span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-runtime-panel {
  display: grid;
  gap: var(--app-space-xs);
  margin-top: var(--app-space-md);
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.profile-runtime-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.profile-runtime-heading strong { color: var(--app-text); font-weight: 600; }
.runtime-error { color: var(--app-error); font-size: var(--app-font-xs); line-height: var(--app-leading-normal); overflow-wrap: anywhere; }
.spec-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-xs); margin-top: var(--app-space-lg); }
.spec-item { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-sm); padding: var(--app-space-sm); border-radius: var(--app-radius-sm); background: var(--app-surface-muted); }
.spec-item strong { color: var(--app-text); font-size: var(--app-font-sm); }
.resource-actions { margin-top: auto; padding-top: var(--app-space-lg); }
.action-spacer { flex: 1; }

.path-block { margin-top: var(--app-space-lg); padding: var(--app-space-md); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface-muted); }
.path-block span { display: block; margin-bottom: var(--app-space-xs); }
.path-block code,
.checksum-line code { display: block; overflow: hidden; color: var(--app-text); font-size: var(--app-font-sm); text-overflow: ellipsis; white-space: nowrap; }
.checksum-line { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); margin-top: var(--app-space-sm); }
.checksum-line code { min-width: 0; }
.storage-root { display: flex; flex-wrap: wrap; gap: var(--app-space-xs); margin-top: var(--app-space-xs); color: var(--app-text-muted); font-size: var(--app-font-sm); }
.storage-root code,
.storage-hint code { color: var(--app-text); }
.storage-hint { margin-bottom: var(--app-space-md); color: var(--app-text-secondary); font-size: var(--app-font-sm); }
.model-directory-summary {
  display: grid;
  gap: var(--app-space-xs);
  margin: calc(var(--app-space-sm) * -1) 0 var(--app-space-md);
  padding: var(--app-space-sm) var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.model-directory-heading { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-xs); }
.model-directory-heading strong { margin-right: var(--app-space-xs); color: var(--app-text-strong); }
.model-directory-heading span {
  padding: 2px var(--app-space-xs);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-size: var(--app-font-xs);
}
.model-directory-summary code {
  overflow: hidden;
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-panel {
  min-height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-sm);
  padding: var(--app-space-xl);
  border: 1px dashed var(--app-border-hover);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
  text-align: center;
  animation: app-fade-in-up 0.3s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.empty-icon { width: 56px; height: 56px; margin-bottom: var(--app-space-xs); color: var(--app-text-muted); font-size: 29px; background: var(--app-surface); box-shadow: var(--app-shadow-sm); }
.empty-panel p { max-width: 460px; margin: 0 0 var(--app-space-sm); color: var(--app-text-muted); font-size: var(--app-font-sm); line-height: var(--app-leading-normal); }

.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 var(--app-space-lg); }
.memory-form-item { grid-column: 1 / -1; }
.memory-limit-control { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: var(--app-space-sm) var(--app-space-md); width: 100%; align-items: center; }
.memory-limit-control p { grid-column: 1 / -1; margin: 0; color: var(--app-text-muted); font-size: var(--app-font-xs); line-height: var(--app-leading-normal); }

@container local-model (max-width: 900px) {
  .overview-grid { grid-template-columns: 1fr 1fr; }
  .runtime-card { grid-column: 1 / -1; }
  .resource-grid { grid-template-columns: 1fr; }
}

@container local-model (max-width: 620px) {
  .local-model-view { padding: var(--app-space-md); }
  .context-subtitle { padding-left: 0; }
  .overview-grid { grid-template-columns: 1fr; }
  .runtime-card { grid-column: auto; }
  .model-panel { padding: 0 var(--app-space-md) var(--app-space-md); }
  .form-grid { grid-template-columns: 1fr; }
  .memory-form-item { grid-column: auto; }
  .memory-limit-control { grid-template-columns: 1fr; }
  .memory-limit-control p { grid-column: auto; }
  .content-header { align-items: flex-start; }
}
</style>
