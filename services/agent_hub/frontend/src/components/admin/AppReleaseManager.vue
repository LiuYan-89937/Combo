<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import MarkdownContent from '@/components/base/MarkdownContent.vue'
import {
  createAppRelease,
  deleteAppRelease,
  deleteAppReleaseAsset,
  fetchAdminAppRelease,
  listAdminAppReleases,
  publishAppRelease,
  updateAppRelease,
  uploadAppReleaseAsset,
} from '@/api/appReleases'
import { ApiError } from '@/api/client'
import type { AppRelease, AppReleaseAsset } from '@/api/types'
import { formatBytes, formatDate } from '@/composables/useFormat'

type Platform = 'macos' | 'windows'
type AssetKind = 'installer' | 'updater'
type UploadTargetKey = 'macos-installer' | 'macos-updater' | 'windows-installer'

interface AssetTarget {
  key: UploadTargetKey
  platform: Platform
  assetKind: AssetKind
  title: string
  extension: string
  signatureRequired: boolean
}

const assetTargets: AssetTarget[] = [
  {
    key: 'macos-installer',
    platform: 'macos',
    assetKind: 'installer',
    title: 'macOS 安装包',
    extension: '.dmg',
    signatureRequired: false,
  },
  {
    key: 'macos-updater',
    platform: 'macos',
    assetKind: 'updater',
    title: 'macOS 自动更新包',
    extension: '.app.tar.gz',
    signatureRequired: true,
  },
  {
    key: 'windows-installer',
    platform: 'windows',
    assetKind: 'installer',
    title: 'Windows 安装与更新包',
    extension: '.exe',
    signatureRequired: true,
  },
]

const architectureOptions: Record<Platform, Array<{ value: string; label: string }>> = {
  macos: [
    { value: 'aarch64', label: 'Apple Silicon' },
  ],
  windows: [
    { value: 'x86_64', label: 'x64' },
    { value: 'arm64', label: 'ARM64' },
  ],
}

interface UploadState {
  active: boolean
  progress: number
  error: string
}

const releases = ref<AppRelease[]>([])
const selected = ref<AppRelease | null>(null)
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const publishing = ref(false)
const submitted = ref(false)
const notice = ref('')
const form = reactive({
  version: '',
  title: '',
  notes: '',
})
const uploadState = reactive<Record<UploadTargetKey, UploadState>>({
  'macos-installer': { active: false, progress: 0, error: '' },
  'macos-updater': { active: false, progress: 0, error: '' },
  'windows-installer': { active: false, progress: 0, error: '' },
})
const updaterSignatures = reactive<Record<UploadTargetKey, string>>({
  'macos-installer': '',
  'macos-updater': '',
  'windows-installer': '',
})
const uploadArchitecture = reactive<Record<Platform, string>>({
  macos: 'aarch64',
  windows: 'x86_64',
})
let pollTimer: number | undefined

const errors = computed(() => ({
  version: form.version.trim() ? '' : '请填写版本号',
  title: form.title.trim() ? '' : '请填写版本标题',
  notes: form.notes.trim() ? '' : '请填写更新日志',
}))
const editable = computed(
  () => !selected.value || ['draft', 'failed', 'published'].includes(selected.value.status),
)
const assetsReady = computed(() => {
  const assets = selected.value?.assets || []
  const installers = assets.filter((asset) => asset.asset_kind === 'installer')
  if (!installers.length || assets.some((asset) => asset.status !== 'uploaded')) return false
  return installers.every((installer) => {
    if (installer.platform === 'windows') return installer.has_updater_signature
    return assets.some(
      (asset) =>
        asset.platform === installer.platform &&
        asset.architecture === installer.architecture &&
        asset.asset_kind === 'updater' &&
        asset.has_updater_signature,
    )
  })
})
const activeJob = computed(() => {
  const job = selected.value?.latest_job
  return job && ['queued', 'running'].includes(job.status) ? job : null
})

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : '操作失败'
}

async function load(selectId?: string) {
  loading.value = true
  loadError.value = ''
  try {
    releases.value = await listAdminAppReleases()
    const targetId = selectId || selected.value?.app_release_id
    if (targetId) {
      const current = releases.value.find((item) => item.app_release_id === targetId)
      if (current) select(current)
    }
  } catch (error) {
    loadError.value = message(error)
  } finally {
    loading.value = false
  }
}

function select(release: AppRelease) {
  selected.value = release
  form.version = release.version
  form.title = release.title
  form.notes = release.notes_markdown
  submitted.value = false
  notice.value = ''
  clearSignatures()
}

function createNew() {
  selected.value = null
  form.version = ''
  form.title = ''
  form.notes = ''
  submitted.value = false
  notice.value = ''
  clearSignatures()
}

async function save(): Promise<AppRelease | null> {
  submitted.value = true
  if (Object.values(errors.value).some(Boolean)) return null
  saving.value = true
  notice.value = ''
  try {
    const release = selected.value
      ? await updateAppRelease(selected.value.app_release_id, {
          title: form.title.trim(),
          notes_markdown: form.notes.trim(),
        })
      : await createAppRelease({
          version: form.version.trim(),
          title: form.title.trim(),
          notes_markdown: form.notes.trim(),
        })
    selected.value = release
    await load(release.app_release_id)
    notice.value = release.status === 'published' ? '更新日志已保存并排队同步到 GitHub。' : '草稿已保存。'
    return selected.value
  } catch (error) {
    notice.value = message(error)
    return null
  } finally {
    saving.value = false
  }
}

async function upload(target: AssetTarget, file: File | undefined) {
  if (!file) return
  if (!file.name.toLowerCase().endsWith(target.extension)) {
    uploadState[target.key].error = `请选择 ${target.extension} 文件`
    return
  }
  const signature = updaterSignatures[target.key].trim()
  if (target.signatureRequired && !signature) {
    uploadState[target.key].error = '请先选择该安装包对应的 .sig 签名文件'
    return
  }
  let release = await save()
  if (!release) return
  uploadState[target.key] = { active: true, progress: 0, error: '' }
  try {
    await uploadAppReleaseAsset(
      release.app_release_id,
      {
        assetKind: target.assetKind,
        platform: target.platform,
        architecture: uploadArchitecture[target.platform],
        file,
        updaterSignature: signature,
      },
      {
        onProgress(progress) {
          uploadState[target.key].progress = progress.total
            ? progress.loaded / progress.total
            : 0
        },
      },
    )
    release = await fetchAdminAppRelease(release.app_release_id)
    updaterSignatures[target.key] = ''
    select(release)
    await load(release.app_release_id)
  } catch (error) {
    uploadState[target.key].error = message(error)
  } finally {
    uploadState[target.key].active = false
  }
}

async function selectSignature(target: AssetTarget, file: File | undefined) {
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.sig')) {
    uploadState[target.key].error = '请选择 .sig 签名文件'
    return
  }
  if (file.size > 20_000) {
    uploadState[target.key].error = '签名文件大小异常'
    return
  }
  try {
    updaterSignatures[target.key] = (await file.text()).trim()
    uploadState[target.key].error = updaterSignatures[target.key] ? '' : '签名文件内容为空'
  } catch (error) {
    updaterSignatures[target.key] = ''
    uploadState[target.key].error = message(error)
  }
}

function handleSignatureSelection(target: AssetTarget, event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  void selectSignature(target, file)
}

function handleAssetSelection(target: AssetTarget, event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  void upload(target, file)
}

function clearSignatures() {
  for (const target of assetTargets) updaterSignatures[target.key] = ''
}

watch(
  () => uploadArchitecture.macos,
  () => {
    updaterSignatures['macos-updater'] = ''
    uploadState['macos-installer'].error = ''
    uploadState['macos-updater'].error = ''
  },
)

watch(
  () => uploadArchitecture.windows,
  () => {
    updaterSignatures['windows-installer'] = ''
    uploadState['windows-installer'].error = ''
  },
)

async function removeAsset(asset: AppReleaseAsset) {
  if (!selected.value) return
  notice.value = ''
  try {
    await deleteAppReleaseAsset(selected.value.app_release_id, asset.asset_id)
    await load(selected.value.app_release_id)
  } catch (error) {
    notice.value = message(error)
  }
}

async function publish() {
  const release = await save()
  if (!release || !assetsReady.value) {
    notice.value ||= '请先上传至少一个完整安装包。'
    return
  }
  publishing.value = true
  notice.value = ''
  try {
    selected.value = await publishAppRelease(release.app_release_id)
    await load(release.app_release_id)
    notice.value = '发布任务已进入后台队列。'
  } catch (error) {
    notice.value = message(error)
  } finally {
    publishing.value = false
  }
}

async function removeRelease() {
  if (!selected.value || !['draft', 'failed'].includes(selected.value.status)) return
  const release = selected.value
  if (!window.confirm(`删除 ${release.tag_name} 草稿及其暂存安装包？`)) return
  notice.value = ''
  try {
    await deleteAppRelease(release.app_release_id)
    createNew()
    await load()
    if (releases.value[0]) select(releases.value[0])
  } catch (error) {
    notice.value = message(error)
  }
}

function assetFor(target: AssetTarget): AppReleaseAsset | undefined {
  return selected.value?.assets.find(
    (asset) =>
      asset.platform === target.platform &&
      asset.asset_kind === target.assetKind &&
      asset.architecture === uploadArchitecture[target.platform],
  )
}

function architectureLabel(platform: Platform, architecture: string): string {
  return (
    architectureOptions[platform].find((option) => option.value === architecture)?.label ||
    architecture
  )
}

function statusLabel(status: string): string {
  return {
    draft: '草稿',
    queued: '等待发布',
    publishing: '发布中',
    published: '已发布',
    failed: '发布失败',
    withdrawn: '已撤回',
    awaiting_upload: '等待上传',
    uploaded: '已上传',
  }[status] || status
}

async function poll() {
  if (!selected.value || !activeJob.value) return
  try {
    const release = await fetchAdminAppRelease(selected.value.app_release_id)
    select(release)
    if (!['queued', 'running'].includes(release.latest_job?.status || '')) {
      await load(release.app_release_id)
    }
  } catch {
    // Preserve the current editor state; the next interval retries.
  }
}

onMounted(async () => {
  await load()
  if (releases.value[0]) select(releases.value[0])
  pollTimer = window.setInterval(poll, 2_000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="manager">
    <aside class="release-nav">
      <div class="release-nav__head">
        <div>
          <span class="eyebrow">Application</span>
          <h2>应用版本</h2>
        </div>
        <button type="button" class="square-action" title="新建版本" @click="createNew">
          <span>＋</span>
        </button>
      </div>
      <p v-if="loading" class="release-nav__empty">正在加载…</p>
      <div v-else-if="loadError" class="release-nav__failure">
        <p>{{ loadError }}</p>
        <button type="button" @click="load()">重新加载</button>
      </div>
      <p v-else-if="!releases.length" class="release-nav__empty">还没有应用版本</p>
      <button
        v-for="release in releases"
        :key="release.app_release_id"
        type="button"
        class="release-item"
        :class="{ 'release-item--active': selected?.app_release_id === release.app_release_id }"
        @click="select(release)"
      >
        <span>
          <strong>{{ release.tag_name }}</strong>
          <small>{{ release.title }}</small>
        </span>
        <i :data-status="release.status">{{ statusLabel(release.status) }}</i>
      </button>
    </aside>

    <section class="editor">
      <header class="editor__head">
        <div>
          <span class="eyebrow">{{ selected ? selected.tag_name : 'New release' }}</span>
          <h2>{{ selected ? '编辑应用版本' : '创建应用版本' }}</h2>
        </div>
        <a
          v-if="selected?.github_url"
          :href="selected.github_url"
          target="_blank"
          rel="noopener noreferrer"
          class="github-link"
        >
          GitHub <BaseIcon name="arrow-up-right" :size="15" />
        </a>
      </header>

      <div class="form-grid">
        <label class="field">
          <span>版本号 <b>*</b></span>
          <input
            v-model="form.version"
            :disabled="Boolean(selected)"
            placeholder="0.2.0"
            :class="{ 'field--error': submitted && errors.version }"
          />
          <small v-if="submitted && errors.version">{{ errors.version }}</small>
        </label>
        <label class="field">
          <span>版本标题 <b>*</b></span>
          <input
            v-model="form.title"
            :disabled="!editable"
            placeholder="FastAgentFactory 0.2.0"
            :class="{ 'field--error': submitted && errors.title }"
          />
          <small v-if="submitted && errors.title">{{ errors.title }}</small>
        </label>
      </div>

      <div class="notes">
        <label class="field notes__editor">
          <span>更新日志 <b>*</b></span>
          <textarea
            v-model="form.notes"
            :disabled="!editable"
            rows="13"
            placeholder="## 新增&#10;&#10;- 支持…"
            :class="{ 'field--error': submitted && errors.notes }"
          />
          <small v-if="submitted && errors.notes">{{ errors.notes }}</small>
        </label>
        <div class="notes__preview">
          <span class="notes__label">预览</span>
          <MarkdownContent v-if="form.notes.trim()" :source="form.notes" />
          <p v-else>更新日志将在这里预览。</p>
        </div>
      </div>

      <section v-if="selected && ['draft', 'failed'].includes(selected.status)" class="assets">
        <header>
          <div>
            <h3>安装包</h3>
            <p>文件直接上传到 OSS 暂存区，不经过 API 服务器。</p>
          </div>
        </header>
        <div class="asset-grid">
          <div v-for="target in assetTargets" :key="target.key" class="asset-slot">
            <label class="asset-slot__architecture">
              <span>{{ target.title }}</span>
              <select
                v-model="uploadArchitecture[target.platform]"
                :disabled="uploadState[target.key].active"
              >
                <option
                  v-for="option in architectureOptions[target.platform]"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label v-if="target.signatureRequired" class="signature-picker">
              <input
                type="file"
                class="visually-hidden"
                accept=".sig"
                :disabled="uploadState[target.key].active"
                @change="handleSignatureSelection(target, $event)"
              />
              <BaseIcon :name="updaterSignatures[target.key] ? 'check' : 'upload'" :size="15" />
              <span>
                {{ updaterSignatures[target.key] ? '签名文件已选择' : '先选择对应的 .sig 签名文件' }}
              </span>
            </label>
            <label class="asset-card">
              <input
                type="file"
                class="visually-hidden"
                :accept="target.extension"
                :disabled="uploadState[target.key].active"
                @change="handleAssetSelection(target, $event)"
              />
              <span class="asset-card__icon">
                <BaseIcon :name="assetFor(target) ? 'check' : 'upload'" :size="21" />
              </span>
              <span class="asset-card__copy">
                <strong>
                  {{ architectureLabel(target.platform, uploadArchitecture[target.platform]) }}
                </strong>
                <small v-if="assetFor(target)">
                  {{ assetFor(target)?.filename }} ·
                  {{ formatBytes(assetFor(target)?.size_bytes || 0) }}
                </small>
                <small v-else>选择 {{ target.extension }} 文件</small>
              </span>
              <span v-if="uploadState[target.key].active" class="asset-card__progress">
                {{ Math.round(uploadState[target.key].progress * 100) }}%
              </span>
              <button
                v-else-if="assetFor(target)"
                type="button"
                class="asset-card__remove"
                title="移除"
                @click.prevent="removeAsset(assetFor(target)!)"
              >
                ×
              </button>
              <small v-if="uploadState[target.key].error" class="asset-card__error">
                {{ uploadState[target.key].error }}
              </small>
            </label>
          </div>
        </div>
        <div v-if="selected.assets.length" class="asset-list">
          <div v-for="asset in selected.assets" :key="asset.asset_id">
            <span>
              <strong>{{ asset.filename }}</strong>
              <small>
                {{ asset.asset_kind === 'updater' ? '自动更新包' : '安装包' }} ·
                {{ asset.platform }} · {{ asset.architecture }} · {{ formatBytes(asset.size_bytes) }}
              </small>
            </span>
            <button type="button" title="移除安装包" @click="removeAsset(asset)">×</button>
          </div>
        </div>
        <p v-if="selected.assets.length && !assetsReady" class="assets__requirement">
          发布前，每个 macOS DMG 必须配套同架构的 .app.tar.gz 与 .sig；Windows EXE
          必须配套自身的 .sig。
        </p>
      </section>

      <section v-if="selected?.assets.length && !['draft', 'failed'].includes(selected.status)" class="published-assets">
        <h3>安装包</h3>
        <div v-for="asset in selected.assets" :key="asset.asset_id" class="published-asset">
          <span>
            <strong>{{ asset.filename }}</strong>
            <small>{{ formatBytes(asset.size_bytes) }} · {{ statusLabel(asset.status) }}</small>
          </span>
          <span v-if="asset.status === 'publishing'" class="mono">
            {{ Math.round((asset.progress_ratio || 0) * 100) }}%
          </span>
        </div>
      </section>

      <section v-if="selected?.latest_job" class="job">
        <div class="job__head">
          <span>
            <strong>{{ statusLabel(selected.latest_job.status) }}</strong>
            <small>{{ selected.latest_job.stage }}</small>
          </span>
          <span class="mono">{{ Math.round(selected.latest_job.progress_ratio * 100) }}%</span>
        </div>
        <div class="job__bar">
          <i :style="{ width: `${selected.latest_job.progress_ratio * 100}%` }" />
        </div>
        <p v-if="selected.latest_job.error">{{ selected.latest_job.error.message }}</p>
      </section>

      <p v-if="selected?.error" class="notice notice--error">{{ selected.error.message }}</p>
      <p v-if="notice" class="notice">{{ notice }}</p>

      <footer class="editor__actions">
        <span v-if="selected" class="editor__updated">
          更新于 {{ formatDate(selected.updated_at, 'zh-CN') }}
        </span>
        <BaseButton
          v-if="selected && ['draft', 'failed'].includes(selected.status)"
          variant="ghost"
          @click="removeRelease"
        >
          删除草稿
        </BaseButton>
        <BaseButton
          variant="secondary"
          :loading="saving"
          :disabled="!editable"
          @click="save"
        >
          {{ selected?.status === 'published' ? '保存日志' : '保存草稿' }}
        </BaseButton>
        <BaseButton
          v-if="selected && ['draft', 'failed'].includes(selected.status)"
          icon="upload"
          :loading="publishing"
          :disabled="!assetsReady"
          @click="publish"
        >
          发布版本
        </BaseButton>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.manager {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  min-height: 680px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.release-nav {
  padding: var(--space-4);
  border-right: 1px solid var(--border);
  background: var(--surface-subtle);
}
.release-nav__head,
.editor__head,
.assets header,
.editor__actions,
.job__head,
.published-asset {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.release-nav__head {
  margin-bottom: var(--space-4);
}
.release-nav h2,
.editor h2,
.assets h3,
.published-assets h3 {
  margin: 2px 0 0;
  color: var(--text-strong);
  line-height: 1.2;
}
.square-action {
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-strong);
  font-size: 21px;
  cursor: pointer;
}
.release-nav__empty {
  padding: var(--space-6) var(--space-2);
  color: var(--text-secondary);
  text-align: center;
}
.release-nav__failure {
  padding: var(--space-5) var(--space-2);
  color: var(--danger);
  font-size: 12px;
  text-align: center;
}
.release-nav__failure button {
  margin-top: var(--space-3);
  border: 0;
  background: none;
  color: var(--text-strong);
  font: inherit;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.release-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  width: 100%;
  margin-bottom: var(--space-2);
  padding: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.release-item:hover,
.release-item--active {
  border-color: var(--border);
  background: var(--surface);
}
.release-item strong,
.release-item small {
  display: block;
}
.release-item small {
  max-width: 145px;
  margin-top: 2px;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.release-item i {
  color: var(--text-secondary);
  font-size: 11px;
  font-style: normal;
}
.release-item i[data-status='published'] {
  color: var(--success);
}
.release-item i[data-status='failed'] {
  color: var(--danger);
}
.editor {
  min-width: 0;
  padding: clamp(var(--space-6), 4vw, var(--space-8));
}
.editor__head {
  margin-bottom: var(--space-8);
}
.github-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
}
.form-grid,
.asset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}
.field {
  display: grid;
  gap: var(--space-2);
}
.field > span,
.notes__label {
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 600;
}
.field b {
  color: var(--danger);
}
.field input,
.field textarea {
  width: 100%;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.field input {
  height: 44px;
  padding-inline: var(--space-3);
}
.field textarea {
  min-height: 290px;
  padding: var(--space-3);
  resize: vertical;
}
.field input:disabled,
.field textarea:disabled {
  background: var(--surface-subtle);
  color: var(--text-secondary);
}
.field .field--error {
  border-color: var(--danger);
}
.field small {
  color: var(--danger);
  font-size: 12px;
}
.notes {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-4);
  margin-top: var(--space-6);
}
.notes__preview {
  min-height: 322px;
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: auto;
}
.notes__preview > p {
  margin-top: var(--space-8);
  color: var(--text-muted);
  text-align: center;
}
.assets,
.published-assets,
.job {
  margin-top: var(--space-6);
  padding-top: var(--space-6);
  border-top: 1px solid var(--border);
}
.assets header p {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 13px;
}
.assets__requirement {
  margin-top: var(--space-3);
  color: var(--danger);
  font-size: 12px;
}
.asset-grid {
  margin-top: var(--space-4);
}
.asset-slot {
  display: grid;
  gap: var(--space-2);
}
.asset-slot__architecture {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  color: var(--text-secondary);
  font-size: 12px;
}
.asset-slot__architecture select {
  min-width: 132px;
  height: 34px;
  padding-inline: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
.signature-picker {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding-inline: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}
.signature-picker:hover {
  border-color: var(--border-strong);
  color: var(--text-strong);
}
.asset-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 88px;
  padding: var(--space-4);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
}
.asset-card:hover {
  border-style: solid;
}
.asset-card__icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
}
.asset-card__copy {
  min-width: 0;
}
.asset-card__copy strong,
.asset-card__copy small {
  display: block;
}
.asset-card__copy small {
  max-width: 250px;
  margin-top: 3px;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-card__progress {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 12px;
}
.asset-card__remove {
  margin-left: auto;
  border: 0;
  background: none;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.asset-card__error {
  position: absolute;
  right: var(--space-3);
  bottom: 3px;
  color: var(--danger);
}
.asset-list {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
.asset-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.asset-list strong,
.asset-list small {
  display: block;
}
.asset-list small {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 12px;
}
.asset-list button {
  border: 0;
  background: none;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.published-asset {
  margin-top: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.published-asset strong,
.published-asset small {
  display: block;
}
.published-asset small {
  color: var(--text-secondary);
}
.job {
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.job__head strong,
.job__head small {
  display: block;
}
.job__head small {
  color: var(--text-secondary);
}
.job__bar {
  height: 5px;
  margin-top: var(--space-3);
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--surface-pressed);
}
.job__bar i {
  display: block;
  height: 100%;
  background: var(--text-strong);
  transition: width var(--dur-base) var(--ease-out);
}
.job p,
.notice {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: 13px;
}
.notice--error {
  color: var(--danger);
}
.editor__actions {
  justify-content: flex-end;
  margin-top: var(--space-8);
}
.editor__updated {
  margin-right: auto;
  color: var(--text-muted);
  font-size: 12px;
}
@media (max-width: 900px) {
  .manager {
    grid-template-columns: 1fr;
  }
  .release-nav {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }
  .notes {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .form-grid,
  .asset-grid {
    grid-template-columns: 1fr;
  }
  .editor__actions {
    align-items: stretch;
    flex-direction: column;
  }
  .editor__updated {
    margin-right: 0;
  }
}
</style>
