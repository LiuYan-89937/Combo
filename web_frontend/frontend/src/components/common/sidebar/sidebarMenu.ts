import { h } from 'vue'
import { NIcon } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import {
  Build,
  ChatbubbleEllipses,
  ExtensionPuzzle,
  GitCompare,
  Layers,
  Library,
  Rocket,
  Time,
} from '@/components/icons'
import type { I18nKey } from '@/i18n'

type Translate = (key: I18nKey) => string

export function sidebarMenuOptions(t: Translate): MenuOption[] {
  return [
    {
      label: t('route.chat'),
      key: '/factory',
      icon: renderIcon(ChatbubbleEllipses),
    },
    {
      label: t('route.manufacturing'),
      key: '/manufacturing',
      icon: renderIcon(Build),
    },
    {
      label: t('route.evolution'),
      key: '/evolution',
      icon: renderIcon(GitCompare),
    },
    {
      label: t('route.agents'),
      key: '/agents',
      icon: renderIcon(Rocket),
    },
    {
      type: 'divider',
      key: 'd1',
    },
    {
      label: t('sidebar.resources'),
      key: 'resources',
      children: [
        {
          label: t('route.knowledge'),
          key: '/knowledge',
          icon: renderIcon(Library),
        },
        {
          label: t('route.scheduler'),
          key: '/scheduler',
          icon: renderIcon(Time),
        },
        {
          label: t('route.extensions'),
          key: '/extensions',
          icon: renderIcon(ExtensionPuzzle),
        },
        {
          label: t('route.modelPool'),
          key: '/model-pool',
          icon: renderIcon(Layers),
        },
      ],
    },
  ]
}

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}
