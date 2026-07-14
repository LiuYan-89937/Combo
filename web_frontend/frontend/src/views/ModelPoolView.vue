<template>
  <div class="local-model-view">
    <div class="context-bar">
      <div class="context-title">
        <n-text strong>{{ t('localModel.title') }}</n-text>
        <n-text depth="3" class="context-subtitle">{{ t('localModel.subtitle') }}</n-text>
      </div>
      <n-button :loading="loading" @click="refresh">{{ t('common.refresh') }}</n-button>
    </div>

    <n-alert :type="rocm?.available ? 'success' : 'warning'" :title="t('localModel.rocmRuntime')">
      <template v-if="rocm?.available">
        ROCm {{ rocm.hip_version }} · PyTorch {{ rocm.torch_version }} ·
        {{ t('localModel.deviceCount', { count: rocm.device_count }) }}
        <div v-for="device in rocm.devices" :key="device.index">
          GPU {{ device.index }} · {{ device.name }} · {{ formatBytes(device.total_memory_bytes) }}
        </div>
      </template>
      <template v-else>{{ rocm?.error || t('localModel.rocmUnchecked') }}</template>
    </n-alert>

    <n-tabs type="line" animated>
      <n-tab-pane name="profiles" :tab="t('localModel.profiles')">
        <div class="tab-content">
          <div class="content-header">
            <n-text>{{ t('localModel.profileHint') }}</n-text>
            <n-button type="primary" :disabled="!artifacts.length" @click="openProfile()">
              {{ t('localModel.addProfile') }}
            </n-button>
          </div>
          <n-list v-if="profiles.length" bordered>
            <n-list-item v-for="profile in profiles" :key="profile.profile_id">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ profile.display_name }}</n-text>
                    <n-tag size="small">{{ profile.kind }}</n-tag>
                    <n-tag size="small">{{ profile.engine }}</n-tag>
                    <n-tag size="small" :type="profile.enabled ? 'success' : 'default'">
                      {{ profile.enabled ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div>{{ profile.served_model_name }} · {{ profile.artifact?.local_path }}</div>
                  <div>
                    {{ profile.inference.dtype }} · TP {{ profile.inference.tensor_parallel_size }}
                    <span v-if="profile.inference.quantization"> · {{ profile.inference.quantization }}</span>
                  </div>
                </template>
                <template #action>
                  <n-space>
                    <n-button size="small" :loading="checkingProfileId === profile.profile_id" @click="checkProfile(profile)">
                      {{ t('localModel.checkLoad') }}
                    </n-button>
                    <n-button size="small" @click="openProfile(profile)">{{ t('common.edit') }}</n-button>
                    <n-button size="small" type="error" tertiary @click="removeProfile(profile)">{{ t('common.delete') }}</n-button>
                  </n-space>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>
          <n-empty v-else :description="t('localModel.noProfiles')" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="artifacts" :tab="t('localModel.artifacts')">
        <div class="tab-content">
          <div class="content-header">
            <n-text>{{ t('localModel.artifactHint') }}</n-text>
            <n-button type="primary" @click="openArtifact()">{{ t('localModel.addArtifact') }}</n-button>
          </div>
          <n-list v-if="artifacts.length" bordered>
            <n-list-item v-for="artifact in artifacts" :key="artifact.artifact_id">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ artifact.display_name }}</n-text>
                    <n-tag size="small">{{ artifact.kind }}</n-tag>
                    <n-tag size="small" :type="artifact.enabled ? 'success' : 'default'">
                      {{ artifact.enabled ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div>{{ artifact.local_path }}</div>
                  <div v-if="artifact.revision || artifact.checksum">
                    {{ artifact.revision }} <span v-if="artifact.checksum">· {{ artifact.checksum }}</span>
                  </div>
                </template>
                <template #action>
                  <n-space>
                    <n-button size="small" @click="openArtifact(artifact)">{{ t('common.edit') }}</n-button>
                    <n-button size="small" type="error" tertiary @click="removeArtifact(artifact)">{{ t('common.delete') }}</n-button>
                  </n-space>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>
          <n-empty v-else :description="t('localModel.noArtifacts')" />
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="artifactModalOpen" preset="dialog" :title="t('localModel.artifactEditor')">
      <n-form label-placement="top">
        <n-form-item :label="t('localModel.displayName')"><n-input v-model:value="artifactForm.display_name" /></n-form-item>
        <n-form-item :label="t('localModel.kind')"><n-select v-model:value="artifactForm.kind" :options="kindOptions" /></n-form-item>
        <n-form-item :label="t('localModel.localPath')"><n-input v-model:value="artifactForm.local_path" /></n-form-item>
        <n-form-item :label="t('localModel.tokenizerPath')"><n-input v-model:value="artifactForm.tokenizer_path" clearable /></n-form-item>
        <n-form-item :label="t('localModel.revision')"><n-input v-model:value="artifactForm.revision" clearable /></n-form-item>
        <n-form-item :label="t('localModel.checksum')"><n-input v-model:value="artifactForm.checksum" clearable /></n-form-item>
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
          <n-form-item :label="t('localModel.dtype')"><n-input v-model:value="profileForm.dtype" /></n-form-item>
          <n-form-item :label="t('localModel.quantization')"><n-input v-model:value="profileForm.quantization" clearable /></n-form-item>
          <n-form-item :label="t('localModel.tensorParallel')">
            <n-input-number v-model:value="profileForm.tensor_parallel_size" :min="1" />
          </n-form-item>
          <n-form-item :label="t('localModel.gpuMemoryUtilization')">
            <n-input-number v-model:value="profileForm.gpu_memory_utilization" :min="0.01" :max="1" :step="0.05" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxInput')">
            <n-input-number v-model:value="profileForm.max_input_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxOutput')">
            <n-input-number v-model:value="profileForm.max_output_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'embedding'" :label="t('localModel.embeddingDimensions')">
            <n-input-number v-model:value="profileForm.embedding_dimensions" :min="1" />
          </n-form-item>
        </div>
        <n-space vertical>
          <n-checkbox v-model:checked="profileForm.enabled">{{ t('common.enabled') }}</n-checkbox>
          <n-checkbox v-model:checked="profileForm.trust_remote_code">{{ t('localModel.trustRemoteCode') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.tool_calling">{{ t('modelPool.toolCalling') }}</n-checkbox>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  modelPoolApi,
  type LocalModelArtifact,
  type LocalModelKind,
  type LocalModelProfile,
  type RocmRuntimeInfo,
} from '@/api/modelPool'

const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const checkingProfileId = ref('')
const artifacts = ref<LocalModelArtifact[]>([])
const profiles = ref<LocalModelProfile[]>([])
const rocm = ref<RocmRuntimeInfo | null>(null)
const artifactModalOpen = ref(false)
const profileModalOpen = ref(false)
const artifactEditing = ref<LocalModelArtifact | null>(null)
const profileEditing = ref<LocalModelProfile | null>(null)

const artifactForm = reactive({
  display_name: '', kind: 'chat' as LocalModelKind, local_path: '', tokenizer_path: '',
  revision: '', checksum: '', enabled: true,
})
const profileForm = reactive({
  display_name: '', artifact_id: '', kind: 'chat' as LocalModelKind,
  served_model_name: '', dtype: '', quantization: '', tensor_parallel_size: 1,
  gpu_memory_utilization: null as number | null, max_input_tokens: null as number | null,
  max_output_tokens: null as number | null, embedding_dimensions: null as number | null,
  trust_remote_code: false, tool_calling: true, reasoning_supported: false,
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

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [artifactData, profileData, runtimeData] = await Promise.all([
      modelPoolApi.artifacts(), modelPoolApi.profiles(), modelPoolApi.rocmRuntime(),
    ])
    artifacts.value = artifactData.artifacts
    profiles.value = profileData.profiles
    rocm.value = runtimeData
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
  artifactForm.tokenizer_path = item?.tokenizer_path || ''
  artifactForm.revision = item?.revision || ''
  artifactForm.checksum = item?.checksum || ''
  artifactForm.enabled = item?.enabled ?? true
  artifactModalOpen.value = true
}

async function saveArtifact(): Promise<void> {
  saving.value = true
  try {
    const payload = { ...artifactForm, artifact_id: artifactEditing.value?.artifact_id }
    if (artifactEditing.value) await modelPoolApi.patchArtifact(artifactEditing.value.artifact_id, payload)
    else await modelPoolApi.saveArtifact(payload)
    artifactModalOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) } finally { saving.value = false }
}

function openProfile(item?: LocalModelProfile): void {
  const artifact = item?.artifact || artifacts.value[0]
  profileEditing.value = item || null
  profileForm.display_name = item?.display_name || ''
  profileForm.artifact_id = item?.artifact_id || artifact?.artifact_id || ''
  profileForm.kind = item?.kind || artifact?.kind || 'chat'
  profileForm.served_model_name = item?.served_model_name || ''
  profileForm.dtype = item?.inference.dtype || ''
  profileForm.quantization = item?.inference.quantization || ''
  profileForm.tensor_parallel_size = item?.inference.tensor_parallel_size || 1
  profileForm.gpu_memory_utilization = item?.inference.gpu_memory_utilization ?? null
  profileForm.max_input_tokens = item?.limits.max_input_tokens ?? null
  profileForm.max_output_tokens = item?.limits.max_output_tokens ?? null
  profileForm.embedding_dimensions = item?.embedding_dimensions ?? null
  profileForm.trust_remote_code = item?.inference.trust_remote_code ?? false
  profileForm.tool_calling = item?.capabilities.tool_calling ?? true
  profileForm.reasoning_supported = item?.capabilities.reasoning_supported ?? false
  profileForm.normalize_embeddings = item?.normalize_embeddings ?? true
  profileForm.enabled = item?.enabled ?? true
  profileModalOpen.value = true
}

function syncProfileKind(artifactId: string): void {
  const artifact = artifacts.value.find((item) => item.artifact_id === artifactId)
  if (artifact) profileForm.kind = artifact.kind
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
      engine: isChat ? 'vllm_rocm' : 'transformers_rocm',
      served_model_name: profileForm.served_model_name,
      enabled: profileForm.enabled,
      capabilities: {
        input_modalities: ['text'], output_modalities: ['text'],
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
      },
      inference: {
        dtype: profileForm.dtype,
        quantization: profileForm.quantization || null,
        tensor_parallel_size: profileForm.tensor_parallel_size,
        gpu_memory_utilization: profileForm.gpu_memory_utilization,
        trust_remote_code: profileForm.trust_remote_code,
      },
      embedding_dimensions: isChat ? null : profileForm.embedding_dimensions,
      normalize_embeddings: profileForm.normalize_embeddings,
      notes: '',
    }
    if (profileEditing.value) await modelPoolApi.patchProfile(profileEditing.value.profile_id, payload)
    else await modelPoolApi.saveProfile(payload)
    profileModalOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) } finally { saving.value = false }
}

async function checkProfile(profile: LocalModelProfile): Promise<void> {
  checkingProfileId.value = profile.profile_id
  try {
    const result = await modelPoolApi.checkProfile(profile.profile_id)
    message.success(`${t('localModel.checkComplete')} · ${String(result.status || '')}`)
  } catch (error) { message.error(errorText(error)) } finally { checkingProfileId.value = '' }
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

function formatBytes(value: number): string {
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GiB`
}

function errorText(error: unknown): string { return error instanceof Error ? error.message : String(error) }

onMounted(refresh)
</script>

<style scoped>
.local-model-view { display: flex; flex-direction: column; gap: 16px; }
.context-bar, .content-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.context-title { display: flex; flex-direction: column; gap: 4px; }
.context-subtitle { font-size: 13px; }
.tab-content { display: flex; flex-direction: column; gap: 16px; padding-top: 8px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
@media (max-width: 720px) { .form-grid { grid-template-columns: 1fr; } }
</style>
