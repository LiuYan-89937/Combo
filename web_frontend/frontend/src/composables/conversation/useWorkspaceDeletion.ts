import { useDialog } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useCommand } from '@/composables/useCommand'

export function useWorkspaceDeletion(setInteractionLock: (locked: boolean) => void) {
  const dialog = useDialog()
  const commands = useCommand()
  const { t } = useI18n()

  function confirmDeleteWorkspace(
    workspaceId: string,
    name: string,
    rootKind: 'managed' | 'linked',
    onDeleted?: () => void,
  ) {
    setInteractionLock(true)
    dialog.warning({
      title: t('sessions.deleteWorkspaceTitle'),
      content: t(
        rootKind === 'linked'
          ? 'sessions.deleteLinkedWorkspaceContent'
          : 'sessions.deleteManagedWorkspaceContent',
        { name },
      ),
      positiveText: t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        const event = await commands.deleteWorkspaceProject(workspaceId)
        if (event) onDeleted?.()
      },
      onAfterLeave: () => setInteractionLock(false),
    })
  }

  return { confirmDeleteWorkspace }
}
