<script setup lang="ts">
/*
 * Deterministic square mark for an Agent package. There is no backend icon
 * field, so we render stable initials over a generated monochrome texture keyed
 * on publisher/package_id. Purely decorative — the accessible name comes from
 * the surrounding heading, so this is aria-hidden.
 */
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { agentIdentity, agentTextureDataUri } from '@/composables/useAgentIdentity'
import { useThemeStore } from '@/stores/theme'

const props = withDefaults(
  defineProps<{
    publisher: string
    packageId: string
    size?: number
  }>(),
  { size: 56 },
)

const { theme } = storeToRefs(useThemeStore())

const identity = computed(() => agentIdentity(props.publisher, props.packageId))
const texture = computed(() => agentTextureDataUri(identity.value, theme.value === 'dark'))
const fontSize = computed(() => Math.round(props.size * 0.36))
</script>

<template>
  <span
    class="avatar"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      backgroundImage: `url(&quot;${texture}&quot;)`,
    }"
    aria-hidden="true"
  >
    <span class="avatar__initials mono" :style="{ fontSize: `${fontSize}px` }">
      {{ identity.initials }}
    </span>
  </span>
</template>

<style scoped>
.avatar {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background-size: cover;
  background-position: center;
  overflow: hidden;
}
.avatar__initials {
  font-weight: 650;
  letter-spacing: 0.02em;
  color: var(--text-strong);
  mix-blend-mode: normal;
}
</style>
