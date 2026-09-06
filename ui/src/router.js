// 화면이 셋(로그인 / 대화 / 현황)이라 라우터를 쓴다.
// 뒤로가기와 북마크가 되고, 로그인 확인을 한 곳에서 건다.
import { createRouter, createWebHistory } from 'vue-router'
import { api, session } from './api'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
  { path: '/', name: 'chat', component: () => import('./views/ChatView.vue') },
  { path: '/insights', name: 'insights', component: () => import('./views/InsightsView.vue') },
  // 없는 주소는 대화로 보낸다
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  // 새로고침하면 화면은 비어 있지만 쿠키는 살아 있다. 한 번 물어보고 채운다.
  if (session.user === undefined) {
    try {
      session.user = await api.me()
    } catch {
      session.user = null
    }
  }

  if (!session.user && to.name !== 'login') return { name: 'login' }
  // 이미 들어와 있는데 로그인 화면으로 오면 현황으로 보낸다. 로그인 직후와 같은 자리다.
  if (session.user && to.name === 'login') return { name: 'insights' }
  return true
})
