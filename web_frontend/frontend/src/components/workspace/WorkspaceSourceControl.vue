<template>
  <section v-if="desktopAvailable && repositoryRoot" class="source-control">
    <div v-if="loading" class="source-control-state">
      <span class="status-dot pulse"></span>
      <span>{{ t('sourceControl.loading') }}</span>
    </div>

    <div v-else-if="!initialized" class="initialize-panel">
      <div class="initialize-copy">
        <ComboPngIcon name="empty-workspace" :size="38" />
        <span>
          <strong>{{ t('sourceControl.initializeTitle') }}</strong>
          <small>{{ t('sourceControl.initializeDescription') }}</small>
        </span>
      </div>
      <button type="button" class="pill-button primary" :disabled="busy" @click="initializeRepository">
        {{ t('sourceControl.initialize') }}
      </button>
    </div>

    <template v-else-if="status">
      <header class="source-control-header">
        <div class="repository-heading">
          <span class="branch-pill">
            <n-icon size="13"><GitBranchOutline /></n-icon>
            {{ status.branch || t('sourceControl.detached') }}
          </span>
          <span v-if="status.has_upstream" class="tracking-state">
            <b>↑{{ status.ahead }}</b><i>↓{{ status.behind }}</i>
          </span>
        </div>
        <div class="repository-actions">
          <button type="button" :title="t('sourceControl.refresh')" :disabled="busy" @click="refresh">
            <n-icon><RefreshOutline /></n-icon>
          </button>
          <button
            v-if="status.remote_url"
            type="button"
            :title="t('sourceControl.fetch')"
            :disabled="busy"
            @click="runRemote('fetch')"
          >
            <n-icon><CloudDownloadOutline /></n-icon>
          </button>
          <button
            v-if="status.has_upstream"
            type="button"
            :title="t('sourceControl.pull')"
            :disabled="busy"
            @click="runRemote('pull')"
          >
            <n-icon><ArrowDownOutline /></n-icon>
          </button>
          <button
            v-if="status.remote_url"
            type="button"
            :title="t('sourceControl.push')"
            :disabled="busy || !hasCommit"
            @click="runRemote('push')"
          >
            <n-icon><ArrowUpOutline /></n-icon>
          </button>
        </div>
      </header>

      <div v-if="status.remote_url" class="sync-row">
        <span class="remote-name" :title="status.remote_url">
          {{ status.remote_name || t('sourceControl.remote') }}
        </span>
        <button
          type="button"
          class="pill-button sync"
          :disabled="busy || (!status.has_upstream && !hasCommit)"
          @click="runRemote(status.has_upstream ? 'sync' : 'push')"
        >
          <n-icon size="13"><SyncOutline /></n-icon>
          {{ status.has_upstream ? t('sourceControl.sync') : t('sourceControl.publishBranch') }}
        </button>
      </div>
      <div v-else class="remote-empty">
        <p class="remote-hint">{{ t('sourceControl.noRemote') }}</p>
        <div class="remote-empty-actions">
          <button type="button" class="pill-button primary" :disabled="busy || !hasCommit" @click="openPublishDialog">
            {{ t('sourceControl.publishToGitHub') }}
          </button>
          <button type="button" class="pill-button" :disabled="busy" @click="remoteOpen = true">
            {{ t('sourceControl.addRemote') }}
          </button>
        </div>
      </div>

      <div class="commit-box">
        <input
          v-model="commitMessage"
          type="text"
          :placeholder="t('sourceControl.commitPlaceholder')"
          :disabled="busy"
          @keydown.enter.prevent="commitChanges"
        />
        <button
          type="button"
          class="commit-button"
          :disabled="busy || !commitMessage.trim() || stagedFiles.length === 0"
          @click="commitChanges"
        >
          {{ t('sourceControl.commit') }}
        </button>
      </div>

      <div v-if="status.files.length" class="change-groups">
        <section v-if="stagedFiles.length" class="change-group">
          <header>
            <span>{{ t('sourceControl.stagedChanges') }}</span>
            <b>{{ stagedFiles.length }}</b>
            <button type="button" :title="t('sourceControl.unstageAll')" :disabled="busy" @click="unstage(stagedFiles.map(file => file.path))">−</button>
          </header>
          <WorkspaceGitFileRow
            v-for="file in stagedFiles"
            :key="`staged:${file.path}`"
            :file="file"
            action="unstage"
            @action="unstage([file.path])"
          />
        </section>

        <section v-if="unstagedFiles.length" class="change-group">
          <header>
            <span>{{ t('sourceControl.changes') }}</span>
            <b>{{ unstagedFiles.length }}</b>
            <button type="button" :title="t('sourceControl.stageAll')" :disabled="busy" @click="stageAll">+</button>
          </header>
          <WorkspaceGitFileRow
            v-for="file in unstagedFiles"
            :key="`unstaged:${file.path}`"
            :file="file"
            action="stage"
            @action="stage([file.path])"
          />
        </section>
      </div>
      <div v-else class="clean-state">
        <span class="status-dot"></span>
        {{ t('sourceControl.clean') }}
      </div>
    </template>

    <div v-if="errorMessage" class="source-control-error" role="alert">
      <span>{{ errorMessage }}</span>
      <button type="button" @click="refresh">{{ t('sourceControl.retry') }}</button>
    </div>
  </section>

  <n-modal v-model:show="identityOpen" preset="card" class="git-identity-modal" :title="t('sourceControl.identityTitle')">
    <div class="identity-form">
      <p>{{ t('sourceControl.identityDescription') }}</p>
      <label>
        <span>{{ t('sourceControl.identityName') }}</span>
        <input v-model="identityName" autocomplete="name" />
      </label>
      <label>
        <span>{{ t('sourceControl.identityEmail') }}</span>
        <input v-model="identityEmail" type="email" autocomplete="email" />
      </label>
      <div class="identity-actions">
        <button type="button" class="pill-button" @click="identityOpen = false">{{ t('common.cancel') }}</button>
        <button type="button" class="pill-button primary" :disabled="busy || !identityName.trim() || !identityEmail.trim()" @click="saveIdentityAndCommit">
          {{ t('sourceControl.saveAndCommit') }}
        </button>
      </div>
    </div>
  </n-modal>

  <n-modal v-model:show="remoteOpen" preset="card" class="git-identity-modal" :title="t('sourceControl.addRemoteTitle')">
    <div class="identity-form">
      <p>{{ t('sourceControl.addRemoteDescription') }}</p>
      <label>
        <span>{{ t('sourceControl.remoteUrl') }}</span>
        <input v-model="remoteUrl" type="url" placeholder="https://github.com/owner/repository.git" />
      </label>
      <div class="identity-actions">
        <button type="button" class="pill-button" @click="remoteOpen = false">{{ t('common.cancel') }}</button>
        <button type="button" class="pill-button primary" :disabled="busy || !remoteUrl.trim()" @click="addRemote">
          {{ t('sourceControl.addRemote') }}
        </button>
      </div>
    </div>
  </n-modal>

  <n-modal v-model:show="publishOpen" preset="card" class="git-identity-modal" :title="t('sourceControl.publishTitle')">
    <div class="identity-form">
      <p>{{ t('sourceControl.publishDescription') }}</p>
      <label>
        <span>{{ t('sourceControl.repositoryName') }}</span>
        <input v-model="publishName" />
      </label>
      <button type="button" class="visibility-choice" @click="publishPrivate = !publishPrivate">
        <span>
          <strong>{{ publishPrivate ? t('sourceControl.privateRepository') : t('sourceControl.publicRepository') }}</strong>
          <small>{{ publishPrivate ? t('sourceControl.privateRepositoryDescription') : t('sourceControl.publicRepositoryDescription') }}</small>
        </span>
        <i :class="{ active: publishPrivate }"></i>
      </button>
      <div class="identity-actions">
        <button type="button" class="pill-button" @click="publishOpen = false">{{ t('common.cancel') }}</button>
        <button type="button" class="pill-button primary" :disabled="busy || !publishName.trim()" @click="publishToGitHub">
          {{ t('sourceControl.publish') }}
        </button>
      </div>
    </div>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { NIcon, NModal, useMessage } from 'naive-ui'
import {
  ArrowDownOutline,
  ArrowUpOutline,
  CloudDownloadOutline,
  GitBranchOutline,
  RefreshOutline,
  SyncOutline,
} from '@/components/icons'
import { gitApi, type GitRemoteOperationResult, type GitRepositoryStatus } from '@/api/git'
import { githubApi } from '@/api/github'
import { workspaceApi } from '@/api/workspace'
import { useI18n } from '@/composables/useI18n'
import ComboPngIcon from '@/components/icons/ComboPngIcon.vue'
import WorkspaceGitFileRow from './WorkspaceGitFileRow.vue'

const props = defineProps<{
  workspaceId: string | null | undefined
  workspaceRoot?: string | null
}>()
const { t } = useI18n()
const message = useMessage()
const desktopAvailable = isTauri()
const repositoryRoot = ref('')
const status = ref<GitRepositoryStatus | null>(null)
const initialized = ref(false)
const loading = ref(false)
const busyAction = ref('')
const errorMessage = ref('')
const commitMessage = ref('')
const identityOpen = ref(false)
const identityName = ref('')
const identityEmail = ref('')
const remoteOpen = ref(false)
const remoteUrl = ref('')
const publishOpen = ref(false)
const publishName = ref('')
const publishPrivate = ref(true)
const busy = computed(() => Boolean(busyAction.value))
const stagedFiles = computed(() => status.value?.files.filter(file => file.staged) || [])
const unstagedFiles = computed(() => status.value?.files.filter(file => file.unstaged || !file.staged) || [])
const hasCommit = computed(() => Boolean(status.value?.has_head && !status.value.detached))

watch(() => [props.workspaceId, props.workspaceRoot], loadWorkspace, { immediate: true })

async function loadWorkspace() {
  repositoryRoot.value = String(props.workspaceRoot || '').trim()
  status.value = null
  initialized.value = false
  errorMessage.value = ''
  if (!desktopAvailable) return
  loading.value = true
  try {
    if (!repositoryRoot.value && props.workspaceId) {
      const projects = await workspaceApi.projects()
      repositoryRoot.value = projects.workspaces.find(item => item.workspace_id === props.workspaceId)?.workdir_root || ''
    }
    if (repositoryRoot.value) await refresh()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (!repositoryRoot.value) return
  errorMessage.value = ''
  try {
    status.value = await gitApi.repositoryStatus(repositoryRoot.value)
    initialized.value = true
  } catch (error) {
    const detail = errorText(error)
    if (detail.includes('not a Git repository')) {
      status.value = null
      initialized.value = false
      return
    }
    errorMessage.value = detail
  }
}

async function initializeRepository() {
  await perform('initialize', async () => {
    status.value = await gitApi.initializeRepository(repositoryRoot.value)
    initialized.value = true
    message.success(t('sourceControl.initialized'))
  })
}

async function stage(paths: string[]) {
  await perform('stage', async () => {
    status.value = await gitApi.stagePaths(repositoryRoot.value, paths)
  })
}

async function stageAll() {
  await perform('stage', async () => {
    status.value = await gitApi.stageAll(repositoryRoot.value)
  })
}

async function unstage(paths: string[]) {
  await perform('unstage', async () => {
    status.value = await gitApi.unstagePaths(repositoryRoot.value, paths)
  })
}

async function commitChanges() {
  if (!commitMessage.value.trim() || stagedFiles.value.length === 0) return
  await perform('commit', async () => {
    const identity = await gitApi.repositoryIdentity(repositoryRoot.value)
    if (!identity.configured) {
      identityName.value = identity.name || ''
      identityEmail.value = identity.email || ''
      identityOpen.value = true
      return
    }
    await finishCommit()
  })
}

async function saveIdentityAndCommit() {
  await perform('identity', async () => {
    await gitApi.setRepositoryIdentity(repositoryRoot.value, identityName.value, identityEmail.value)
    identityOpen.value = false
    await finishCommit()
  })
}

async function finishCommit() {
  status.value = await gitApi.commit(repositoryRoot.value, commitMessage.value)
  commitMessage.value = ''
  message.success(t('sourceControl.committed'))
}

async function runRemote(operation: 'fetch' | 'pull' | 'push' | 'sync') {
  await perform(operation, async () => {
    if ((operation === 'push' || operation === 'sync') && isGitHubRemote(status.value?.remote_url)) {
      const account = await githubApi.account()
      if (!account) {
        message.info(t('sourceControl.loginRequired'))
        await githubApi.login(() => message.info(t('gitImport.waitingAuthorization')))
      }
    }
    const result = await gitApi[operation](repositoryRoot.value)
    applyRemoteResult(result)
  })
}

function openPublishDialog() {
  publishName.value = repositoryRoot.value.split(/[\\/]/).filter(Boolean).at(-1) || ''
  publishPrivate.value = true
  publishOpen.value = true
}

async function addRemote() {
  await perform('remote', async () => {
    status.value = await gitApi.addRemote(repositoryRoot.value, remoteUrl.value)
    remoteUrl.value = ''
    remoteOpen.value = false
    message.success(t('sourceControl.remoteAdded'))
  })
}

async function publishToGitHub() {
  await perform('publish', async () => {
    const account = await githubApi.account()
    if (!account) {
      message.info(t('sourceControl.loginRequired'))
      await githubApi.login(() => message.info(t('gitImport.waitingAuthorization')))
    }
    const repository = await githubApi.createRepository(publishName.value, publishPrivate.value)
    status.value = await gitApi.addRemote(repositoryRoot.value, repository.clone_url)
    const result = await gitApi.push(repositoryRoot.value)
    applyRemoteResult(result)
    publishOpen.value = false
  })
}

function applyRemoteResult(result: GitRemoteOperationResult) {
  status.value = result.status
  if (result.outcome === 'conflicts') {
    message.error(t('sourceControl.conflicts', { count: result.conflicting_files.length }))
    return
  }
  message.success(t(`sourceControl.outcome.${result.outcome}`))
}

async function perform(action: string, operation: () => Promise<void>) {
  if (busy.value || !repositoryRoot.value) return
  busyAction.value = action
  errorMessage.value = ''
  try {
    await operation()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    busyAction.value = ''
  }
}

function isGitHubRemote(value: string | null | undefined): boolean {
  return /^https:\/\/github\.com\//i.test(String(value || ''))
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
</script>

<style scoped>
.source-control { flex: 0 0 auto; display: grid; gap: 10px; padding: 12px; border-bottom: 1px solid var(--app-border); background: var(--app-surface); }
.source-control-state,.clean-state { display: flex; min-height: 38px; align-items: center; justify-content: center; gap: 8px; color: var(--app-text-muted); font-size: 11px; }
.status-dot { width: 6px; height: 6px; border-radius: 999px; background: var(--app-text); }.status-dot.pulse { animation: status-pulse 1s ease-in-out infinite alternate; }
.initialize-panel { display: grid; gap: 12px; padding: 4px; }.initialize-copy { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; }.initialize-copy > span { display: grid; gap: 3px; }.initialize-copy strong { color: var(--app-text-strong); font-size: 13px; }.initialize-copy small,.remote-hint { color: var(--app-text-muted); font-size: 10px; line-height: 1.5; }
.pill-button { min-height: 32px; padding: 0 13px; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text); background: var(--app-surface); cursor: pointer; }.pill-button.primary,.pill-button.sync { border-color: var(--app-text); color: var(--app-text-inverse); background: var(--app-text); }.pill-button:disabled,button:disabled { opacity: .42; cursor: default; }
.source-control-header,.sync-row,.repository-heading,.repository-actions,.tracking-state { display: flex; align-items: center; }.source-control-header,.sync-row { justify-content: space-between; gap: 10px; }.repository-heading { min-width: 0; gap: 8px; }.branch-pill { min-width: 0; display: inline-flex; align-items: center; gap: 5px; padding: 6px 9px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.tracking-state { gap: 5px; font: 9px/1 var(--app-font-mono); }.tracking-state b,.tracking-state i { color: var(--app-text-muted); font-style: normal; font-weight: 500; }
.repository-actions { gap: 3px; }.repository-actions button,.change-group header button { width: 28px; height: 28px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 9px; color: var(--app-text-secondary); background: transparent; cursor: pointer; }.repository-actions button:hover,.change-group header button:hover { background: color-mix(in srgb, var(--app-text) 7%, transparent); }.remote-name { min-width: 0; overflow: hidden; color: var(--app-text-muted); font: 10px/1.2 var(--app-font-mono); text-overflow: ellipsis; white-space: nowrap; }.pill-button.sync { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 6px; min-height: 29px; font-size: 10px; }.remote-hint { margin: 0; }.remote-empty { display: grid; gap: 8px; }.remote-empty-actions { display: flex; flex-wrap: wrap; gap: 6px; }.remote-empty-actions .pill-button { min-height: 29px; font-size: 10px; }
.commit-box { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; }.commit-box input,.identity-form input { min-width: 0; height: 34px; padding: 0 11px; border: 1px solid var(--app-border); border-radius: 11px; outline: none; color: var(--app-text); background: var(--app-surface); font: inherit; font-size: 11px; }.commit-box input:focus,.identity-form input:focus { border-color: var(--app-text); }.commit-button { padding: 0 13px; border: 1px solid var(--app-text); border-radius: 11px; color: var(--app-text-inverse); background: var(--app-text); font-size: 11px; cursor: pointer; }
.change-groups { display: grid; gap: 9px; max-height: 270px; overflow-y: auto; }.change-group { display: grid; }.change-group > header { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; min-height: 30px; color: var(--app-text-secondary); font-size: 10px; font-weight: 700; }.change-group > header b { min-width: 22px; color: var(--app-text-muted); text-align: center; font: 9px/1 var(--app-font-mono); }
.source-control-error { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 8px 10px; border: 1px solid var(--app-border); border-radius: 11px; color: var(--app-text-secondary); font-size: 10px; line-height: 1.5; }.source-control-error span { min-width: 0; overflow-wrap: anywhere; }.source-control-error button { flex: 0 0 auto; padding: 0; border: 0; color: var(--app-text); background: transparent; cursor: pointer; text-decoration: underline; }
:global(.git-identity-modal) { width: min(480px, calc(100vw - 32px)); border-radius: 24px; }.identity-form { display: grid; gap: 14px; }.identity-form p { margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }.identity-form label { display: grid; gap: 6px; color: var(--app-text-secondary); font-size: 11px; }.identity-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 4px; }
.visibility-choice { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 14px; padding: 12px; border: 1px solid var(--app-border); border-radius: 14px; color: var(--app-text); text-align: left; background: var(--app-surface); cursor: pointer; }.visibility-choice > span { display: grid; gap: 3px; }.visibility-choice strong { font-size: 12px; }.visibility-choice small { color: var(--app-text-muted); font-size: 10px; line-height: 1.45; }.visibility-choice i { position: relative; width: 32px; height: 18px; border-radius: 999px; background: var(--app-border-hover); }.visibility-choice i::after { position: absolute; top: 3px; left: 3px; width: 12px; height: 12px; border-radius: 50%; background: var(--app-surface); content: ''; transition: transform .16s ease; }.visibility-choice i.active { background: var(--app-text); }.visibility-choice i.active::after { transform: translateX(14px); }
@keyframes status-pulse { to { opacity: .25; } }
</style>
