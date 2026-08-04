<template>
  <div class="published-view">
    <AgentPackageList />
  </div>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import AgentPackageList from '@/components/agent/AgentPackageList.vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()

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

</script>

<style scoped>
.published-view {
  height: 100%;
  background: var(--app-surface);
}
</style>
