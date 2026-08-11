import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'Conversation', component: () => import('@/views/ConversationView.vue') },
    { path: '/models', name: 'ModelPool', component: () => import('@/views/ModelPoolView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
