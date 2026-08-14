<template>
  <div class="git-import">
    <header class="git-import-header">
      <button type="button" class="back-pill" :disabled="busy" @click="$emit('back')">
        {{ t('gitImport.back') }}
      </button>
      <div>
        <strong>{{ t('gitImport.title') }}</strong>
        <span>{{ t('gitImport.description') }}</span>
      </div>
      <div v-if="account" class="account-pill">
        <img :src="account.avatar_url" alt="" />
        <span>{{ account.login }}</span>
        <button type="button" :disabled="busy" @click="logout">{{ t('gitImport.logout') }}</button>
      </div>
    </header>

    <section v-if="loadingAccount" class="git-import-state">
      <ComboFrameAnimation character="lead" action="idle" :size="60" />
      <span>{{ t('gitImport.checkingAccount') }}</span>
    </section>

    <section v-else-if="!account" class="github-login-panel">
      <img src="/brand/combo/ui-icons/empty-workspace.png" alt="" />
      <strong>{{ t('gitImport.loginTitle') }}</strong>
      <p>{{ t('gitImport.loginDescription') }}</p>
      <button type="button" class="primary-pill" :disabled="loginBusy" @click="login">
        {{ loginBusy ? t('gitImport.waitingAuthorization') : t('gitImport.login') }}
      </button>
      <small>{{ t('gitImport.loginSecurity') }}</small>
    </section>

    <section v-else-if="cloningRepository" class="clone-progress-panel">
      <ComboFrameAnimation character="lead" action="running" :size="72" />
      <strong>{{ t(cloneStageKey) }}</strong>
      <span>{{ cloningRepository.full_name }}</span>
      <div class="clone-progress-track"><i :style="{ width: `${clonePercent}%` }" /></div>
      <div class="clone-progress-meta">
        <span>{{ clonePercent }}%</span>
        <span>{{ formatBytes(cloneProgress.received_bytes) }}</span>
      </div>
    </section>

    <section v-else class="repository-browser">
      <div class="repository-toolbar">
        <n-input v-model:value="query" clearable :placeholder="t('gitImport.searchPlaceholder')" />
        <span>{{ t('gitImport.repositoryCount', { count: filteredRepositories.length }) }}</span>
      </div>

      <div v-if="loadingRepositories" class="git-import-state compact">
        <ComboFrameAnimation character="companion" action="running" :size="42" />
        <span>{{ t('gitImport.loadingRepositories') }}</span>
      </div>
      <div v-else-if="errorMessage" class="git-import-state compact error">
        <span>{{ errorMessage }}</span>
        <button type="button" class="back-pill" @click="loadRepositories">{{ t('gitImport.retry') }}</button>
      </div>
      <div v-else class="repository-list">
        <button
          v-for="repository in filteredRepositories"
          :key="repository.id"
          type="button"
          class="repository-row"
          @click="cloneRepository(repository)"
        >
          <img :src="repository.owner_avatar_url" alt="" />
          <span>
            <strong>{{ repository.full_name }}</strong>
            <small>{{ repository.default_branch }} · {{ formatDate(repository.updated_at) }}</small>
          </span>
          <i>{{ repository.private ? t('gitImport.private') : t('gitImport.public') }}</i>
          <b>{{ t('gitImport.clone') }}</b>
        </button>
        <div v-if="filteredRepositories.length === 0" class="repository-empty">
          {{ t('gitImport.noRepositories') }}
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NInput, useMessage } from 'naive-ui'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import { selectLocalDirectory } from '@/api/desktopDialogs'
import {
  githubApi,
  type GitCloneProgress,
  type GitHubAccount,
  type GitHubRepository,
} from '@/api/github'
import { useI18n } from '@/composables/useI18n'

const emit = defineEmits<{
  back: []
  cloned: [path: string, title: string]
}>()
const { locale, t } = useI18n()
const message = useMessage()
const account = ref<GitHubAccount | null>(null)
const repositories = ref<GitHubRepository[]>([])
const query = ref('')
const loadingAccount = ref(true)
const loadingRepositories = ref(false)
const loginBusy = ref(false)
const cloningRepository = ref<GitHubRepository | null>(null)
const errorMessage = ref('')
const cloneProgress = ref<GitCloneProgress>({
  stage: 'connecting', received_objects: 0, total_objects: 0, indexed_objects: 0, received_bytes: 0,
})
const busy = computed(() => loginBusy.value || Boolean(cloningRepository.value))
const filteredRepositories = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return needle
    ? repositories.value.filter(repository => repository.full_name.toLocaleLowerCase().includes(needle))
    : repositories.value
})
const clonePercent = computed(() => {
  if (cloneProgress.value.stage === 'complete') return 100
  if (cloneProgress.value.total_objects <= 0) return cloneProgress.value.stage === 'connecting' ? 4 : 12
  return Math.min(99, Math.round((cloneProgress.value.received_objects / cloneProgress.value.total_objects) * 100))
})
const cloneStageKey = computed(() => ({
  connecting: 'gitImport.stageConnecting',
  receiving: 'gitImport.stageReceiving',
  complete: 'gitImport.stageComplete',
})[cloneProgress.value.stage] as 'gitImport.stageConnecting' | 'gitImport.stageReceiving' | 'gitImport.stageComplete')

onMounted(async () => {
  try {
    account.value = await githubApi.account()
    if (account.value) await loadRepositories()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loadingAccount.value = false
  }
})

async function login() {
  loginBusy.value = true
  errorMessage.value = ''
  try {
    account.value = await githubApi.login()
    await loadRepositories()
  } catch (error) {
    message.error(errorText(error))
  } finally {
    loginBusy.value = false
  }
}

async function logout() {
  await githubApi.logout()
  account.value = null
  repositories.value = []
}

async function loadRepositories() {
  loadingRepositories.value = true
  errorMessage.value = ''
  try {
    repositories.value = await githubApi.repositories()
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loadingRepositories.value = false
  }
}

async function cloneRepository(repository: GitHubRepository) {
  try {
    const destinationParent = await selectLocalDirectory()
    if (!destinationParent) return
    cloningRepository.value = repository
    cloneProgress.value = {
      stage: 'connecting', received_objects: 0, total_objects: 0, indexed_objects: 0, received_bytes: 0,
    }
    const result = await githubApi.clone(repository, destinationParent, progress => {
      cloneProgress.value = progress
    })
    emit('cloned', result.repository_root, repository.name)
  } catch (error) {
    message.error(errorText(error))
  } finally {
    cloningRepository.value = null
  }
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(value))
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
</script>

<style scoped>
.git-import { height: 100%; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 18px; }
.git-import-header { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 14px; }
.git-import-header > div:nth-child(2) { display: grid; gap: 3px; }.git-import-header strong { color: var(--app-text-strong); }.git-import-header span { color: var(--app-text-muted); font-size: 12px; }
.back-pill, .primary-pill, .account-pill, .repository-row i, .repository-row b { border-radius: 999px; }
.back-pill { min-height: 36px; padding: 0 14px; border: 1px solid var(--app-border); background: var(--app-surface); color: var(--app-text); cursor: pointer; }
.account-pill { display: flex; align-items: center; gap: 8px; padding: 5px 8px 5px 5px; border: 1px solid var(--app-border); }.account-pill img { width: 28px; height: 28px; border-radius: 50%; }.account-pill button { border: 0; background: transparent; color: var(--app-text-muted); cursor: pointer; }
.git-import-state, .github-login-panel, .clone-progress-panel { display: grid; place-content: center; justify-items: center; gap: 12px; min-height: 390px; border: 1px solid var(--app-border); border-radius: 26px; background: var(--app-surface); color: var(--app-text-muted); text-align: center; }
.git-import-state.compact { min-height: 300px; }.git-import-state.error { color: var(--app-error); }
.github-login-panel img { width: 82px; height: 82px; object-fit: contain; filter: var(--app-brand-mark-filter); }.github-login-panel strong, .clone-progress-panel strong { color: var(--app-text-strong); font-size: 22px; }.github-login-panel p { max-width: 440px; margin: 0; color: var(--app-text-secondary); line-height: 1.7; }.github-login-panel small { color: var(--app-text-muted); }
.primary-pill { min-height: 44px; padding: 0 22px; border: 1px solid var(--app-text); background: var(--app-text); color: var(--app-text-inverse); font: inherit; cursor: pointer; }
.repository-browser { min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; }.repository-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; }.repository-toolbar span { color: var(--app-text-muted); font-size: 12px; }
.repository-list { min-height: 0; overflow-y: auto; overscroll-behavior: contain; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: start; gap: 10px; padding-right: 4px; }.repository-row { min-height: 82px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: 12px; width: 100%; padding: 14px; border: 1px solid var(--app-border); border-radius: 18px; background: var(--app-surface); color: var(--app-text); text-align: left; cursor: pointer; transition: border-color 160ms ease, transform 160ms ease; }.repository-row:hover { border-color: var(--app-text); transform: translateY(-1px); }.repository-row img { width: 42px; height: 42px; border-radius: 13px; }.repository-row > span { min-width: 0; display: grid; gap: 4px; }.repository-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.repository-row small { overflow: hidden; color: var(--app-text-muted); text-overflow: ellipsis; white-space: nowrap; }.repository-row i, .repository-row b { padding: 7px 10px; font-size: 11px; font-style: normal; font-weight: 500; white-space: nowrap; }.repository-row i { border: 1px solid var(--app-border); color: var(--app-text-muted); }.repository-row b { background: var(--app-text); color: var(--app-text-inverse); }
.repository-empty { grid-column: 1 / -1; min-height: 240px; display: grid; place-items: center; color: var(--app-text-muted); }.clone-progress-panel > span { color: var(--app-text-muted); }.clone-progress-track { width: min(480px, 70vw); height: 7px; overflow: hidden; border-radius: 999px; background: var(--app-surface-muted); }.clone-progress-track i { display: block; height: 100%; border-radius: inherit; background: var(--app-text); transition: width 180ms ease; }.clone-progress-meta { width: min(480px, 70vw); display: flex; justify-content: space-between; color: var(--app-text-muted); font: 11px/1.2 var(--app-font-mono); }
@media (max-width: 900px) { .repository-list { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .git-import-header { grid-template-columns: auto 1fr; }.account-pill { grid-column: 1 / -1; justify-self: start; }.repository-row { grid-template-columns: auto minmax(0, 1fr) auto; }.repository-row i { display: none; } }
</style>
