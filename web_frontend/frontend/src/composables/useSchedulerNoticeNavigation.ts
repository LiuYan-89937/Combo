import { useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useCommand } from '@/composables/useCommand'
import { normalizeResourcePackageId } from '@/utils/resourceScope'
import type { SchedulerRunNoticeView } from '@/types/protocol'

export function useSchedulerNoticeNavigation() {
  const router = useRouter()
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const commands = useCommand()

  function canOpenSchedulerNoticeConversation(notice: SchedulerRunNoticeView): boolean {
    const packageId = normalizeResourcePackageId(notice.packageId)
    return Boolean((packageId && notice.sessionId) || notice.factorySessionId)
  }

  function openSchedulerNoticeConversation(notice: SchedulerRunNoticeView): boolean {
    runtimeStore.markSchedulerNoticeRead(notice.id)
    const packageId = normalizeResourcePackageId(notice.packageId)
    if (packageId && notice.sessionId) {
      agentStore.enterAgentChat(packageId, notice.sessionId)
      void router.push({ name: 'Factory' })
      void commands.selectAgentPackage(packageId, 'run').then(() => {
        void commands.loadAgentPackageSession(packageId, notice.sessionId as string)
      })
      return true
    }
    if (notice.factorySessionId) {
      agentStore.leaveAgentChat()
      runtimeStore.enterFactoryConversation('chat')
      void router.push({ name: 'Factory' })
      commands.switchSession(notice.factorySessionId, 'chat')
      return true
    }
    return false
  }

  return {
    canOpenSchedulerNoticeConversation,
    openSchedulerNoticeConversation,
  }
}
