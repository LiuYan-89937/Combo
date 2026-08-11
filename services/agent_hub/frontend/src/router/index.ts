/*
 * SPA router. All routes below the shell are lazy so each page is its own
 * chunk. Scroll is restored on back/forward and reset to top otherwise; hash
 * targets (e.g. /#download) scroll into view.
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
  { path: '/changelog', name: 'changelog', component: () => import('@/views/ChangelogView.vue') },
  { path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue') },
  { path: '/guide', name: 'guide', component: () => import('@/views/GuideView.vue') },
  { path: '/auth/result', name: 'auth-result', component: () => import('@/views/AuthResultView.vue') },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') },
]

const router = createRouter({
  history: createWebHistory('/'),
  routes,
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, top: 80, behavior: 'smooth' }
    return { top: 0 }
  },
})

export default router
