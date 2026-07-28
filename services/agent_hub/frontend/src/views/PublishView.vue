<script setup lang="ts">
/*
 * Publish center. Gated behind GitHub login (cookie session). Once signed in,
 * a drag-drop dropzone validates the file client-side (type/size), then hands
 * it to the upload flow state machine. A submissions list shows prior uploads
 * with expandable validation detail. Copy stresses that "uploaded" != "published".
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import StateBlock from '@/components/base/StateBlock.vue'
import StatusBadge from '@/components/hub/StatusBadge.vue'
import { useI18n } from '@/i18n'
import { useSeo } from '@/composables/useSeo'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'
import { useUploadFlow } from '@/composables/useUploadFlow'
import { formatBytes, formatDate } from '@/composables/useFormat'
import { listUploads } from '@/api/uploads'
import type { HubUpload } from '@/api/types'

const { t, locale } = useI18n()
const auth = useAuthStore()
const { isAuthenticated, resolved, loading } = storeToRefs(auth)
const { config } = storeToRefs(useConfigStore())

const flow = useUploadFlow()
const maxLabel = computed(() => formatBytes(config.value.maxPackageBytes))

const dragging = ref(false)
const fileError = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const submissions = ref<HubUpload[]>([])
const submissionsState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const expanded = ref<Set<string>>(new Set())

function pickFile() {
  fileInput.value?.click()
}

function validate(file: File): string {
  if (!file.name.toLowerCase().endsWith('.zip')) return t('publish.invalidType')
  if (file.size === 0) return t('publish.emptyFile')
  if (file.size > config.value.maxPackageBytes) return t('publish.tooLarge', { max: maxLabel.value })
  return ''
}

async function handleFile(file: File | undefined | null) {
  if (!file) return
  fileError.value = validate(file)
  if (fileError.value) return
  await flow.start(file)
  if (flow.upload.value) void loadSubmissions()
}

function onDrop(event: DragEvent) {
  dragging.value = false
  handleFile(event.dataTransfer?.files?.[0])
}

function onInput(event: Event) {
  const target = event.target as HTMLInputElement
  handleFile(target.files?.[0])
  target.value = ''
}

function toggle(id: string) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

async function loadSubmissions() {
  submissionsState.value = submissions.value.length ? submissionsState.value : 'loading'
  try {
    submissions.value = await listUploads(50)
    submissionsState.value = 'ready'
  } catch {
    submissionsState.value = 'error'
  }
}

useSeo(() => ({
  title: t('publish.title'),
  description: t('publish.subtitle'),
  path: '/publish',
  noindex: true,
}))

onMounted(async () => {
  await auth.ensure()
  if (isAuthenticated.value) void loadSubmissions()
})
</script>

<template>
  <div class="publish">
    <section class="publish__head">
      <div class="container">
        <h1 class="publish__title">{{ t('publish.title') }}</h1>
        <p class="publish__subtitle">{{ t('publish.subtitle') }}</p>
      </div>
    </section>

    <div class="container publish__body">
      <!-- Auth resolving -->
      <StateBlock v-if="!resolved && loading" kind="loading" :title="t('common.loading')" />

      <!-- Login gate -->
      <div v-else-if="!isAuthenticated" class="gate">
        <span class="gate__icon"><BaseIcon name="github" :size="28" /></span>
        <h2 class="gate__title">{{ t('publish.loginTitle') }}</h2>
        <p class="gate__body">{{ t('publish.loginBody') }}</p>
        <BaseButton icon="github" size="lg" @click="auth.login('/publish')">
          {{ t('publish.loginButton') }}
        </BaseButton>
      </div>

      <template v-else>
        <!-- UPLOAD -->
        <section class="uploader">
          <div class="uploader__head">
            <h2 class="uploader__title">{{ t('publish.uploadTitle') }}</h2>
            <p class="uploader__note">{{ t('publish.uploadNote') }}</p>
          </div>

          <!-- Dropzone (idle / error) -->
          <div
            v-if="flow.phase.value === 'idle' || flow.phase.value === 'error'"
            class="dropzone"
            :class="{ 'dropzone--drag': dragging, 'dropzone--error': !!fileError }"
            role="button"
            tabindex="0"
            :aria-label="t('publish.uploadHint')"
            @click="pickFile"
            @keydown.enter.prevent="pickFile"
            @keydown.space.prevent="pickFile"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop.prevent="onDrop"
          >
            <span class="dropzone__icon"><BaseIcon name="file-zip" :size="30" /></span>
            <p class="dropzone__hint">{{ t('publish.uploadHint') }}</p>
            <p class="dropzone__constraint">{{ t('publish.uploadConstraint', { max: maxLabel }) }}</p>
            <input
              ref="fileInput"
              type="file"
              accept=".zip,application/zip"
              class="visually-hidden"
              @change="onInput"
            />
          </div>

          <!-- Active flow -->
          <div v-else class="flow" aria-live="polite">
            <div class="flow__row">
              <span class="flow__file">
                <BaseIcon name="file-zip" :size="18" />
                <span class="clamp-1">{{ flow.upload.value?.filename }}</span>
              </span>
              <StatusBadge v-if="flow.upload.value" :status="flow.upload.value.status" />
            </div>

            <div v-if="flow.phase.value === 'uploading'" class="flow__progress">
              <div class="bar"><span class="bar__fill" :style="{ width: `${Math.round(flow.progress.value * 100)}%` }" /></div>
              <span class="flow__pct mono">{{ Math.round(flow.progress.value * 100) }}%</span>
            </div>

            <p v-if="flow.phase.value === 'creating' || flow.phase.value === 'uploading'" class="flow__status">
              <BaseIcon name="spinner" :size="15" /> {{ t('publish.uploading') }}
            </p>
            <p v-else-if="flow.phase.value === 'finalizing'" class="flow__status">
              <BaseIcon name="spinner" :size="15" /> {{ t('publish.finalizing') }}
            </p>
            <p v-else-if="flow.phase.value === 'tracking'" class="flow__status">
              <BaseIcon name="spinner" :size="15" /> {{ t(`status.${flow.upload.value?.status}`) }}
            </p>

            <div v-if="flow.phase.value === 'done'" class="flow__done">
              <p v-if="flow.upload.value?.status === 'published'" class="flow__msg flow__msg--ok">
                <BaseIcon name="check" :size="16" /> {{ t('status.published') }}
              </p>
              <p v-else class="flow__msg">{{ t('publish.uploadSuccess') }}</p>
              <p
                v-if="flow.upload.value?.error"
                class="flow__err"
              >
                {{ t('publish.reason') }}: {{ flow.upload.value.error.message }}
              </p>
            </div>

            <div v-if="flow.phase.value === 'error'" class="flow__error">
              <p>{{ flow.errorMessage.value || t('common.serverError') }}</p>
              <p v-if="flow.errorRequestId.value" class="mono flow__rid">
                {{ t('common.requestId') }}: {{ flow.errorRequestId.value }}
              </p>
            </div>

            <div class="flow__actions">
              <BaseButton
                v-if="flow.isActive.value"
                variant="ghost"
                size="sm"
                @click="flow.cancel()"
              >
                {{ t('common.cancel') }}
              </BaseButton>
              <BaseButton
                v-else
                variant="secondary"
                size="sm"
                icon="upload"
                @click="flow.reset()"
              >
                {{ t('publish.uploadTitle') }}
              </BaseButton>
            </div>
          </div>

          <p v-if="fileError" class="uploader__file-error" role="alert">{{ fileError }}</p>
        </section>

        <!-- SUBMISSIONS -->
        <section class="submissions">
          <div class="submissions__head">
            <h2 class="uploader__title">{{ t('publish.mySubmissions') }}</h2>
            <BaseButton variant="ghost" size="sm" icon="arrow-right" @click="loadSubmissions">
              {{ t('common.retry') }}
            </BaseButton>
          </div>

          <StateBlock
            v-if="submissionsState === 'error'"
            kind="error"
            :title="t('common.error')"
            :body="t('common.serverError')"
            retryable
            @retry="loadSubmissions"
          />
          <StateBlock
            v-else-if="submissionsState === 'ready' && submissions.length === 0"
            kind="empty"
            icon="upload"
            :body="t('publish.noSubmissions')"
          />
          <ul v-else-if="submissions.length" class="sub-list">
            <li v-for="sub in submissions" :key="sub.upload_id" class="sub">
              <div class="sub__row">
                <span class="sub__file">
                  <BaseIcon name="file-zip" :size="17" />
                  <span class="clamp-1">{{ sub.filename }}</span>
                </span>
                <StatusBadge :status="sub.status" />
                <span class="sub__date">{{ formatDate(sub.created_at, locale) }}</span>
                <button
                  v-if="sub.validation || sub.error"
                  type="button"
                  class="sub__toggle"
                  :aria-expanded="expanded.has(sub.upload_id)"
                  @click="toggle(sub.upload_id)"
                >
                  {{ expanded.has(sub.upload_id) ? t('publish.collapse') : t('publish.expand') }}
                  <BaseIcon :name="expanded.has(sub.upload_id) ? 'chevron-down' : 'chevron-right'" :size="14" />
                </button>
              </div>

              <div v-if="expanded.has(sub.upload_id)" class="sub__detail">
                <p v-if="sub.error" class="sub__error">
                  <BaseIcon name="alert" :size="14" /> {{ sub.error.message }}
                </p>
                <template v-if="sub.validation">
                  <p class="sub__detail-line">
                    {{ t('publish.detailDeps') }}:
                    <span class="mono">py {{ sub.validation.dependencies.python_count }} · npm {{ sub.validation.dependencies.npm_count }} · sys {{ sub.validation.dependencies.system_count }}</span>
                  </p>
                  <p class="sub__detail-line">
                    {{ t('publish.detailTools') }}:
                    <span class="mono">{{ sub.validation.tools.package_tools.length }} · MCP {{ sub.validation.tools.mcp_servers.length }}</span>
                  </p>
                  <ul v-if="sub.validation.warnings.length" class="sub__warnings">
                    <li v-for="(w, i) in sub.validation.warnings" :key="i">{{ w.message }}</li>
                  </ul>
                </template>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.publish__head {
  padding-block: var(--space-18) var(--space-8);
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.publish__title {
  font-size: clamp(30px, 5vw, 46px);
  letter-spacing: -0.03em;
  font-weight: 680;
  color: var(--text-strong);
}
.publish__subtitle {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: 17px;
  max-width: 600px;
}
.publish__body {
  padding-block: var(--space-12) var(--space-24);
  max-width: 860px;
}

/* LOGIN GATE */
.gate {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-4);
  padding: var(--space-24) var(--space-6);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: var(--surface);
}
.gate__icon {
  display: inline-grid;
  place-items: center;
  width: 60px;
  height: 60px;
  border-radius: var(--radius-lg);
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  color: var(--text-strong);
}
.gate__title {
  font-size: 22px;
  font-weight: 640;
  color: var(--text-strong);
}
.gate__body {
  max-width: 42ch;
  color: var(--text-secondary);
  margin-bottom: var(--space-2);
}

/* UPLOADER */
.uploader {
  margin-bottom: var(--space-18);
}
.uploader__head {
  margin-bottom: var(--space-6);
}
.uploader__title {
  font-size: 21px;
  font-weight: 640;
  color: var(--text-strong);
}
.uploader__note {
  margin-top: var(--space-2);
  color: var(--text-muted);
  font-size: 14px;
}
.uploader__file-error {
  margin-top: var(--space-3);
  color: var(--danger);
  font-size: 14px;
}

/* DROPZONE */
.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-18) var(--space-6);
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius-xl);
  background: var(--surface-subtle);
  cursor: pointer;
  text-align: center;
  transition: border-color var(--dur-base) var(--ease-out), background var(--dur-base) var(--ease-out);
}
.dropzone:hover,
.dropzone--drag {
  border-color: var(--text-strong);
  background: var(--surface-pressed);
}
.dropzone--error {
  border-color: var(--danger);
}
.dropzone__icon {
  display: inline-grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-strong);
  margin-bottom: var(--space-2);
}
.dropzone__hint {
  font-size: 16px;
  font-weight: 550;
  color: var(--text);
}
.dropzone__constraint {
  color: var(--text-muted);
  font-size: 13px;
}

/* ACTIVE FLOW */
.flow {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.flow__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.flow__file {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  font-weight: 550;
  color: var(--text-strong);
}
.flow__progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.bar {
  flex: 1;
  height: 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-pressed);
  overflow: hidden;
}
.bar__fill {
  display: block;
  height: 100%;
  background: var(--primary);
  border-radius: var(--radius-pill);
  transition: width var(--dur-base) var(--ease-out);
}
.flow__pct {
  font-size: 13px;
  color: var(--text-secondary);
  min-width: 42px;
  text-align: right;
}
.flow__status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-secondary);
  font-size: 14px;
}
.flow__msg {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text);
  font-size: 15px;
}
.flow__msg--ok {
  color: var(--success);
  font-weight: 550;
}
.flow__err,
.flow__rid {
  font-size: 13px;
  color: var(--text-muted);
}
.flow__error {
  padding: var(--space-3) var(--space-4);
  background: var(--danger-surface);
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: 14px;
}
.flow__actions {
  display: flex;
  justify-content: flex-end;
}

/* SUBMISSIONS */
.submissions__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-6);
}
.sub-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.sub {
  padding: var(--space-4) var(--space-6);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.sub__row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.sub__file {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex: 1;
  color: var(--text);
  font-weight: 500;
}
.sub__date {
  color: var(--text-muted);
  font-size: 13px;
  white-space: nowrap;
}
.sub__toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.sub__toggle:hover {
  color: var(--text-strong);
}
.sub__detail {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.sub__detail-line {
  font-size: 14px;
  color: var(--text-secondary);
}
.sub__error {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--danger);
  font-size: 14px;
}
.sub__warnings {
  margin-top: var(--space-2);
  padding-left: var(--space-4);
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 640px) {
  .sub__row {
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .sub__date {
    order: 3;
  }
}
</style>


