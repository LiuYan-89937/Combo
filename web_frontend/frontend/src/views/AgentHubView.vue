<template>
  <div class="hub-view">
    <header class="hub-header">
      <div>
        <h1>{{ t('agentHub.title') }}</h1>
        <p>{{ t('agentHub.subtitle') }}</p>
      </div>
      <div class="identity">
        <template v-if="auth.authenticated && auth.user">
          <n-avatar :src="auth.user.avatar_url" round size="small">
            {{ auth.user.github_login.slice(0, 1).toUpperCase() }}
          </n-avatar>
          <span>{{ auth.user.github_login }}</span>
          <n-button quaternary size="small" @click="logout">{{ t('agentHub.logout') }}</n-button>
        </template>
        <n-button v-else type="primary" @click="startLogin">{{ t('agentHub.login') }}</n-button>
      </div>
    </header>

    <n-tabs v-model:value="activeTab" type="line" animated class="hub-tabs">
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
        <n-alert v-if="!auth.authenticated" type="info" class="page-alert">
          {{ t('agentHub.loginHint') }}
          <template #action>
            <n-button size="small" type="primary" @click="startLogin">{{ t('agentHub.login') }}</n-button>
          </template>
        </n-alert>

        <template v-else>
          <section class="publish-section">
            <h2>{{ t('agentHub.publishLocal') }}</h2>
            <div class="local-package-list">
              <div v-for="pkg in publishablePackages" :key="pkg.package_id" class="local-package">
                <div>
                  <strong>{{ pkg.agent_name || pkg.name || pkg.package_id }}</strong>
                  <span>{{ pkg.package_id }}</span>
                </div>
                <n-button
                  type="primary"
                  size="small"
                  :loading="publishingPackageId === pkg.package_id"
                  @click="publish(pkg.package_id)"
                >
                  {{ t('agentHub.publishAction') }}
                </n-button>
              </div>
              <n-empty v-if="publishablePackages.length === 0" :description="t('agents.empty')" />
            </div>
          </section>

          <section class="publish-section">
            <div class="section-heading">
              <h2>{{ t('agentHub.uploads') }}</h2>
              <n-button size="small" @click="loadUploads">{{ t('common.refresh') }}</n-button>
            </div>
            <n-empty v-if="uploads.length === 0" :description="t('agentHub.noUploads')" />
            <div v-else class="upload-list">
              <div v-for="upload in uploads" :key="upload.upload_id" class="upload-row">
                <div>
                  <strong>{{ upload.filename }}</strong>
                  <span>{{ formatDate(upload.updated_at) }}</span>
                </div>
                <div class="upload-status">
                  <n-tag :type="uploadStatusType(upload.status)" size="small">
                    {{ upload.status }}
                  </n-tag>
                  <span v-if="upload.error" class="upload-error">{{ upload.error.message }}</span>
                </div>
              </div>
            </div>
          </section>
        </template>
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
import { Refresh, Search } from '@/components/icons'
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
  try {
    uploads.value = await agentHubApi.uploads()
  } catch (error) {
    showError(error)
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
    await agentHubApi.install(release.release_id, replace)
    commands.listAgentPackages()
    message.success(t('agentHub.installSuccess'))
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
</script>

<style scoped>
.hub-view { height:100%; overflow:auto; padding:26px 30px 40px; background:var(--app-surface-muted) }
.hub-header { display:flex; align-items:center; justify-content:space-between; gap:24px; max-width:1200px; margin:0 auto 18px }
.hub-header h1 { margin:0; font-size:26px; color:var(--app-text-strong) }
.hub-header p { margin:5px 0 0; color:var(--app-text-muted) }
.identity { display:flex; align-items:center; gap:10px }
.hub-tabs { max-width:1200px; margin:0 auto }
.toolbar { display:flex; gap:12px; margin:12px 0 18px }
.toolbar .n-input { max-width:560px }
.page-alert { margin:12px 0 18px }
.hub-empty { padding:80px 0 }
.release-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:16px }
.release-heading { display:flex; align-items:center; gap:11px }
.release-title { flex:1; min-width:0; display:flex; flex-direction:column }
.release-title span,.local-package span,.upload-row span { color:var(--app-text-muted); font-size:12px }
.description { min-height:42px; color:var(--app-text); line-height:1.5 }
.metrics,.capabilities { display:flex; gap:10px; flex-wrap:wrap; color:var(--app-text-muted); font-size:12px }
.capabilities { margin-top:12px }
.card-actions { display:flex; justify-content:flex-end }
.publish-section { background:var(--app-surface); border:1px solid var(--app-divider); border-radius:var(--app-radius-lg); padding:20px; margin:14px 0 20px }
.publish-section h2 { margin:0 0 16px; font-size:17px }
.section-heading { display:flex; justify-content:space-between; align-items:center }
.local-package,.upload-row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:13px 4px; border-bottom:1px solid var(--app-divider) }
.local-package:last-child,.upload-row:last-child { border-bottom:0 }
.local-package > div,.upload-row > div:first-child { display:flex; flex-direction:column; gap:3px }
.upload-status { display:flex; align-items:flex-end; flex-direction:column; gap:4px }
.upload-error { color:var(--app-error)!important; max-width:460px; text-align:right }
.browser-login-card { width:min(440px,calc(100vw - 32px)) }
.browser-login-card p { color:var(--app-text-muted) }
.pending-row { display:flex; align-items:center; justify-content:center; gap:10px; margin-top:18px; color:var(--app-text-muted) }
.login-error { margin:14px 0 0; color:var(--app-error)!important; font-size:12px; text-align:center }
@media (max-width:700px) {
  .hub-view { padding:18px 14px 30px }
  .hub-header { align-items:flex-start; flex-direction:column }
  .toolbar { align-items:stretch; flex-direction:column }
  .toolbar .n-input { max-width:none }
}
</style>
