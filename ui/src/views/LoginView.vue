<script setup>
// 이름만 받는다. 비밀번호가 없으므로 이건 인증이 아니라 신원 표시다.
// 처음 보는 이름을 넣으면 그 자리에서 계정이 만들어진다.
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, session } from '../api'

const router = useRouter()
const users = ref([])
const name = ref('')
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    users.value = await api.listUsers()
  } catch {
    users.value = [] // 코어가 아직 안 떴을 수도 있다. 직접 입력하면 된다.
  }
})

async function enter(username) {
  const value = (username ?? name.value).trim()
  if (!value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { user } = await api.login(value)
    session.user = user
    // 들어오자마자 전체 현황을 먼저 보여준다. 자리를 비운 사이 스케줄이 남긴 결과가
    // 어느 방에 쌓였는지도 여기서 한눈에 보인다.
    router.push({ name: 'insights' })
  } catch (e) {
    error.value = `들어갈 수 없습니다. ${e.message}`
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="gate">
    <div class="card">
      <p class="eyebrow">에이전트 허브</p>
      <h1>Login</h1>
      <p class="lede">
        이름을 넣으면 바로 들어갑니다. 처음이면 그 자리에서 계정이 만들어집니다.
      </p>

      <form @submit.prevent="enter()">
        <input
          v-model="name"
          type="text"
          maxlength="50"
          placeholder="이름"
          autofocus
          :disabled="busy"
        />
        <button type="submit" :disabled="!name.trim() || busy">
          {{ busy ? '들어가는 중' : '들어가기' }}
        </button>
      </form>

      <p v-if="error" class="error">{{ error }}</p>

      <template v-if="users.length">
        <p class="eyebrow sub">이미 쓰던 사람</p>
        <ul class="people">
          <li v-for="u in users" :key="u.username">
            <button :disabled="busy" @click="enter(u.username)">
              <span class="initial">{{ u.display_name.charAt(0) }}</span>
              {{ u.display_name }}
            </button>
          </li>
        </ul>
      </template>

      <p class="note">
        비밀번호를 받지 않습니다. 사내망 안에서만 쓰는 도구이고, 이름은 누가 무엇을 했는지
        구분하는 용도입니다.
      </p>
    </div>
  </div>
</template>

<style scoped>
.gate {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: var(--rail);
  padding: 24px;
}
.card {
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border-radius: 14px;
  padding: 32px 32px 26px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.28);
}
h1 {
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
  margin: 8px 0 10px;
}
.lede {
  color: var(--ink-500);
  font-size: 13.5px;
  line-height: 1.7;
  margin: 0 0 20px;
}

form {
  display: flex;
  gap: 8px;
}
input {
  flex: 1;
  padding: 11px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  font-size: 14px;
}
input:focus {
  outline: none;
  border-color: var(--accent);
}
form button {
  padding: 0 20px;
  border: none;
  border-radius: 9px;
  background: var(--accent);
  color: #fff;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
form button:hover:not(:disabled) {
  background: var(--accent-hi);
}
form button:disabled {
  background: var(--line-strong);
  cursor: default;
}

.error {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--danger);
}

.eyebrow.sub {
  margin: 26px 0 10px;
}
.people {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.people button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 13px 6px 6px;
  border: 1px solid var(--line);
  border-radius: 22px;
  background: var(--surface);
  font-size: 13px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.people button:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.initial {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--ink-900);
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
}

.note {
  margin: 26px 0 0;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  color: var(--ink-400);
  line-height: 1.65;
}
</style>
