<script setup>
// 앱 껍데기. 로그인 화면은 껍데기 없이 홀로 뜨고, 나머지 화면 위에 상단 띠를 얹는다.
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, notify, session } from './api'

const route = useRoute()
const router = useRouter()

const bare = computed(() => route.name === 'login')

// Dashboard 를 보고 있으면 방 목록이 안 보인다. 그때도 스케줄 결과를 알 수 있게
// 상단 띠에 숫자를 띄운다. 대화 화면에 있을 때는 그쪽이 이미 갱신하므로 쉰다.
let timer = null
onMounted(() => {
  timer = setInterval(async () => {
    if (!session.user || route.name === 'chat') return
    try {
      const rooms = await api.listRooms()
      notify.unread = rooms.reduce((sum, r) => sum + (r.unread || 0), 0)
    } catch {
      /* 잠깐 실패해도 다음 차례에 다시 본다 */
    }
  }, 15000)
})
onUnmounted(() => clearInterval(timer))

async function logout() {
  await api.logout()
  session.user = null
  router.push({ name: 'login' })
}
</script>

<template>
  <router-view v-if="bare" />

  <div v-else class="shell">
    <header class="topbar">
      <nav>
        <router-link :to="{ name: 'chat' }">
          Chat
          <span v-if="notify.unread" class="count">{{ notify.unread }}</span>
        </router-link>
        <router-link :to="{ name: 'insights' }">Dashboard</router-link>
      </nav>
      <span class="who">
        {{ session.user?.display_name }}
        <span v-if="session.user?.is_admin" class="badge">관리자</span>
      </span>
      <button class="out" @click="logout">나가기</button>
    </header>

    <router-view class="page" />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-width: 1040px;
}
.page {
  flex: 1;
  min-height: 0;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  height: 42px;
  flex: none;
  background: var(--rail);
  color: var(--rail-text);
}
nav {
  display: flex;
  gap: 4px;
  margin-right: auto;
}
nav a {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border-radius: 7px;
  font-size: 13px;
  text-decoration: none;
  color: var(--rail-muted);
  transition:
    background 0.15s,
    color 0.15s;
}
nav a:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.06);
}
/* 지금 보고 있는 화면 */
nav a.router-link-exact-active {
  color: #fff;
  background: rgba(79, 209, 197, 0.14);
}

/* 스케줄이 남긴, 아직 안 본 결과의 수 */
.count {
  min-width: 16px;
  padding: 0 5px;
  border-radius: 20px;
  background: var(--accent-on-rail);
  color: var(--rail);
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 700;
  text-align: center;
}
.who {
  font-size: 12.5px;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 7px;
}
.badge {
  font-size: 10px;
  letter-spacing: 0.08em;
  padding: 2px 7px;
  border-radius: 20px;
  background: rgba(79, 209, 197, 0.16);
  color: var(--accent-on-rail);
}
.out {
  padding: 4px 11px;
  border: 1px solid #2c3454;
  border-radius: 6px;
  background: transparent;
  color: var(--rail-muted);
  font-size: 11.5px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}
.out:hover {
  border-color: var(--rail-muted);
  color: #fff;
}
</style>
