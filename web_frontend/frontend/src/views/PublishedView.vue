<template>
  <div class="published-view">
    <AgentPackageList />
  </div>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import AgentPackageList from '@/components/agent/AgentPackageList.vue'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'

const agentStore = useAgentStore()
const uiStore = useUiStore()

watch(
  () => agentStore.agentPackages.map((pkg) => pkg.package_id),
  (packageIds) => {
    if (packageIds.length === 0) return
    if (!agentStore.selectedPackageId || !packageIds.includes(agentStore.selectedPackageId)) {
      agentStore.selectPackage(packageIds[0])
    }
  },
  { immediate: true },
)

onMounted(() => {
  uiStore.openRightSidebar('status')
})
</script>

<style scoped>
.published-view {
  height: 100%;
  background: var(--app-surface);
}
</style>
