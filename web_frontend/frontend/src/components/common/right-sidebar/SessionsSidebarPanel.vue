<template>
  <AgentSessionPanel
    v-if="agentSessionContextActive && workspacePackageId"
    :package-id="workspacePackageId"
    @request-new-session="forwardNewAgentSessionRequest"
    @interaction-lock="emit('interactionLock', $event)"
  />
  <SessionSidebar
    v-else
    :title="t('sessions.main')"
    @request-new-agent-session="forwardNewAgentSessionRequest"
    @interaction-lock="emit('interactionLock', $event)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useResourceContext } from '@/composables/useResourceContext'
import AgentSessionPanel from '@/components/agent/AgentSessionPanel.vue'
import SessionSidebar from '@/components/chat/SessionSidebar.vue'

const resourceContext = useResourceContext()
const { t } = useI18n()
const emit = defineEmits<{
  requestNewAgentSession: [packageId: string, initialWorkspaceId: string | null]
  interactionLock: [locked: boolean]
}>()
const agentSessionContextActive = computed(() => resourceContext.isAgentSessionContext.value)
const workspacePackageId = computed(() => resourceContext.packageIdForApi.value)

function forwardNewAgentSessionRequest(packageId: string, initialWorkspaceId: string | null) {
  emit('requestNewAgentSession', packageId, initialWorkspaceId)
}
</script>
