/**
 * Vue Router 配置
 */

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import {
  detectBrowserLocale,
  localeStorageKey,
  normalizeLocale,
  routeTitleKey,
  translate,
} from '@/i18n'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/factory',
  },
  {
    path: '/factory',
    name: 'Factory',
    component: () => import('@/views/FactoryView.vue'),
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
  },
  {
    path: '/scheduler',
    name: 'Scheduler',
    component: () => import('@/views/SchedulerView.vue'),
  },
  {
    path: '/extensions',
    name: 'Extensions',
    redirect: { name: 'McpPool' },
  },
  {
    path: '/capabilities/mcp',
    name: 'McpPool',
    component: () => import('@/views/ExtensionsView.vue'),
    props: { pool: 'mcp' },
  },
  {
    path: '/capabilities/tools',
    name: 'ToolPool',
    component: () => import('@/views/ExtensionsView.vue'),
    props: { pool: 'tools' },
  },
  {
    path: '/capabilities/skills',
    name: 'SkillPool',
    component: () => import('@/views/ExtensionsView.vue'),
    props: { pool: 'skills' },
  },
  {
    path: '/model-pool',
    name: 'ModelPool',
    component: () => import('@/views/ModelPoolView.vue'),
  },
  {
    path: '/main-agent-capabilities',
    name: 'MainAgentCapabilities',
    component: () => import('@/views/MainAgentCapabilitiesView.vue'),
  },
  {
    path: '/mascot-preview',
    name: 'MascotPreview',
    component: () => import('@/views/MascotPreviewView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (typeof document !== 'undefined') {
    const storedLocale = typeof window === 'undefined' ? null : window.localStorage.getItem(localeStorageKey)
    const locale = storedLocale ? normalizeLocale(storedLocale) : detectBrowserLocale()
    document.title = `${translate(locale, routeTitleKey(to.name))} - Combo`
  }
  next()
})

export default router
