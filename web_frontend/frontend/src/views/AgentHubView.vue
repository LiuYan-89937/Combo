<template>
  <div class="hub-view">
    <n-tabs v-model:value="activeTab" type="line" animated class="hub-tabs">
      <template #suffix>
        <div class="identity">
          <template v-if="auth.authenticated && auth.user">
            <n-avatar :src="auth.user.avatar_url" round size="small">
              {{ auth.user.github_login.slice(0, 1).toUpperCase() }}
            </n-avatar>
            <span>{{ auth.user.github_login }}</span>
            <n-button quaternary size="small" @click="logout">{{ t('agentHub.logout') }}</n-button>
          </template>
          <n-button v-else type="primary" size="small" @click="startLogin">
            {{ t('agentHub.login') }}
          </n-button>
        </div>
      </template>

      <n-tab-pane name="explore" :tab="t('agentHub.explore')">
        <div class="toolbar">
          <n-input
            v-model:value="query"
            clearable
            :placeholder="t('agentHub.searchPlaceholder')"
            @keyup.enter="loadPackages"
          >
            <template #prefix><n-icon><Search /></n-icon></template>
          </n-input>
          <n-button :loading="loadingPackages" @click="loadPackages">
            <template #icon><n-icon><Refresh /></n-icon></template>
            {{ t('common.refresh') }}
          </n-button>
        </div>

        <n-alert v-if="errorMessage" type="error" closable class="page-alert" @close="errorMessage = ''">
          {{ errorMessage }}
        </n-alert>

        <n-empty
          v-if="!loadingPackages && releases.length === 0"
          :description="t('agentHub.noPackages')"
          class="hub-empty"
        />
        <div v-else class="release-grid">
          <n-card v-for="release in releases" :key="release.release_id" hoverable>
            <div class="release-heading">
              <n-avatar :style="{ background: packageColor(release.package_id) }">
                {{ release.name.slice(0, 1).toUpperCase() }}
              </n-avatar>
              <div class="release-title">
                <strong>{{ release.name }}</strong>
                <span>{{ release.publisher }}/{{ release.package_id }}</span>
              </div>
              <n-tag size="small">v{{ release.version }}</n-tag>
            </div>
            <p class="description">{{ release.description || t('common.noDescription') }}</p>
            <div class="metrics">
              <span>{{ formatSize(release.size_bytes) }}</span>
              <span>{{ release.download_count }} {{ t('common.download') }}</span>
            </div>
            <div class="capabilities">
              <n-tag size="small" :bordered="false">
                Python {{ release.validation?.dependencies?.python_count || 0 }}
              </n-tag>
              <n-tag size="small" :bordered="false">
                Tools {{ release.validation?.tools?.package_tools?.length || 0 }}
              </n-tag>
              <n-tag size="small" :bordered="false">
                MCP {{ release.validation?.tools?.mcp_servers?.length || 0 }}
              </n-tag>
            </div>
            <template #footer>
              <div class="card-actions">
                <n-button
                  type="primary"
                  :loading="installingReleaseId === release.release_id"
                  @click="install(release)"
                >
                  {{ isInstalled(release.package_id) ? t('agentHub.update') : t('agentHub.install') }}
                </n-button>
              </div>
            </template>
          </n-card>
        </div>
      </n-tab-pane>

      <n-tab-pane name="publish" :tab="t('agentHub.publish')">
        <div class="publish-workspace">
          <section class="publish-intro">
            <div class="publish-intro-copy">
              <div class="publish-mark">
                <n-icon size="24"><CloudUploadOutline /></n-icon>
              </div>
              <div>
                <h2>{{ t('agentHub.publishTitle') }}</h2>
                <p>{{ t('agentHub.publishDescription') }}</p>
              </div>
            </div>
            <div class="review-flow">
              <span>{{ t('agentHub.flowUpload') }}</span>
              <i />
              <span>{{ t('agentHub.flowValidate') }}</span>
              <i />
              <span>{{ t('agentHub.flowReview') }}</span>
              <i />
              <span>{{ t('agentHub.flowPublished') }}</span>
            </div>
          </section>

          <n-alert v-if="!auth.authenticated" type="info" class="login-panel">
            {{ t('agentHub.loginHint') }}
            <template #action>
              <n-button size="small" type="primary" @click="startLogin">
                {{ t('agentHub.login') }}
              </n-button>
            </template>
          </n-alert>

          <template v-else>
            <section class="publish-panel">
              <div class="section-heading">
                <div>
                  <h3>{{ t('agentHub.publishLocal') }}</h3>
                  <p>{{ t('agentHub.publishLocalHint') }}</p>
                </div>
              </div>
              <div v-if="publishablePackages.length" class="local-package-grid">
                <article v-for="pkg in publishablePackages" :key="pkg.package_id" class="local-package-card">
                  <div class="package-card-heading">
                    <n-avatar :style="{ background: packageColor(pkg.package_id) }" round>
                      {{ (pkg.agent_name || pkg.name || pkg.package_id).slice(0, 1).toUpperCase() }}
                    </n-avatar>
                    <div class="package-card-title">
                      <strong>{{ pkg.agent_name || pkg.name || pkg.package_id }}</strong>
                      <span>{{ pkg.package_id }}</span>
                    </div>
                  </div>
                  <p>{{ pkg.agent_description || t('common.noDescription') }}</p>
                  <div class="package-card-footer">
                    <span>
                      <n-icon><ConstructOutline /></n-icon>
                      {{ pkg.tool_count || 0 }} {{ t('agentHub.tools') }}
                    </span>
                    <n-button
                      type="primary"
                      size="small"
                      :loading="publishingPackageId === pkg.package_id"
                      @click="publish(pkg.package_id)"
                    >
                      <template #icon><n-icon><ArrowUpOutline /></n-icon></template>
                      {{ t('agentHub.publishAction') }}
                    </n-button>
                  </div>
                </article>
              </div>
              <n-empty
                v-else
                :description="t('agentHub.noPublishablePackages')"
                class="panel-empty"
              />
            </section>

            <section class="publish-panel">
              <div class="section-heading">
                <div>
                  <h3>{{ t('agentHub.uploads') }}</h3>
                  <p>{{ t('agentHub.uploadsHint') }}</p>
                </div>
                <n-button quaternary circle size="small" :loading="loadingUploads" @click="loadUploads">
                  <template #icon><n-icon><Refresh /></n-icon></template>
                </n-button>
              </div>
              <n-empty
                v-if="!loadingUploads && uploads.length === 0"
                :description="t('agentHub.noUploads')"
                class="panel-empty"
              />
              <div v-else class="upload-list">
                <article v-for="upload in uploads" :key="upload.upload_id" class="upload-row">
                  <div class="upload-file-icon">
                    <n-icon size="20"><CubeOutline /></n-icon>
                  </div>
                  <div class="upload-copy">
                    <strong>{{ upload.filename }}</strong>
                    <span>{{ formatDate(upload.updated_at) }}</span>
                    <span v-if="upload.error" class="upload-error">{{ upload.error.message }}</span>
                  </div>
                  <n-tag :type="uploadStatusType(upload.status)" size="small" round>
                    {{ uploadStatusLabel(upload.status) }}
                  </n-tag>
                </article>
              </div>
            </section>
          </template>
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="browserLoginOpen" :mask-closable="false">
      <n-card class="browser-login-card" :title="t('agentHub.browserLoginTitle')" closable @close="cancelBrowserLogin">
        <p>{{ t('agentHub.browserLoginHint') }}</p>
        <n-button type="primary" block @click="openGithub">
          {{ t('agentHub.reopenGithub') }}
        </n-button>
        <div class="pending-row">
          <n-spin size="small" />
          <span>{{ t('agentHub.authorizationPending') }}</span>
        </div>
        <p v-if="loginError" class="login-error">{{ loginError }}</p>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  NAlert,
  NAvatar,
  NButton,
  NCard,
  NEmpty,
  NIcon,
  NInput,
  NModal,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  useDialog,
  useMessage,
} from 'naive-ui'
import { open } from '@tauri-apps/plugin-shell'
import {
  ArrowUpOutline,
  CloudUploadOutline,
  ConstructOutline,
  CubeOutline,
  Refresh,
  Search,
} from '@/components/icons'
import {
  agentHubApi,
  type AgentHubAuthStatus,
  type AgentHubBrowserAuthorization,
  type AgentHubRelease,
  type AgentHubUpload,
} from '@/api/agentHub'
import { ApiError } from '@/api/http'
import { useI18n } from '@/composables/useI18n'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore } from '@/stores/agent'
import { hashStringToColor } from '@/utils/color'

const { locale, t } = useI18n()
const agentStore = useAgentStore()
const commands = useCommand()
const dialog = useDialog()
const message = useMessage()

const activeTab = ref('explore')
const query = ref('')
const releases = ref<AgentHubRelease[]>([])
const uploads = ref<AgentHubUpload[]>([])
const auth = reactive<AgentHubAuthStatus>({ authenticated: false, user: null, hub_url: '' })
const loadingPackages = ref(false)
const loadingUploads = ref(false)
const installingReleaseId = ref<string | null>(null)
const publishingPackageId = ref<string | null>(null)
const errorMessage = ref('')
const browserLoginOpen = ref(false)
const browserAuthorization = ref<AgentHubBrowserAuthorization | null>(null)
const loginError = ref('')
let pollTimer: number | null = null
let browserLoginExpiresAt = 0

const publishablePackages = computed(() =>
  agentStore.agentPackages.filter(pkg => !pkg.is_builtin && pkg.capabilities?.exportable !== false),
)

onMounted(async () => {
  commands.listAgentPackages()
  await Promise.all([loadAuth(), loadPackages()])
})

onBeforeUnmount(() => {
  void cancelBrowserLogin()
})

watch(activeTab, value => {
  if (value === 'publish' && auth.authenticated) void loadUploads()
})

async function loadAuth() {
  try {
    Object.assign(auth, await agentHubApi.auth())
  } catch (error) {
    showError(error)
  }
}

async function loadPackages() {
  loadingPackages.value = true
  errorMessage.value = ''
  try {
    releases.value = (await agentHubApi.packages(query.value)).items
  } catch (error) {
    showError(error)
  } finally {
    loadingPackages.value = false
  }
}

async function loadUploads() {
  if (!auth.authenticated) return
  loadingUploads.value = true
  try {
    uploads.value = await agentHubApi.uploads()
  } catch (error) {
    showError(error)
  } finally {
    loadingUploads.value = false
  }
}

async function startLogin() {
  try {
    loginError.value = ''
    browserAuthorization.value = await agentHubApi.startBrowserLogin()
    browserLoginExpiresAt = Date.now() + browserAuthorization.value.expires_in * 1000
    browserLoginOpen.value = true
    await openGithub()
    schedulePoll(browserAuthorization.value.interval)
  } catch (error) {
    showError(error)
  }
}

async function openGithub() {
  const url = browserAuthorization.value?.authorization_url
  if (!url) return
  await open(url)
}

function schedulePoll(seconds: number) {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(pollBrowserLogin, Math.max(2, seconds) * 1000)
}

async function pollBrowserLogin() {
  const authorization = browserAuthorization.value
  if (!authorization || Date.now() >= browserLoginExpiresAt) {
    await cancelBrowserLogin()
    errorMessage.value = t('agentHub.authorizationExpired')
    return
  }
  try {
    const result = await agentHubApi.pollBrowserLogin(
      authorization.flow_id,
      authorization.poll_secret,
    )
    if (result.status === 'authorized') {
      clearBrowserLoginState()
      await loadAuth()
      if (activeTab.value === 'publish') await loadUploads()
      return
    }
    loginError.value = ''
    schedulePoll(result.retry_after_seconds || authorization.interval)
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 422)) {
      await cancelBrowserLogin()
      showError(error)
      return
    }
    loginError.value = error instanceof Error ? error.message : String(error)
    schedulePoll(authorization.interval)
  }
}

function clearBrowserLoginState() {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
  browserLoginOpen.value = false
  browserAuthorization.value = null
  browserLoginExpiresAt = 0
  loginError.value = ''
}

async function cancelBrowserLogin() {
  const authorization = browserAuthorization.value
  clearBrowserLoginState()
  if (!authorization) return
  try {
    await agentHubApi.cancelBrowserLogin(
      authorization.flow_id,
      authorization.poll_secret,
    )
  } catch {
    // The server-side flow expires automatically; closing the dialog must stay immediate.
  }
}

async function logout() {
  await agentHubApi.logout()
  Object.assign(auth, { authenticated: false, user: null })
  uploads.value = []
}

async function install(release: AgentHubRelease) {
  const replace = isInstalled(release.package_id)
  if (replace) {
    const confirmed = await new Promise<boolean>(resolve => {
      dialog.warning({
        title: t('agentHub.update'),
        content: t('agentHub.updateConfirm', { name: release.name }),
        positiveText: t('agentHub.update'),
        negativeText: t('common.cancel'),
        onPositiveClick: () => resolve(true),
        onNegativeClick: () => resolve(false),
        onClose: () => resolve(false),
      })
    })
    if (!confirmed) return
  }
  installingReleaseId.value = release.release_id
  try {
    const result = await agentHubApi.install(release.release_id, replace)
    commands.listAgentPackages()
    const extensions = result.package.extensions as
      | { mcp_servers?: Array<{ payload?: { source?: { distribution?: { requires_configuration?: boolean } } } }> }
      | undefined
    const requiresMcpConfiguration = extensions?.mcp_servers?.some(
      server => server.payload?.source?.distribution?.requires_configuration === true,
    )
    if (requiresMcpConfiguration) {
      message.warning(t('agentHub.installRequiresMcpConfiguration'), { duration: 8000 })
    } else {
      message.success(t('agentHub.installSuccess'))
    }
  } catch (error) {
    showError(error)
  } finally {
    installingReleaseId.value = null
  }
}

async function publish(packageId: string) {
  publishingPackageId.value = packageId
  try {
    await agentHubApi.publish(packageId)
    message.success(t('agentHub.publishSuccess'))
    await loadUploads()
  } catch (error) {
    showError(error)
  } finally {
    publishingPackageId.value = null
  }
}

function isInstalled(packageId: string) {
  return agentStore.agentPackages.some(pkg => pkg.package_id === packageId)
}

function showError(error: unknown) {
  if (error instanceof ApiError && error.detail && typeof error.detail === 'object') {
    const detail = error.detail as { message?: unknown }
    errorMessage.value = String(detail.message || error.message)
  } else {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  }
}

function packageColor(packageId: string) {
  return hashStringToColor(packageId)
}

function formatSize(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(value))
}

function uploadStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  if (status === 'published') return 'success'
  if (status === 'rejected' || status === 'failed') return 'error'
  if (status === 'pending_review') return 'warning'
  return 'info'
}

function uploadStatusLabel(status: string) {
  const labels: Record<string, string> = {
    awaiting_upload: t('agentHub.statusAwaitingUpload'),
    queued: t('agentHub.statusQueued'),
    validating: t('agentHub.statusValidating'),
    pending_review: t('agentHub.statusPendingReview'),
    published: t('agentHub.statusPublished'),
    rejected: t('agentHub.statusRejected'),
    failed: t('agentHub.statusFailed'),
  }
  return labels[status] || status
}
</script>

<style scoped>
.hub-view {
  height: 100%;
  overflow: auto;
  padding: 14px 30px 48px;
  background: var(--app-surface);
}

.hub-tabs {
  max-width: 1200px;
  margin: 0 auto;
}

.identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 34px;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin: 20px 0;
}

.toolbar .n-input {
  max-width: 560px;
}

.page-alert {
  margin: 12px 0 18px;
}

.hub-empty {
  padding: 80px 0;
}

.release-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 16px;
}

.release-heading {
  display: flex;
  align-items: center;
  gap: 11px;
}

.release-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.release-title span {
  color: var(--app-text-muted);
  font-size: 12px;
}

.description {
  min-height: 42px;
  color: var(--app-text);
  line-height: 1.5;
}

.metrics,
.capabilities {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--app-text-muted);
  font-size: 12px;
}

.capabilities {
  margin-top: 12px;
}

.card-actions {
  display: flex;
  justify-content: flex-end;
}

.publish-workspace {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-top: 20px;
}

.publish-intro {
  overflow: hidden;
  padding: 28px;
  border-radius: var(--app-radius-lg);
  background: var(--app-text-strong);
  color: var(--app-text-inverse);
}

.publish-intro-copy {
  display: flex;
  align-items: center;
  gap: 16px;
}

.publish-mark {
  width: 50px;
  height: 50px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--app-text-inverse) 20%, transparent);
  border-radius: 16px;
  background: color-mix(in srgb, var(--app-text-inverse) 10%, transparent);
}

.publish-intro h2 {
  margin: 0;
  font-size: 22px;
  line-height: 1.25;
}

.publish-intro p {
  max-width: 680px;
  margin: 6px 0 0;
  color: color-mix(in srgb, var(--app-text-inverse) 68%, transparent);
  line-height: 1.6;
}

.review-flow {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 26px;
  color: color-mix(in srgb, var(--app-text-inverse) 72%, transparent);
  font-size: 12px;
}

.review-flow span {
  white-space: nowrap;
}

.review-flow i {
  width: 32px;
  height: 1px;
  background: color-mix(in srgb, var(--app-text-inverse) 24%, transparent);
}

.login-panel {
  border-radius: var(--app-radius-md);
}

.publish-panel {
  padding: 24px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.section-heading h3 {
  margin: 0;
  color: var(--app-text-strong);
  font-size: 16px;
}

.section-heading p {
  margin: 5px 0 0;
  color: var(--app-text-muted);
  font-size: 12px;
}

.local-package-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 12px;
}

.local-package-card {
  min-width: 0;
  padding: 17px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  transition:
    border-color var(--app-transition-fast),
    background var(--app-transition-fast);
}

.local-package-card:hover {
  border-color: var(--app-border-hover);
  background: var(--app-surface-hover);
}

.package-card-heading {
  display: flex;
  align-items: center;
  gap: 11px;
}

.package-card-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.package-card-title strong,
.package-card-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.package-card-title span,
.upload-copy span {
  color: var(--app-text-muted);
  font-size: 12px;
}

.local-package-card > p {
  min-height: 40px;
  margin: 15px 0;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.65;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.package-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.package-card-footer > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--app-text-muted);
  font-size: 12px;
}

.upload-list {
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.upload-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--app-divider);
}

.upload-row:last-child {
  border-bottom: 0;
}

.upload-file-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
}

.upload-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.upload-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-error {
  color: var(--app-error) !important;
  overflow-wrap: anywhere;
}

.panel-empty {
  padding: 34px 0;
}

.browser-login-card {
  width: min(440px, calc(100vw - 32px));
}

.browser-login-card p {
  color: var(--app-text-muted);
}

.pending-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 18px;
  color: var(--app-text-muted);
}

.login-error {
  margin: 14px 0 0;
  color: var(--app-error) !important;
  font-size: 12px;
  text-align: center;
}

@media (max-width:700px) {
  .hub-view {
    padding: 10px 14px 30px;
  }

  .identity > span {
    display: none;
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar .n-input {
    max-width: none;
  }

  .publish-intro {
    padding: 22px;
  }

  .publish-intro-copy {
    align-items: flex-start;
  }

  .review-flow {
    align-items: flex-start;
    flex-direction: column;
  }

  .review-flow i {
    width: 1px;
    height: 12px;
    margin-left: 4px;
  }

  .publish-panel {
    padding: 18px;
  }

  .local-package-grid {
    grid-template-columns: 1fr;
  }
}
</style>
