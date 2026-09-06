<script setup>
// 대화 화면. 좌측 레일 = 대화 목록, 가운데 = 대화, 우측 = 호출 설정.
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, notify, streamChat } from '../api'
import AgentPanel from '../components/AgentPanel.vue'
import MessageItem from '../components/MessageItem.vue'
import RoomList from '../components/RoomList.vue'

const rooms = ref([])
const activeId = ref(null)
const room = ref(null)
const messages = ref([])
const agents = ref([])
const models = ref([])
const workflows = ref([])
const schedule = ref(null)

const input = ref('')
const sending = ref(false)
const busy = ref(false)
const error = ref('')
const scroller = ref(null)
const composer = ref(null)

// 스트리밍 중인 답변. 완료되면 messages 로 옮긴다.
const draft = ref(null)

// 주기 확인용 타이머. 화면을 떠날 때 전부 멈춘다.
const timers = []

const canSend = computed(() => activeId.value && input.value.trim() && !sending.value)
const onlineAgents = computed(() => agents.value.filter((a) => a.online))

// 빈 화면에 보여줄 질문 예시. 각 에이전트의 manifest.examples 에서 가져온다.
const examples = computed(() =>
  onlineAgents.value
    .flatMap((a) => (a.examples || []).slice(0, 2).map((text) => ({ text, agent: a.name })))
    .slice(0, 4),
)

// 이 대화에서 어떻게 호출되는지 한 줄 요약
const routeLabel = computed(() => {
  if (!room.value) return ''
  if (room.value.workflow) {
    const wf = workflows.value.find((w) => w.key === room.value.workflow)
    return `워크플로우 · ${wf ? wf.name : room.value.workflow}`
  }
  const picked = room.value.agents || []
  if (!picked.length) return '자동 선택'
  const mode = picked.length > 1 ? (room.value.mode === 'sequential' ? ' · 순차' : ' · 병렬') : ''
  return `${picked.join(', ')}${mode}`
})

// --- 초기 로딩 --------------------------------------------------------------

/** 워크플로우 목록을 다시 읽는다. 편집기에서 만들거나 지우면 곧바로 반영된다. */
async function refreshWorkflows() {
  workflows.value = (await api.listWorkflows()).workflows
}

onMounted(async () => {
  const modelInfo = await api.listModels()
  models.value = modelInfo.models
  await refreshWorkflows()
  await refreshAgents()
  await refreshRooms()
  if (rooms.value.length) await selectRoom(rooms.value[0].id)
  // 에이전트가 켜지고 꺼지는 것과 '남이 쓰는 중'을 화면에 반영한다.
  // 사용 중 표시는 늦으면 소용이 없어 짧게 잡았다. /api/agents 는 코어 메모리에서
  // 바로 답하므로(에이전트를 부르지 않는다) 4초 주기도 부담이 되지 않는다.
  timers.push(setInterval(refreshAgents, 4000))
  // 스케줄이 대신 던진 질문과 결과를 새로고침 없이 받아온다.
  timers.push(setInterval(pollMessages, 10000))
})

// 화면을 떠나면 반드시 멈춘다. 정리하지 않으면 Dashboard 로 옮겨도 계속 돌고,
// 나갈 때는 인증이 풀린 뒤에도 요청을 보내 UNAUTHORIZED 를 던진다.
// 게다가 대화 화면에 들어올 때마다 한 쌍씩 늘어난다.
onUnmounted(() => {
  timers.forEach(clearInterval)
  timers.length = 0
})

/** 대화 중이 아닐 때만, 새 메시지가 생겼으면 목록을 갱신한다. */
async function pollMessages() {
  if (sending.value) return

  // 다른 방에서 스케줄이 돌았을 수 있다. 목록을 먼저 훑어 표시를 갱신한다.
  await refreshRooms()
  if (!activeId.value) return

  const latest = await api.listMessages(activeId.value)
  if (latest.length === messages.value.length) return // 변화 없으면 화면을 건드리지 않는다
  const atBottom = isAtBottom()
  messages.value = latest
  schedule.value = await api.getSchedule(activeId.value) // 다음 실행 시각도 갱신
  if (atBottom) scrollToBottom()

  // 보고 있는 방에서 돈 것이라면 바로 읽은 것으로 친다.
  const current = rooms.value.find((r) => r.id === activeId.value)
  if (current?.unread) {
    await api.markRead(activeId.value)
    await refreshRooms()
  }
}

/** 사용자가 아래를 보고 있을 때만 자동으로 따라 내린다. */
function isAtBottom() {
  const el = scroller.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function refreshAgents(manual = false) {
  // 4초마다 도는 자동 갱신까지 busy 를 켜면 패널이 계속 깜빡인다.
  // '새로고침' 을 눌렀을 때만 표시한다.
  if (manual) busy.value = true
  try {
    agents.value = await api.listAgents()
  } finally {
    busy.value = false
  }
}

// --- 채팅방 -----------------------------------------------------------------

async function selectRoom(id) {
  // 먼저 다 받아온 뒤 한꺼번에 세운다.
  // activeId 를 먼저 세우면 방 정보가 도착하기 전에 "방은 골랐는데 내용은 없는" 상태로
  // 화면이 한 번 그려져 room.agents 를 읽다 터진다. 세 요청은 서로 무관하니 같이 보낸다.
  const [detail, msgs, sched] = await Promise.all([
    api.getRoom(id),
    api.listMessages(id),
    api.getSchedule(id),
  ])
  activeId.value = id
  room.value = detail
  messages.value = msgs
  schedule.value = sched
  draft.value = null
  scrollToBottom()

  // 열어봤으니 강조를 지운다. 목록도 같이 갱신해 색이 바로 돌아가게 한다.
  if (detail.unread) {
    await api.markRead(id)
    await refreshRooms()
  }
}

/** 방 목록을 다시 받아오고, 상단 띠가 쓸 합계도 함께 맞춘다. */
async function refreshRooms() {
  rooms.value = await api.listRooms()
  notify.unread = rooms.value.reduce((sum, r) => sum + (r.unread || 0), 0)
}

async function createRoom() {
  const created = await api.createRoom({ model: models.value[0] })
  await refreshRooms()
  await selectRoom(created.id)
  nextTick(() => composer.value?.focus())
}

async function removeRoom(id) {
  if (!confirm('이 대화를 삭제할까요? 되돌릴 수 없습니다.')) return
  await api.deleteRoom(id)
  await refreshRooms()
  if (activeId.value === id) {
    activeId.value = null
    room.value = null
    messages.value = []
  }
}

/** 대화 이름 바꾸기. 목록과 상단 제목이 같이 움직여야 한다. */
async function renameRoom(id, title) {
  try {
    const updated = await api.updateRoom(id, { title })
    await refreshRooms()
    // 보고 있는 방이면 상단 제목도 같이 고친다. 목록만 갱신하면 헤더가 옛 이름으로 남는다.
    if (activeId.value === id) room.value = updated
  } catch (e) {
    error.value = `이름을 바꾸지 못했습니다. (${e.message})`
  }
}

async function updateRoom(patch) {
  room.value = await api.updateRoom(activeId.value, patch)
  await refreshRooms()
}

// --- 스케줄 -----------------------------------------------------------------

async function saveSchedule(body) {
  try {
    schedule.value = await api.putSchedule(activeId.value, body)
    error.value = ''
  } catch (e) {
    error.value = `스케줄을 저장하지 못했습니다. cron 식을 확인하세요. (${e.message})`
  }
}

async function deleteSchedule() {
  await api.deleteSchedule(activeId.value)
  schedule.value = null
}

// --- 대화 -------------------------------------------------------------------

/** 서버가 409 로 돌려준 안내 문구를 꺼낸다. 409 가 아니면 null. */
function busyReason(e) {
  const m = /^409\s(.+)$/s.exec(e.message || '')
  if (!m) return null
  try {
    return JSON.parse(m[1]).detail
  } catch {
    return m[1]
  }
}

/** 실행 중인 질문을 중단한다. 여기까지 받은 부분 결과는 서버가 저장한다. */
async function stopRun() {
  try {
    await api.cancelRun(activeId.value)
  } catch (e) {
    error.value = `중단하지 못했습니다. (${e.message})`
  }
}

function useExample(text) {
  input.value = text
  composer.value?.focus()
}

async function send() {
  if (!canSend.value) return
  const text = input.value.trim()
  input.value = ''
  sending.value = true
  error.value = ''

  messages.value.push({ role: 'user', content_md: text, meta: {} })
  // agentOutputs: 에이전트별 진행 중인 출력. 최종 본문(content)과 섞이지 않게 따로 둔다.
  draft.value = { content: '', statuses: [], meta: { runs: [] }, agentOutputs: [], createdAt: '' }
  scrollToBottom()

  try {
    for await (const event of streamChat(activeId.value, text)) {
      applyEvent(event)
      scrollToBottom()
    }
  } catch (e) {
    // 409 는 "남이 그 에이전트를 쓰는 중" 이다. 사고가 아니라 안내이므로 그대로 보여준다.
    error.value = busyReason(e) || `응답을 받지 못했습니다. (${e.message})`
    // 서버가 거절했으면 방금 화면에 얹은 질문도 되돌린다.
    if (busyReason(e)) messages.value.pop()
  } finally {
    // 최종 결과를 대화 목록에 옮기고, 방 제목이 바뀌었을 수 있으니 목록도 갱신한다.
    if (draft.value) {
      messages.value.push({
        role: 'assistant',
        content_md: draft.value.content,
        meta: draft.value.meta,
        created_at: draft.value.createdAt,
      })
      draft.value = null
    }
    sending.value = false
    await refreshRooms()
    // 첫 질문이면 서버가 방 제목을 바꾼다. 목록만 갱신하면 상단 헤더가 옛 제목으로 남는다.
    const fresh = rooms.value.find((r) => r.id === activeId.value)
    if (fresh && room.value) room.value.title = fresh.title
    scrollToBottom()
  }
}

/** 진행 중인 에이전트 한 건의 상태를 갱신한다. 목록에 없으면 새로 만든다. */
function markRun(d, agentId, patch) {
  let run = d.meta.runs.find((r) => r.agent_id === agentId)
  if (!run) {
    run = { agent_id: agentId, state: 'pending' }
    d.meta.runs.push(run)
  }
  Object.assign(run, patch)
}

/** 이벤트 종류별 화면 반영. 계약의 status/delta/result/error 와 코어의 plan 을 다룬다. */
function applyEvent(event) {
  const d = draft.value
  if (!d) return

  if (event.type === 'plan') {
    // 계획이 오면 부를 에이전트를 먼저 늘어놓는다. 무엇이 일어날지 미리 보인다.
    d.meta.plan = { agents: event.agents, mode: event.mode, reason: event.reason }
    d.meta.runs = (event.agents || []).map((agent_id) => ({ agent_id, state: 'pending' }))
  } else if (event.type === 'status') {
    d.statuses.push({ agent: event.agent_id || '', message: event.message })
    if (event.agent_id) markRun(d, event.agent_id, { state: 'running' })
  } else if (event.type === 'delta') {
    if (event.agent_id) {
      // 에이전트 토큰은 에이전트별로 따로 모은다.
      // 병렬 호출에서 여러 에이전트의 토큰이 한 덩어리로 섞이면 읽을 수 없다.
      markRun(d, event.agent_id, { state: 'running' })
      const found = d.agentOutputs.find((o) => o.agent === event.agent_id)
      if (found) found.text += event.text
      else d.agentOutputs.push({ agent: event.agent_id, text: event.text })
    } else {
      // agent_id 가 없는 토큰 = 코디네이터가 직접 쓰는 최종 답변.
      // 이 순간 중간 출력은 역할을 마쳤다. 함께 띄워두면 같은 내용이 두 벌로 보이다가
      // 최종 결과에서 한쪽만 사라져 화면이 튄다.
      if (!d.content) d.agentOutputs = []
      d.content += event.text
    }
  } else if (event.type === 'result') {
    if (event.agent_id) {
      markRun(d, event.agent_id, {
        state: 'done',
        elapsed_ms: (event.meta || {}).elapsed_ms || 0,
        // 에이전트가 실제로 쓴 모델. .env 로 고정해 두면 방에서 고른 것과 다르다.
        // 저장된 뒤에만 보이면 스트리밍 중에는 무슨 모델로 도는지 알 수 없다.
        model: (event.meta || {}).model,
      })
    } else {
      d.content = event.markdown
      d.meta = { ...d.meta, attachments: event.attachments || [], ...(event.meta || {}) }
      d.statuses = []
      d.agentOutputs = [] // 최종 결과가 나왔으므로 중간 출력은 걷어낸다
      d.createdAt = new Date().toISOString() // 저장 전이라 화면에서 시각을 매긴다
    }
  } else if (event.type === 'error') {
    if (event.agent_id) markRun(d, event.agent_id, { state: 'error', error: event.message })
    else d.statuses.push({ agent: '', message: event.message })
  }
}

function scrollToBottom() {
  nextTick(() => {
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(activeId, () => (input.value = ''))
</script>

<template>
  <div class="app">
    <RoomList
      :rooms="rooms"
      :active-id="activeId"
      :online="onlineAgents.length"
      :total="agents.length"
      @select="selectRoom"
      @create="createRoom"
      @remove="removeRoom"
      @rename="renameRoom"
    />

    <main class="chat">
      <header v-if="room">
        <h1>{{ room.title }}</h1>
        <span class="route">{{ routeLabel }}</span>
      </header>

      <div class="scroll" ref="scroller">
        <div class="thread">
        <!-- 대화를 아직 고르지 않았을 때 -->
        <div v-if="!activeId" class="stage">
          <p class="eyebrow">시작하기</p>
          <h2>대화를 하나 만들어 주세요.</h2>
          <p class="lede">
            질문을 던지면 코디네이터가 담당 에이전트를 골라 부르고, 여러 곳에서 온 결과를 하나로
            정리해 돌려줍니다.
          </p>
          <button class="cta" @click="createRoom">새 대화 시작</button>
        </div>

        <!-- 방은 있는데 아직 아무 말도 하지 않았을 때 -->
        <div v-else-if="!messages.length && !draft" class="stage">
          <p class="eyebrow">에이전트 {{ onlineAgents.length }}개 대기 중</p>
          <h2>무엇을 확인할까요?</h2>
          <p class="lede">
            {{
              room?.agents?.length
                ? '고정해 둔 에이전트를 부릅니다. 선택을 해제하면 코디네이터가 알아서 고릅니다.'
                : '에이전트를 따로 고르지 않으면 질문에 맞는 곳으로 코디네이터가 보냅니다.'
            }}
          </p>

          <ul v-if="examples.length" class="examples">
            <li v-for="(ex, i) in examples" :key="i">
              <button @click="useExample(ex.text)">
                <span class="ex-text">{{ ex.text }}</span>
                <span class="ex-from">{{ ex.agent }}</span>
              </button>
            </li>
          </ul>
        </div>

        <MessageItem
          v-for="(m, i) in messages"
          :key="i"
          :role="m.role"
          :content="m.content_md"
          :meta="m.meta"
          :created-at="m.created_at"
        />

        <MessageItem
          v-if="draft"
          role="assistant"
          :content="draft.content"
          :meta="draft.meta"
          :statuses="draft.statuses"
          :agent-outputs="draft.agentOutputs"
          :created-at="draft.createdAt"
          streaming
        />
        </div>
      </div>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <form class="composer" @submit.prevent="send">
        <textarea
          ref="composer"
          v-model="input"
          rows="1"
          :disabled="!activeId || sending"
          placeholder="질문을 입력하세요"
          @keydown.enter.exact.prevent="send"
        ></textarea>
        <div class="tools">
          <span class="data tip">Enter 전송 · Shift+Enter 줄바꿈</span>
          <!-- 모델은 질문을 보내기 직전에 고르는 것이라 보내기 바로 옆에 둔다. -->
          <select
            class="model"
            :value="room?.model"
            :disabled="!activeId || sending"
            aria-label="모델 선택"
            @change="updateRoom({ model: $event.target.value })"
          >
            <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
          </select>
          <!-- 실행 중에는 같은 자리가 중단 버튼이 된다. 버튼을 하나 더 늘리지 않는다. -->
          <button v-if="sending" type="button" class="stop" @click="stopRun">
            <span class="spinner" aria-hidden="true"></span>
            중단
          </button>
          <button v-else type="submit" :disabled="!canSend">보내기</button>
        </div>
      </form>
    </main>

    <AgentPanel
      :agents="agents"
      :workflows="workflows"
      :room="room"
      :schedule="schedule"
      :busy="busy"
      @update-room="updateRoom"
      @refresh-agents="refreshAgents(true)"
      @refresh-workflows="refreshWorkflows"
      @save-schedule="saveSchedule"
      @delete-schedule="deleteSchedule"
    />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  /* 높이는 상단 띠를 뺀 나머지다. 셸이 flex 로 잡아주므로 100% 만 채운다. */
  height: 100%;
  min-height: 0;
}
.chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--canvas);
}

/* --- 상단 --- */
header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 15px 28px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
h1 {
  font-size: 14.5px;
  font-weight: 650;
  letter-spacing: -0.01em;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.route {
  font-size: 11.5px;
  color: var(--accent-hi);
  background: var(--accent-soft);
  padding: 2px 9px;
  border-radius: 20px;
  flex: none;
}

/* --- 대화 영역 --- */
.scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px 28px 24px;
}
/* 글줄 폭은 이 래퍼가 정하고, 좌우 정렬은 각 메시지가 스스로 정한다.
   폭 제한을 .scroll > * 에 걸면 질문 블록의 우측 정렬을 덮어쓴다. */
.thread {
  max-width: 820px;
  margin: 0 auto;
}

/* --- 빈 화면 --- */
.stage {
  padding: 76px 0 0;
  max-width: 560px;
}
.stage h2 {
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
  margin: 8px 0 10px;
}
.lede {
  color: var(--ink-500);
  font-size: 13.5px;
  margin: 0 0 22px;
  line-height: 1.7;
}
.cta {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: var(--ink-900);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.cta:hover {
  background: var(--ink-700);
}

.examples {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.examples button {
  display: flex;
  align-items: baseline;
  gap: 12px;
  width: 100%;
  text-align: left;
  padding: 11px 14px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  cursor: pointer;
  transition:
    border-color 0.15s,
    transform 0.15s;
}
.examples button:hover {
  border-color: var(--accent);
  transform: translateX(2px);
}
.ex-text {
  font-size: 13px;
  color: var(--ink-900);
  flex: 1;
}
.ex-from {
  font-size: 11px;
  color: var(--ink-400);
  flex: none;
}

/* --- 오류 --- */
.error {
  margin: 0;
  padding: 9px 28px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 12.5px;
  border-top: 1px solid #f0d3cf;
}

/* --- 입력 --- */
.composer {
  padding: 14px 28px 20px;
  background: var(--canvas);
}
.composer > * {
  max-width: 820px;
  margin: 0 auto;
}
textarea {
  display: block;
  width: 100%;
  resize: none;
  padding: 13px 16px;
  border: 1px solid var(--line-strong);
  border-bottom: none;
  border-radius: 10px 10px 0 0;
  font-size: 14px;
  line-height: 1.6;
  min-height: 52px;
  max-height: 180px;
  background: var(--surface);
}
textarea:focus {
  outline: none;
  border-color: var(--accent);
}
textarea:disabled {
  background: var(--surface-sunk);
}
.tools {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px 8px 16px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-top: 1px solid var(--line);
  border-radius: 0 0 10px 10px;
  box-shadow: var(--shadow-sm);
}
.composer:focus-within .tools,
.composer:focus-within textarea {
  border-color: var(--accent);
}
.tip {
  color: var(--ink-400);
}
/* 여기서 오른쪽으로 밀어낸다. 뒤의 보내기 버튼이 따라 붙는다. */
.model {
  margin-left: auto;
  max-width: 190px;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface);
  color: var(--ink-500);
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
}
.model:hover:not(:disabled) {
  border-color: var(--line-strong);
  color: var(--ink-900);
}
.model:disabled {
  opacity: 0.5;
  cursor: default;
}
.tools button {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 18px;
  border: none;
  border-radius: 7px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.tools button:hover:not(:disabled) {
  background: var(--accent-hi);
}
.tools button:disabled {
  background: var(--line-strong);
  cursor: default;
}
/* 중단은 파괴적인 동작이 아니라 "지금 도는 것"에 대한 조작이다.
   빨강으로 겁주지 않고 진행 중임을 나타내는 주황을 쓴다. */
.tools button.stop {
  background: var(--busy);
}
.tools button.stop:hover {
  background: #7d4405;
}
.spinner {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
