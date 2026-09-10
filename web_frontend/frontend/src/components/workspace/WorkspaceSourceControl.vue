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
          <n-dropdown
            trigger="click"
            :options="branchOptions"
            :disabled="busy || branches.length === 0"
            @select="switchBranch"
            @update:show="refreshBranchesWhenOpened"
          >
            <button type="button" class="branch-pill" :disabled="busy || branches.length === 0">
              <n-icon size="13"><GitBranchOutline /></n-icon>
              <span>{{ status.branch || t('sourceControl.detached') }}</span>
              <n-icon size="11"><ChevronDownOutline /></n-icon>
            </button>
          </n-dropdown>
          <span v-if="status.has_upstream" class="tracking-state">
            <b>↑{{ status.ahead }}</b><i>↓{{ status.behind }}</i>
          </span>
        </div>
        <div class="repository-actions">
          <ControlHint :label="t('sourceControl.pull')" placement="bottom">
            <button type="button" :aria-label="t('sourceControl.pull')" :disabled="busy || !status.has_upstream" @click="runRemote('pull')">
              <n-icon><ArrowDownOutline /></n-icon>
            </button>
          </ControlHint>
          <ControlHint :label="t('sourceControl.push')" placement="bottom">
            <button type="button" :aria-label="t('sourceControl.push')" :disabled="busy || !status.remote_url || !hasCommit" @click="runRemote('push')">
              <n-icon><ArrowUpOutline /></n-icon>
            </button>
          </ControlHint>
        </div>
      </header>

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
          :disabled="busy || !commitMessage.trim() || status.files.length === 0"
          @click="commitChanges"
        >
          {{ t('sourceControl.commit') }}
        </button>
      </div>

      <div v-if="status.files.length" class="change-groups">
        <section class="change-group">
          <header>
            <span>{{ t('sourceControl.changes') }}</span>
            <b>{{ status.files.length }}</b>
          </header>
          <div v-for="file in status.files" :key="file.path" class="repository-change-row" :title="file.path">
            <span>{{ file.path }}</span>
            <small><b>+{{ file.additions }}</b><i>-{{ file.deletions }}</i></small>
          </div>
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

</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { NDropdown, NIcon, NModal, useMessage, type DropdownOption } from 'naive-ui'
import {
  ArrowDownOutline,
  ArrowUpOutline,
  ChevronDownOutline,
  GitBranchOutline,
} from '@/components/icons'
import { GIT_ERROR_CODES, gitApi, type GitRemoteOperationResult, type GitRepositoryBranch, type GitRepositoryStatus } from '@/api/git'
import { githubApi } from '@/api/github'
import { workspaceApi } from '@/api/workspace'
import { useI18n } from '@/composables/useI18n'
import ComboPngIcon from '@/components/icons/ComboPngIcon.vue'
import ControlHint from '@/components/common/ControlHint.vue'

const props = defineProps<{
  workspaceId: string | null | undefined
  workspaceRoot?: string | null
  active?: boolean
}>()
const { t } = useI18n()
const message = useMessage()
const desktopAvailable = isTauri()
const repositoryRoot = ref('')
const status = ref<GitRepositoryStatus | null>(null)
const branches = ref<GitRepositoryBranch[]>([])
const initialized = ref(false)
const loading = ref(false)
const busyAction = ref('')
const errorMessage = ref('')
const commitMessage = ref('')
const identityOpen = ref(false)
const identityName = ref('')
const identityEmail = ref('')
const busy = computed(() => Boolean(busyAction.value))
const hasCommit = computed(() => Boolean(status.value?.has_head && !status.value.detached))
const branchOptions = computed<DropdownOption[]>(() => branches.value.map(branch => ({
  key: branch.name,
  label: branch.current ? `✓ ${branch.name}` : branch.name,
  disabled: branch.current,
})))

watch(() => [props.workspaceId, props.workspaceRoot], loadWorkspace, { immediate: true })
watch(() => props.active, (active) => {
  if (active) void refresh()
})

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
  const requestedRoot = repositoryRoot.value
  errorMessage.value = ''
  try {
    const [nextStatus, nextBranches] = await Promise.all([
      gitApi.repositoryStatus(requestedRoot),
      gitApi.repositoryBranches(requestedRoot),
    ])
    if (repositoryRoot.value !== requestedRoot) return
    status.value = nextStatus
    branches.value = nextBranches
    initialized.value = true
  } catch (error) {
    const detail = errorText(error)
    if (detail.includes('not a Git repository')) {
      status.value = null
      branches.value = []
      initialized.value = false
      return
    }
    errorMessage.value = detail
  }
}

async function refreshBranchesWhenOpened(open: boolean) {
  if (!open || busy.value || !repositoryRoot.value) return
  try {
    const [nextStatus, nextBranches] = await Promise.all([
      gitApi.repositoryStatus(repositoryRoot.value),
      gitApi.repositoryBranches(repositoryRoot.value),
    ])
    status.value = nextStatus
    branches.value = nextBranches
  } catch (error) {
    errorMessage.value = errorText(error)
  }
}

async function switchBranch(value: string | number) {
  const branch = String(value)
  await perform('switch-branch', async () => {
    status.value = await gitApi.switchBranch(repositoryRoot.value, branch)
    branches.value = await gitApi.repositoryBranches(repositoryRoot.value)
  })
}

async function initializeRepository() {
  await perform('initialize', async () => {
    status.value = await gitApi.initializeRepository(repositoryRoot.value)
    branches.value = await gitApi.repositoryBranches(repositoryRoot.value)
    initialized.value = true
    message.success(t('sourceControl.initialized'))
  })
}

async function commitChanges() {
  if (!commitMessage.value.trim() || !status.value?.files.length) return
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
  await gitApi.stageAll(repositoryRoot.value)
  status.value = await gitApi.commit(repositoryRoot.value, commitMessage.value)
  branches.value = await gitApi.repositoryBranches(repositoryRoot.value)
  commitMessage.value = ''
  message.success(t('sourceControl.committed'))
}

async function runRemote(operation: 'pull' | 'push') {
  await perform(operation, async () => {
    if (operation === 'push' && isGitHubRemote(status.value?.remote_url)) {
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
  const detail = error instanceof Error ? error.message : String(error)
  if (detail === GIT_ERROR_CODES.pullRequiresCleanWorktree) {
    return t('sourceControl.pullRequiresCleanWorktree')
  }
  return detail
}

function refreshOnWindowFocus() {
  if (props.active !== false) void refresh()
}

function refreshOnVisibilityChange() {
  if (document.visibilityState === 'visible' && props.active !== false) void refresh()
}

onMounted(() => {
  window.addEventListener('focus', refreshOnWindowFocus)
  document.addEventListener('visibilitychange', refreshOnVisibilityChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('focus', refreshOnWindowFocus)
  document.removeEventListener('visibilitychange', refreshOnVisibilityChange)
})
</script>

<style scoped>
.source-control { display: grid; align-content: start; gap: 10px; padding: 12px; border-bottom: 1px solid var(--app-border); background: var(--app-surface); }
.source-control-state,.clean-state { display: flex; min-height: 38px; align-items: center; justify-content: center; gap: 8px; color: var(--app-text-muted); font-size: 11px; }
.status-dot { width: 6px; height: 6px; border-radius: var(--app-radius-pill); background: var(--app-text); }.status-dot.pulse { animation: status-pulse 1s ease-in-out infinite alternate; }
.initialize-panel { display: grid; gap: 12px; padding: 4px; }.initialize-copy { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; }.initialize-copy > span { display: grid; gap: 3px; }.initialize-copy strong { color: var(--app-text-strong); font-size: 13px; }.initialize-copy small,.remote-hint { color: var(--app-text-muted); font-size: 10px; line-height: 1.5; }
.pill-button { min-height: 32px; padding: 0 13px; border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); color: var(--app-text); background: var(--app-surface); cursor: pointer; }.pill-button.primary,.pill-button.sync { border-color: var(--app-text); color: var(--app-text-inverse); background: var(--app-text); }.pill-button:disabled,button:disabled { opacity: .42; cursor: default; }
.source-control-header,.repository-heading,.repository-actions,.tracking-state { display: flex; align-items: center; }.source-control-header { justify-content: space-between; gap: 10px; }.repository-heading { min-width: 0; gap: 8px; }.branch-pill { min-width: 0; max-width: 220px; display: inline-flex; align-items: center; gap: 5px; padding: 6px 9px; overflow: hidden; border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); color: var(--app-text); background: var(--app-surface); font: inherit; font-size: 10px; cursor: pointer; white-space: nowrap; }.branch-pill span { overflow: hidden; text-overflow: ellipsis; }.tracking-state { gap: 5px; font: 9px/1 var(--app-font-mono); }.tracking-state b,.tracking-state i { color: var(--app-text-muted); font-style: normal; font-weight: 500; }
.repository-actions { gap: 3px; }.repository-actions button { width: 30px; height: 30px; display: grid; place-items: center; padding: 0; border: 0; border-radius: var(--app-radius-sm); color: var(--app-text-secondary); background: transparent; cursor: pointer; }.repository-actions button:hover { background: color-mix(in srgb, var(--app-text) 7%, transparent); }
.commit-box { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; }.commit-box input,.identity-form input { min-width: 0; height: 34px; padding: 0 11px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); outline: none; color: var(--app-text); background: var(--app-surface); font: inherit; font-size: 11px; }.commit-box input:focus,.identity-form input:focus { border-color: var(--app-text); }.commit-button { padding: 0 13px; border: 1px solid var(--app-text); border-radius: var(--app-radius-md); color: var(--app-text-inverse); background: var(--app-text); font-size: 11px; cursor: pointer; }
.change-groups { display: grid; gap: 9px; }.change-group { display: grid; }.change-group > header { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; min-height: 30px; color: var(--app-text-secondary); font-size: 10px; font-weight: 700; }.change-group > header b { min-width: 22px; color: var(--app-text-muted); text-align: center; font: 9px/1 var(--app-font-mono); }.repository-change-row { min-width: 0; min-height: 30px; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 0 7px; border-radius: var(--app-radius-sm); color: var(--app-text-secondary); }.repository-change-row:hover { background: color-mix(in srgb, var(--app-text) 5%, transparent); }.repository-change-row > span { overflow: hidden; font: 10px/1.3 var(--app-font-mono); text-overflow: ellipsis; white-space: nowrap; }.repository-change-row small { display: inline-flex; gap: 5px; font: 9px/1 var(--app-font-mono); }.repository-change-row small b { color: var(--app-diff-addition); }.repository-change-row small i { color: var(--app-diff-deletion); font-style: normal; }
.source-control-error { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 8px 10px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); color: var(--app-text-secondary); font-size: 10px; line-height: 1.5; }.source-control-error span { min-width: 0; overflow-wrap: anywhere; }.source-control-error button { flex: 0 0 auto; padding: 0; border: 0; color: var(--app-text); background: transparent; cursor: pointer; text-decoration: underline; }
:global(.git-identity-modal) { width: min(480px, calc(100vw - 32px)); border-radius: var(--app-radius-lg); }.identity-form { display: grid; gap: 14px; }.identity-form p { margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }.identity-form label { display: grid; gap: 6px; color: var(--app-text-secondary); font-size: 11px; }.identity-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 4px; }
@keyframes status-pulse { to { opacity: .25; } }
</style>
