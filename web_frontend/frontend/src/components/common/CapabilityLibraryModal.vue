<template>
  <n-modal
    :show="show"
    preset="card"
    class="capability-library-modal"
    :bordered="false"
    :title="t('capabilityLibrary.title')"
    @update:show="emit('update:show', $event)"
  >
    <div class="library-lead">
      <p class="library-intro">{{ t('capabilityLibrary.description') }}</p>
    </div>

    <section class="library-section">
      <div class="section-heading">
        <span>{{ t('capabilityLibrary.resources') }}</span>
        <small>{{ t('capabilityLibrary.resourcesHint') }}</small>
      </div>
      <div class="library-grid resource-grid">
        <button class="library-entry compact" type="button" @click="openCapabilityPool('mcp')">
          <n-icon size="20"><ExtensionPuzzleOutline /></n-icon>
          <span><strong>MCP</strong><small>{{ t('capabilityPools.mcpHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openCapabilityPool('tools')">
          <n-icon size="20"><ConstructOutline /></n-icon>
          <span><strong>Tool</strong><small>{{ t('capabilityPools.toolHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openCapabilityPool('skills')">
          <n-icon size="20"><SparklesOutline /></n-icon>
          <span><strong>Skill</strong><small>{{ t('capabilityPools.skillHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('ModelPool')">
          <n-icon size="20"><LayersOutline /></n-icon>
          <span><strong>模型池</strong><small>模型、凭据与运行时默认绑定。</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('Knowledge')">
          <n-icon size="20"><LibraryOutline /></n-icon>
          <span><strong>{{ t('route.knowledge') }}</strong><small>{{ t('capabilityLibrary.knowledgeHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('Scheduler')">
          <n-icon size="20"><TimeOutline /></n-icon>
          <span><strong>{{ t('route.scheduler') }}</strong><small>{{ t('capabilityLibrary.schedulerHint') }}</small></span>
        </button>
      </div>
    </section>
  </n-modal>
</template>

<script setup lang="ts">
import { NIcon, NModal } from 'naive-ui'
import {
  ExtensionPuzzleOutline,
  ConstructOutline,
  LibraryOutline,
  SparklesOutline,
  TimeOutline,
  LayersOutline,
} from '@/components/icons'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()
const router = useRouter()
const { t } = useI18n()

function openRoute(name: 'Knowledge' | 'Scheduler' | 'ModelPool') {
  emit('update:show', false)
  void router.push({ name })
}

function openCapabilityPool(pool: 'mcp' | 'tools' | 'skills') {
  emit('update:show', false)
  const routeNames = { mcp: 'McpPool', tools: 'ToolPool', skills: 'SkillPool' } as const
  void router.push({ name: routeNames[pool] })
}
</script>

<style>
.capability-library-modal.n-card {
  width: min(760px, calc(100vw - 40px));
  border: 1px solid var(--app-border);
  border-radius: 24px;
  background: var(--app-surface);
  box-shadow: 0 30px 90px color-mix(in srgb, var(--app-text) 18%, transparent);
}
</style>

<style scoped>
.library-lead { display: flex; align-items: center; gap: 16px; margin: -10px 0 22px; padding: 8px 14px 8px 8px; border-radius: 16px; background: var(--app-surface-muted); }
.library-intro { margin: 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.6; }
.library-section + .library-section { margin-top: 26px; }
.section-heading { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.section-heading span { font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.section-heading small { color: var(--app-text-muted); font-size: 11px; }
.library-grid { display: grid; gap: 10px; }
.resource-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.library-entry {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 104px;
  padding: 16px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  background: var(--app-surface);
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition: transform .24s cubic-bezier(.16, 1, .3, 1), border-color .2s ease, box-shadow .24s ease;
}
.library-entry:hover { transform: translateY(-3px); border-color: var(--app-border-focus); box-shadow: 0 14px 30px color-mix(in srgb, var(--app-text) 9%, transparent); }
.library-entry:hover > .n-icon { color: var(--app-text); transform: rotate(-4deg) scale(1.06); }
.library-entry > .n-icon { transition: color var(--app-transition-fast), transform var(--app-transition-base); }
.library-entry:active { transform: translateY(-1px) scale(.99); }
.library-entry.featured { background: var(--app-text); color: var(--app-surface); border-color: var(--app-text); }
.library-entry.compact { min-height: 76px; }
.library-entry span { display: grid; min-width: 0; gap: 4px; }
.library-entry strong { font-size: 13px; }
.library-entry small { color: currentColor; font-size: 11px; line-height: 1.45; opacity: .62; }
.entry-arrow { opacity: .45; transition: transform .2s ease, opacity .2s ease; }
.library-entry:hover .entry-arrow { opacity: 1; transform: translateX(3px); }
@media (max-width: 720px) { .agent-grid, .resource-grid { grid-template-columns: 1fr; } }
</style>
