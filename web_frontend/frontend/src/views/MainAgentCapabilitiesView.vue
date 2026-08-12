<template>
  <main class="profile-page">
    <header class="profile-header">
      <div>
        <span class="eyebrow">MAIN AGENT PROFILE</span>
        <h1>{{ t('mainAgentProfile.title') }}</h1>
        <p>{{ t('mainAgentProfile.description') }}</p>
      </div>
      <div class="header-actions">
        <n-button secondary @click="router.back()">{{ t('common.back') }}</n-button>
        <n-button type="primary" :loading="saving" :disabled="!dirty || loading" @click="saveProfile">
          {{ t('mainAgentProfile.save') }}
        </n-button>
      </div>
    </header>

    <n-alert v-if="restartRequired" type="warning" class="profile-alert" :show-icon="true">
      {{ t('mainAgentProfile.restartRequired') }}
    </n-alert>
    <n-alert v-if="errorText" type="error" closable class="profile-alert" @close="errorText = ''">
      {{ errorText }}
    </n-alert>
    <n-alert v-if="missingSelectedIds.length" type="error" class="profile-alert" :show-icon="true">
      <div class="missing-capability-alert">
        <span>{{ t('mainAgentProfile.missingCapabilities', { count: missingSelectedIds.length }) }}</span>
        <n-button size="small" @click="removeMissingCapabilities">{{ t('mainAgentProfile.removeMissing') }}</n-button>
      </div>
    </n-alert>

    <section class="profile-summary">
      <div><strong>{{ selectedCount }}</strong><span>{{ t('mainAgentProfile.selected') }}</span></div>
      <div><strong>{{ activeCount }}</strong><span>{{ t('mainAgentProfile.active') }}</span></div>
      <div><strong>{{ poolItems.length }}</strong><span>{{ t('mainAgentProfile.available') }}</span></div>
      <p>{{ t('mainAgentProfile.mcpHint') }}</p>
    </section>

    <section class="profile-surface">
      <div class="toolbar">
        <n-input v-model:value="query" clearable :placeholder="t('mainAgentProfile.searchPlaceholder')">
          <template #prefix><n-icon><SearchOutline /></n-icon></template>
        </n-input>
        <n-radio-group v-model:value="activeKind" size="small" class="kind-filter soft-segmented-control">
          <n-radio-button value="all">{{ t('common.all') }}</n-radio-button>
          <n-radio-button value="mcp_server">MCP</n-radio-button>
          <n-radio-button value="skill">Skill</n-radio-button>
          <n-radio-button value="tool">工具</n-radio-button>
        </n-radio-group>
        <n-button quaternary circle :loading="loading" :aria-label="t('common.refresh')" @click="loadProfile">
          <template #icon><n-icon><Refresh /></n-icon></template>
        </n-button>
      </div>

      <div v-if="loading && !profile" class="loading-state"><n-spin size="large" /></div>
      <div v-else-if="visibleItems.length" class="capability-list">
        <article
          v-for="item in visibleItems"
          :key="item.capability_id"
          class="capability-row"
          :class="{ selected: selectedIds.has(item.capability_id) }"
          @click="toggle(item.capability_id)"
        >
          <div class="capability-mark" :class="item.kind">{{ kindMark(item.kind) }}</div>
          <div class="capability-copy">
            <div class="capability-title">
              <strong>{{ item.display_name }}</strong>
              <span>{{ kindLabel(item.kind) }}</span>
              <small v-if="activeIds.has(item.capability_id)">{{ t('mainAgentProfile.active') }}</small>
            </div>
            <p>{{ item.description || t('mainAgentProfile.noDescription') }}</p>
            <div class="capability-meta">
              <span>{{ item.namespace }}</span>
              <span v-if="item.health">{{ item.health }}</span>
              <span v-if="item.kind === 'mcp_server'">{{ t('mainAgentProfile.toolCount', { count: mcpToolCount(item.capability_id) }) }}</span>
            </div>
          </div>
          <n-switch
            :value="selectedIds.has(item.capability_id)"
            :aria-label="t('mainAgentProfile.toggleCapability', { name: item.display_name })"
            @click.stop
            @update:value="setEnabled(item.capability_id, $event)"
          />
        </article>
      </div>
      <n-empty v-else :description="t('mainAgentProfile.empty')" class="empty-state" />
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NEmpty,
  NIcon,
  NInput,
  NRadioButton,
  NRadioGroup,
  NSpin,
  NSwitch,
  useMessage,
} from 'naive-ui'
import { Refresh, SearchOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import {
  capabilityPoolsApi,
  type CapabilityKind,
  type CapabilityPoolItem,
  type MainAgentCapabilityProfile,
} from '@/api/capabilityPools'

type ProfileCapabilityKind = 'mcp_server' | 'skill' | 'tool'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const loading = ref(false)
const saving = ref(false)
const errorText = ref('')
const query = ref('')
const activeKind = ref<'all' | ProfileCapabilityKind>('all')
const profile = ref<MainAgentCapabilityProfile | null>(null)
const poolItems = ref<CapabilityPoolItem[]>([])
const allPoolItems = ref<CapabilityPoolItem[]>([])
const selectedIds = ref(new Set<string>())

const activeIds = computed(() => new Set(profile.value?.active_capability_ids || []))
const selectedCount = computed(() => selectedIds.value.size)
const activeCount = computed(() => activeIds.value.size)
const restartRequired = computed(() => profile.value?.restart_required || false)
const dirty = computed(() => {
  const saved = new Set(profile.value?.capability_ids || [])
  return saved.size !== selectedIds.value.size
    || [...saved].some(identifier => !selectedIds.value.has(identifier))
})
const visibleItems = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return poolItems.value.filter(item => {
    if (activeKind.value !== 'all' && item.kind !== activeKind.value) return false
    if (!needle) return true
    return [item.display_name, item.description, item.namespace, ...item.keywords]
      .join(' ')
      .toLocaleLowerCase()
      .includes(needle)
  })
})
const missingSelectedIds = computed(() => {
  const available = new Set(poolItems.value.map(item => item.capability_id))
  return [...selectedIds.value].filter(identifier => !available.has(identifier))
})

onMounted(loadProfile)

async function loadProfile() {
  if (loading.value) return
  loading.value = true
  errorText.value = ''
  try {
    const [snapshot, nextProfile] = await Promise.all([
      capabilityPoolsApi.snapshot(),
      capabilityPoolsApi.mainAgentProfile(),
    ])
    allPoolItems.value = snapshot.capabilities
    poolItems.value = snapshot.capabilities.filter(isProfileCapability)
    profile.value = nextProfile
    selectedIds.value = new Set(nextProfile.capability_ids)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  if (!profile.value || saving.value || !dirty.value) return
  saving.value = true
  errorText.value = ''
  try {
    profile.value = await capabilityPoolsApi.updateMainAgentProfile({
      revision: profile.value.revision,
      capability_ids: [...selectedIds.value].sort(),
    })
    selectedIds.value = new Set(profile.value.capability_ids)
    message.success(t('mainAgentProfile.saved'))
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    saving.value = false
  }
}

function isProfileCapability(item: CapabilityPoolItem): boolean {
  if (item.kind === 'mcp_server' || item.kind === 'skill') return true
  return item.kind === 'tool' && item.details.system_available !== true
}

function toggle(capabilityId: string) {
  setEnabled(capabilityId, !selectedIds.value.has(capabilityId))
}

function setEnabled(capabilityId: string, enabled: boolean) {
  const next = new Set(selectedIds.value)
  if (enabled) next.add(capabilityId)
  else next.delete(capabilityId)
  selectedIds.value = next
}

function removeMissingCapabilities() {
  const next = new Set(selectedIds.value)
  missingSelectedIds.value.forEach(identifier => next.delete(identifier))
  selectedIds.value = next
}

function kindLabel(kind: CapabilityKind): string {
  if (kind === 'mcp_server') return 'MCP'
  if (kind === 'skill') return 'Skill'
  return 'Tool'
}

function kindMark(kind: CapabilityKind): string {
  if (kind === 'mcp_server') return 'M'
  if (kind === 'skill') return 'S'
  return 'T'
}

function mcpToolCount(serverCapabilityId: string): number {
  return allPoolItems.value.filter(item => (
    item.kind === 'mcp_tool' && item.details.server_capability_id === serverCapabilityId
  )).length
}
</script>

<style scoped>
.profile-page { width: min(1180px, calc(100vw - 48px)); margin: 0 auto; padding: 42px 0 72px; }
.profile-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.eyebrow { color: var(--app-text-muted); font-size: 10px; font-weight: 750; letter-spacing: .14em; }
.profile-header h1 { margin: 8px 0 7px; color: var(--app-text-strong); font-size: 32px; letter-spacing: -.035em; }
.profile-header p { max-width: 680px; margin: 0; color: var(--app-text-muted); line-height: 1.6; }
.header-actions { display: flex; flex: 0 0 auto; gap: 9px; }
.profile-alert { margin-bottom: 16px; border-radius: 14px; }
.missing-capability-alert { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.profile-summary { display: grid; grid-template-columns: repeat(3, 110px) minmax(280px, 1fr); align-items: center; gap: 10px; margin-bottom: 18px; padding: 16px; border: 1px solid var(--app-border); border-radius: 18px; background: var(--app-surface-muted); }
.profile-summary div { display: grid; gap: 2px; }
.profile-summary strong { font-size: 22px; }
.profile-summary span, .profile-summary p { color: var(--app-text-muted); font-size: 11px; }
.profile-summary p { margin: 0; justify-self: end; text-align: right; line-height: 1.5; }
.profile-surface { min-height: 420px; padding: 18px; border: 1px solid var(--app-border); border-radius: 22px; background: var(--app-surface); }
.toolbar { display: grid; grid-template-columns: minmax(260px, 1fr) auto auto; gap: 12px; margin-bottom: 16px; }
.kind-filter { white-space: nowrap; }
.capability-list { display: grid; gap: 9px; }
.capability-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; align-items: center; gap: 13px; padding: 14px; border: 1px solid var(--app-border); border-radius: 16px; cursor: pointer; transition: border-color .16s ease, background .16s ease, transform .18s ease; }
.capability-row:hover { border-color: var(--app-border-hover); transform: translateY(-1px); }
.capability-row.selected { border-color: color-mix(in srgb, var(--app-text) 34%, var(--app-border)); background: var(--app-surface-muted); }
.capability-mark { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 13px; background: var(--app-text); color: var(--app-surface); font-size: 12px; font-weight: 780; }
.capability-copy { min-width: 0; }
.capability-title { display: flex; align-items: center; gap: 8px; }
.capability-title strong { overflow: hidden; color: var(--app-text-strong); text-overflow: ellipsis; white-space: nowrap; }
.capability-title span, .capability-title small { padding: 2px 7px; border-radius: 999px; background: var(--app-surface-pressed); color: var(--app-text-muted); font-size: 9px; }
.capability-title small { color: var(--app-text); }
.capability-copy p { margin: 5px 0 6px; overflow: hidden; color: var(--app-text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.capability-meta { display: flex; gap: 12px; color: var(--app-text-subtle); font-size: 9px; }
.loading-state, .empty-state { display: grid; min-height: 320px; place-items: center; }
@media (max-width: 760px) { .profile-page { width: calc(100vw - 24px); padding-top: 24px; } .profile-header { align-items: stretch; flex-direction: column; } .profile-summary { grid-template-columns: repeat(3, 1fr); } .profile-summary p { grid-column: 1 / -1; justify-self: start; text-align: left; } .toolbar { grid-template-columns: 1fr; } }
</style>
