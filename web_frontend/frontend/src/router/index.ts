/**
 * Vue Router 配置
 */

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/factory',
  },
  {
    path: '/factory',
    name: 'Factory',
    component: () => import('@/views/FactoryView.vue'),
    meta: { title: '闲聊' },
  },
  {
    path: '/manufacturing',
    name: 'Manufacturing',
    component: () => import('@/views/FactoryView.vue'),
    meta: { title: 'Agent 制造' },
  },
  {
    path: '/agents',
    name: 'Agents',
    component: () => import('@/views/PublishedView.vue'),
    meta: { title: '已发布 Agent' },
  },
  {
    path: '/workspace',
    name: 'Workspace',
    component: () => import('@/views/WorkspaceView.vue'),
    meta: { title: '工作区' },
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: { title: '知识库' },
  },
  {
    path: '/scheduler',
    name: 'Scheduler',
    component: () => import('@/views/SchedulerView.vue'),
    meta: { title: '定时任务' },
  },
  {
    path: '/extensions',
    name: 'Extensions',
    component: () => import('@/views/ExtensionsView.vue'),
    meta: { title: '扩展管理' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  // 设置页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title} - FastAgentFactory`
  }
  next()
})

export default router
