<template>
  <div class="agent-group-view">
    <section class="chat-container">
      <n-scrollbar ref="scrollbarRef" class="messages-scrollbar">
        <div class="messages-list">
          <n-empty
            v-if="store.transcript.length === 0 && store.activeRuns.length === 0"
            class="group-empty"
            description="暂无群聊消息"
          />
          <MessageItem
            v-for="message in store.transcript"
            :key="message.id"
            :message="message"
            :streaming="message.status === 'streaming'"
          />
        </div>
      </n-scrollbar>

      <section v-if="store.approvalRequests.length" class="approval-section">
        <div v-for="approval in store.approvalRequests" :key="approval.event_id" class="group-approval">
          <ToolApprovalPanel
            :requests="approval.payload?.requests || []"
            @resolve="resolveApproval(approval, $event)"
          />
        </div>
      </section>

      <section v-if="store.activeRuns.length" class="active-runs">
        <n-button
          v-for="run in store.activeRuns"
          :key="run.group_run_id"
          size="small"
          secondary
          type="error"
          @click="store.cancelRun(run.group_run_id)"
        >
          停止 {{ agentName(run.speaker_package_id) }}
        </n-button>
      </section>

      <section v-if="retryableRuns.length" class="active-runs">
        <n-button
          v-for="run in retryableRuns"
          :key="run.group_run_id"
          size="small"
          secondary
          @click="store.retryRun(run.group_run_id)"
        >
          重试 {{ agentName(run.speaker_package_id) }}
        </n-button>
      </section>

      <footer v-if="store.activeGroup" class="composer">
        <div class="mention-control">
          <n-button size="small" quaternary @click="showMentionPicker = !showMentionPicker">@</n-button>
        </div>
        <div v-if="selectedMentions.length" class="selected-mentions">
          <n-tag v-for="packageId in selectedMentions" :key="packageId" closable @close="removeMention(packageId)">
            @{{ agentName(packageId) }}
          </n-tag>
        </div>
        <div v-if="showMentionPicker" class="mention-picker">
          <n-button
            v-for="member in store.members"
            :key="member.package_id"
            size="small"
            quaternary
            @click="selectMention(member.package_id)"
          >
            @{{ agentName(member.package_id) }}
          </n-button>
        </div>
        <MessageInput
          ref="inputRef"
          :placeholder="selectedMentions.length ? '输入消息...' : '输入 @ 选择 Agent，然后输入消息'"
          :disabled="store.saving"
          :is-running="false"
          @send="sendMessage"
          @cancel="cancelActiveRuns"
        />
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NScrollbar, NTag } from 'naive-ui'
import { useAgentGroupStore } from '@/stores/agentGroup'
import MessageInput from '@/components/chat/MessageInput.vue'
import MessageItem from '@/components/chat/MessageItem.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import type { FactoryFrontendEvent, RuntimeAttachmentInput } from '@/types/protocol'

const store = useAgentGroupStore()
const inputRef = ref()
const scrollbarRef = ref()
const selectedMentions = ref<string[]>([])
const showMentionPicker = ref(false)

const activeRunKey = computed(() => store.activeRuns.map(run => `${run.group_run_id}:${run.status}`).join('|'))
const retryableRuns = computed(() => store.runs.filter(run => ['failed', 'cancelled'].includes(run.status)))

onMounted(async () => {
  await store.bootstrap()
  nextTick(() => inputRef.value?.focus())
})

watch(() => store.transcript.map(message => `${message.id}:${message.timestamp}:${message.status}`).join('|'), () => {
  const container = scrollbarRef.value?.scrollbarInstRef?.containerRef || scrollbarRef.value?.containerRef
  if (!container || container.scrollHeight - container.scrollTop - container.clientHeight < 96) {
    nextTick(() => scrollbarRef.value?.scrollTo({ position: 'bottom' }))
  }
})

function agentName(packageId: string): string {
  return store.agentById(packageId)?.agent_name || packageId
}

function selectMention(packageId: string) {
  if (!selectedMentions.value.includes(packageId)) selectedMentions.value.push(packageId)
  showMentionPicker.value = false
}

function removeMention(packageId: string) {
  selectedMentions.value = selectedMentions.value.filter(value => value !== packageId)
}

async function sendMessage(content: string, _attachments: RuntimeAttachmentInput[]) {
  const message = content.trim()
  if (!message || !store.activeGroup) return
  if (!selectedMentions.value.length) {
    await store.sendMessage(message, [])
    return
  }
  await store.sendMessage(message, selectedMentions.value)
  selectedMentions.value = []
  nextTick(() => scrollbarRef.value?.scrollTo({ position: 'bottom', behavior: 'smooth' }))
}

async function resolveApproval(event: FactoryFrontendEvent, payload: Record<string, unknown>) {
  const runId = String(event.payload?.group_run_id || '').trim()
  if (runId) await store.resumeRun(runId, payload)
}

async function cancelActiveRuns() {
  await Promise.all(store.activeRuns.map(run => store.cancelRun(run.group_run_id)))
}

watch(() => activeRunKey.value, () => undefined)
</script>

<style scoped>
.agent-group-view { height: 100%; min-height: 0; }
.chat-container { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.messages-scrollbar { flex: 1; min-height: 0; }
.messages-list { width: min(100%, 920px); margin: 0 auto; padding: var(--app-space-lg); }
.group-empty { min-height: 320px; display: grid; place-items: center; }
.composer { border-top: 1px solid var(--app-border); padding: var(--app-space-md); background: var(--app-surface); }
.mention-control, .selected-mentions, .mention-picker { width: min(100%, 920px); margin: 0 auto var(--app-space-sm); display: flex; gap: var(--app-space-xs); flex-wrap: wrap; }
.approval-section { border-top: 1px solid var(--app-border); padding: var(--app-space-sm) var(--app-space-md); max-height: 38vh; overflow: auto; }
.group-approval + .group-approval { margin-top: var(--app-space-sm); }
.active-runs { display: flex; gap: var(--app-space-xs); flex-wrap: wrap; padding: var(--app-space-sm) var(--app-space-md); border-top: 1px solid var(--app-border); }
</style>
