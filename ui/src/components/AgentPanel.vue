<script setup>
// 우측 작업대: 호출 가능한 에이전트(요구사항 17), 모델(18), 워크플로우(11), 스케줄(16).
//
// 에이전트가 10개, 20개로 늘어도 아래 항목이 화면 밖으로 밀려나지 않아야 한다.
// 그래서 세로를 두 덩이로 고정한다:
//   위(에이전트) = 남는 공간 전부 + 자체 스크롤 / 아래(설정) = 고정
// 아래 설정들은 접이식이고, 접힌 상태에서도 현재 값이 요약줄에 보인다.
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import InfoDialog from './InfoDialog.vue'
import WorkflowEditor from './WorkflowEditor.vue'

const props = defineProps({
  agents: { type: Array, default: () => [] },
  workflows: { type: Array, default: () => [] },
  room: { type: Object, default: null },
  schedule: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits([
  'update-room',
  'refresh-agents',
  'refresh-workflows',
  'save-schedule',
  'delete-schedule',
])

const selected = computed(() => props.room?.agents || [])
const isSequential = computed(() => props.room?.mode === 'sequential' && selected.value.length > 1)

/** 이 에이전트가 몇 번째로 도는지. 안 골랐으면 0. */
function stepNo(id) {
  return selected.value.indexOf(id) + 1
}

/** 에이전트 id 를 화면에 보이는 이름으로. 없으면 id 를 그대로 쓴다. */
function agentName(id) {
  return props.agents.find((a) => a.id === id)?.name || id
}

/** 호출 순서를 한 칸 옮긴다. 보낸 배열 순서가 곧 실행 순서로 저장된다. */
function move(index, delta) {
  const next = [...selected.value]
  const target = index + delta
  if (target < 0 || target >= next.length) return
  ;[next[index], next[target]] = [next[target], next[index]]
  emit('update-room', { agents: next })
}
const usingWorkflow = computed(() => !!props.room?.workflow)

// 지금 열려 있는 설명 창. null 이면 닫힌 상태.
// 설명을 패널에 작은 글씨로 늘어놓으면 매번 눈에 걸리기만 하고 정작 안 읽힌다.
const dialog = ref(null)
// 설명을 펼쳐 보고 있는 에이전트. null 이면 닫힌 상태.
const detail = ref(null)

/** 몇 초째 잡고 있는지. 기다릴지 말지 판단하려면 초보다 분이 읽기 쉽다. */
function elapsed(sec) {
  if (sec < 60) return `${sec}초째`
  return `${Math.floor(sec / 60)}분 ${sec % 60}초째`
}

// 목록이 길어지면 눈으로 찾기 어렵다. 이름·id·설명·태그로 걸러낸다.
const keyword = ref('')
const visibleAgents = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return props.agents
  return props.agents.filter((a) =>
    [a.name, a.id, a.description, ...(a.tags || [])].join(' ').toLowerCase().includes(k),
  )
})

// 접힌 상태에서도 무엇이 설정되어 있는지 보이게 한다.
const modeLabel = computed(() => (props.room?.mode === 'sequential' ? '순차' : '병렬'))
const workflowLabel = computed(() => {
  if (!props.room?.workflow) return '사용 안 함'
  const wf = props.workflows.find((w) => w.key === props.room.workflow)
  return wf ? wf.name : props.room.workflow
})
const scheduleLabel = computed(() => (props.schedule ? props.schedule.cron : '없음'))

// 스케줄 입력값은 화면 안에서만 들고 있다가 저장할 때 한 번에 올려보낸다.
const cron = ref('')
const prompt = ref('')
watch(
  () => props.schedule,
  (s) => {
    cron.value = s?.cron || ''
    prompt.value = s?.prompt || ''
  },
  { immediate: true },
)

// 자주 쓰는 주기. cron 을 외우지 않아도 되게 한 번 눌러 채운다.
const PRESETS = [
  { label: '30분마다', expr: '*/30 * * * *' },
  { label: '1시간마다', expr: '0 * * * *' },
  { label: '3시간마다', expr: '0 */3 * * *' },
  { label: '매일 09시', expr: '0 9 * * *' },
  { label: '평일 09시', expr: '0 9 * * 1-5' },
  { label: '평일 2시간마다', expr: '0 9-18/2 * * 1-5' },
]

// "3시간마다" 를 글로 설명하는 것보다 실제 실행 시각을 보여주는 편이 오해가 없다.
const preview = ref(null)
let previewTimer = null
let previewSeq = 0 // 요청 순번. 늦게 도착한 옛 응답이 최신 결과를 덮어쓰지 않게 한다
watch(cron, (expr) => {
  clearTimeout(previewTimer)
  if (!expr.trim()) {
    preview.value = null
    return
  }
  const seq = ++previewSeq
  // 타이핑이 멈춘 뒤에 한 번만 물어본다.
  previewTimer = setTimeout(async () => {
    let result = null
    try {
      result = await api.previewCron(expr.trim())
    } catch {
      result = null
    }
    if (seq === previewSeq) preview.value = result // 최신 요청의 응답만 반영
  }, 350)
})

function toggleAgent(id) {
  const next = selected.value.includes(id)
    ? selected.value.filter((a) => a !== id)
    : [...selected.value, id]
  emit('update-room', { agents: next })
}

// 이름 첫 글자를 아이콘 대신 쓴다. 별도 이미지가 없어도 목록에서 구분된다.
function initial(agent) {
  return (agent.name || agent.id).trim().charAt(0)
}
</script>

<template>
  <aside class="bench">
    <div v-if="!room" class="empty">
      <p>대화를 선택하면<br />호출 설정이 여기에 표시됩니다.</p>
    </div>

    <template v-else>
      <!-- 위: 에이전트 (남는 공간을 다 쓰고 여기서만 스크롤한다)
           모델 선택은 입력창 옆으로 옮겼다. 질문을 보내기 직전에 고르는 것이 자연스럽다. -->
      <div class="mid">
        <p class="eyebrow row">
          <span>에이전트 <b v-if="selected.length">{{ selected.length }} 선택</b></span>
          <span class="tools">
            <button class="help" aria-label="에이전트 설명" @click="dialog = 'agents'">?</button>
            <button class="ghost" :disabled="busy" @click="emit('refresh-agents')">새로고침</button>
          </span>
        </p>

        <input
          v-if="agents.length > 5"
          class="search"
          type="search"
          placeholder="이름·설명으로 찾기"
          v-model="keyword"
        />

        <!-- 지금 상태를 알리는 문구만 남긴다. 개념 설명은 물음표 안으로 옮겼다. -->
        <p v-if="usingWorkflow" class="hint warn">
          워크플로우를 쓰는 중이라 선택이 적용되지 않습니다.
        </p>
        <p v-else-if="!selected.length" class="hint">코디네이터가 알아서 고릅니다.</p>

        <ul class="agents">
          <li v-for="a in visibleAgents" :key="a.id">
            <label :class="{ off: !a.online, busy: a.busy, on: selected.includes(a.id) }">
              <input
                type="checkbox"
                :checked="selected.includes(a.id)"
                :disabled="!a.online || a.busy || usingWorkflow"
                @change="toggleAgent(a.id)"
              />
              <span class="avatar" :class="{ live: a.online, working: a.busy }">
                <!-- 순차일 때는 몇 번째로 도는지가 이름보다 중요하다 -->
                {{ isSequential && stepNo(a.id) ? stepNo(a.id) : initial(a) }}
              </span>
              <!-- 목록에는 이름과 지금 상태만 둔다.
                   설명을 두 줄로 잘라 넣으면 어느 쪽도 제대로 읽히지 않는다. -->
              <span class="info">
                <span class="top-line">
                  <span class="name">{{ a.name }}</span>
                  <span class="data id">{{ a.id }}</span>
                </span>
                <span v-if="a.contract_mismatch" class="flag">계약 버전이 다릅니다</span>
                <span v-else-if="!a.online" class="flag muted">응답 없음</span>
                <span v-else-if="a.busy" class="flag working">
                  {{ a.busy_by }} 사용 중 · {{ elapsed(a.busy_seconds) }}
                </span>
              </span>
              <button
                class="more"
                title="에이전트 설명 보기"
                aria-label="에이전트 설명 보기"
                @click.stop.prevent="detail = a"
              >
                ?
              </button>
            </label>
          </li>
        </ul>

        <p v-if="!agents.length" class="hint">registry.yaml 에 등록된 에이전트가 없습니다.</p>
        <p v-else-if="!visibleAgents.length" class="hint">'{{ keyword }}' 와 맞는 에이전트가 없습니다.</p>
      </div>

      <!-- 아래: 설정 (접혀 있어도 현재 값이 보인다) -->
      <div class="bottom">
        <details v-if="selected.length > 1 && !usingWorkflow">
          <summary>실행 방식 <span class="val">{{ modeLabel }}</span></summary>
          <div class="body">
            <div class="modes">
              <button
                :class="{ picked: room.mode === 'parallel' }"
                @click="emit('update-room', { mode: 'parallel' })"
              >
                <span class="mname">병렬</span>
                <span class="mdesc">동시에 부르고 결과를 합칩니다</span>
              </button>
              <button
                :class="{ picked: room.mode === 'sequential' }"
                @click="emit('update-room', { mode: 'sequential' })"
              >
                <span class="mname">순차</span>
                <span class="mdesc">앞 결과를 다음 에이전트에 넘깁니다</span>
              </button>
            </div>

            <!-- 순차는 순서가 곧 동작이다. 보이지 않으면 어떤 게 먼저인지 알 수 없다. -->
            <template v-if="isSequential">
              <p class="label">호출 순서</p>
              <ol class="order">
                <li v-for="(id, i) in selected" :key="id">
                  <span class="no data">{{ i + 1 }}</span>
                  <span class="nm">{{ agentName(id) }}</span>
                  <button :disabled="i === 0" title="위로" @click="move(i, -1)">↑</button>
                  <button
                    :disabled="i === selected.length - 1"
                    title="아래로"
                    @click="move(i, 1)"
                  >
                    ↓
                  </button>
                </li>
              </ol>
            </template>
          </div>
        </details>

        <details>
          <summary>워크플로우 <span class="val">{{ workflowLabel }}</span></summary>
          <div class="body">
            <select
              :value="room.workflow || ''"
              @change="emit('update-room', { workflow: $event.target.value })"
            >
              <option value="">사용 안 함</option>
              <option v-for="w in workflows" :key="w.key" :value="w.key">{{ w.name }}</option>
            </select>
            <button class="link" @click="dialog = 'workflow'">
              워크플로우 관리 (내용 보기 · 만들기 · 고치기)
            </button>
          </div>
        </details>

        <details>
          <summary>스케줄 <span class="val">{{ scheduleLabel }}</span></summary>
          <div class="body">
            <div class="presets">
              <button
                v-for="p in PRESETS"
                :key="p.expr"
                :class="{ picked: cron.trim() === p.expr }"
                @click="cron = p.expr"
              >
                {{ p.label }}
              </button>
            </div>

            <input class="data cron" placeholder="0 9 * * 1-5" v-model="cron" />

            <p v-if="preview && preview.valid" class="preview">
              실행 시각
              <span v-for="t in preview.next" :key="t" class="data slot">{{ t }}</span>
            </p>
            <p v-else-if="preview" class="preview bad">cron 식을 읽을 수 없습니다</p>
            <textarea rows="2" placeholder="예약 시각에 던질 질문" v-model="prompt"></textarea>
            <div class="row gap">
              <button
                class="solid"
                :disabled="!cron.trim() || !prompt.trim()"
                @click="emit('save-schedule', { cron, prompt, enabled: true })"
              >
                {{ schedule ? '스케줄 변경' : '스케줄 저장' }}
              </button>
              <button v-if="schedule" class="ghost danger" @click="emit('delete-schedule')">
                삭제
              </button>
            </div>
            <p v-if="schedule?.next_run_at" class="next">
              다음 실행
              <span class="data">{{ schedule.next_run_at.slice(0, 16).replace('T', ' ') }}</span>
            </p>
            <button class="link" @click="dialog = 'schedule'">cron 쓰는 법</button>
          </div>
        </details>
      </div>
    </template>

    <!-- 에이전트 한 개의 전체 설명. 목록에서는 이름만 보이므로 여기서 다 보여준다. -->
    <InfoDialog
      :open="!!detail"
      :title="detail ? detail.name : ''"
      @close="detail = null"
    >
      <template v-if="detail">
        <p class="meta">
          <span class="data tag">{{ detail.id }}</span>
          <span class="data tag" :class="detail.busy ? 'busy' : detail.online ? 'on' : ''">
            {{ detail.busy ? `${detail.busy_by} 사용 중` : detail.online ? '온라인' : '응답 없음' }}
          </span>
          <span v-if="detail.model" class="data tag">{{ detail.model }} 고정</span>
        </p>

        <p class="label">하는 일</p>
        <p class="full-desc">{{ detail.description || '설명이 없습니다.' }}</p>

        <template v-if="detail.examples?.length">
          <p class="label">이런 질문에 부릅니다</p>
          <ul class="samples">
            <li v-for="ex in detail.examples" :key="ex">{{ ex }}</li>
          </ul>
        </template>

        <dl class="facts">
          <dt>담당자</dt>
          <dd>{{ detail.owner || '미지정' }}</dd>
          <dt>주소</dt>
          <dd class="data">{{ detail.url }}</dd>
          <template v-if="detail.tags?.length">
            <dt>태그</dt>
            <dd>{{ detail.tags.join(', ') }}</dd>
          </template>
        </dl>

        <p v-if="detail.contract_mismatch" class="warn-note">
          이 에이전트는 오래된 계약으로 만들어졌습니다. 부를 수는 있지만 동작을 보장하지
          않으니 담당자에게 알려주세요.
        </p>
        <p v-else-if="detail.error" class="warn-note">{{ detail.error }}</p>
      </template>
    </InfoDialog>

    <!-- 설명 창들. 패널에는 지금 상태만 두고 개념 설명은 여기로 모았다. -->
    <InfoDialog :open="dialog === 'agents'" title="에이전트 고르기" @close="dialog = null">
      <p>
        <b>고르지 않으면</b> 코디네이터가 질문을 읽고 알맞은 에이전트를 스스로 고릅니다.
        평소에는 이대로 두는 편이 편합니다.
      </p>
      <p>
        <b>직접 고르면</b> 그 에이전트만 부릅니다. 두 개 이상 고르면 아래 <b>실행 방식</b>에서
        동시에 부를지(병렬) 앞 결과를 넘겨줄지(순차) 정할 수 있습니다.
      </p>
      <dl>
        <dt><span class="dot on"></span> 초록 점</dt>
        <dd>지금 응답하는 에이전트입니다.</dd>
        <dt><span class="dot working"></span> 주황 점</dt>
        <dd>
          지금 다른 사람이 쓰고 있습니다. 로컬 모델은 동시에 부르면 서로 느려지므로
          끝날 때까지 고를 수 없습니다.
        </dd>
        <dt><span class="dot"></span> 회색 점</dt>
        <dd>담당자의 노트북이 꺼져 있거나 방화벽에 막혀 있습니다. 고를 수 없습니다.</dd>
        <dt><span class="data">모델 고정</span></dt>
        <dd>
          그 에이전트가 자기 설정으로 모델을 못 박아 두었습니다. 화면에서 다른 모델을
          골라도 그 에이전트만은 표시된 모델로 돕니다. 담당자 노트북에 그 모델만
          있을 때 이렇게 해둡니다.
        </dd>
        <dt class="warn">계약 버전이 다릅니다</dt>
        <dd>
          그 에이전트가 오래된 규약으로 만들어졌습니다. 부를 수는 있지만 동작을 보장하지
          않으니 담당자에게 알려주세요.
        </dd>
      </dl>
    </InfoDialog>

    <!-- 워크플로우는 원문을 보고 그 자리에서 만들고 고친다. -->
    <WorkflowEditor
      :open="dialog === 'workflow'"
      @close="dialog = null"
      @changed="emit('refresh-workflows')"
    />

    <InfoDialog :open="dialog === 'schedule'" title="cron 쓰는 법" @close="dialog = null">
      <p>
        정해진 시각에 저장해 둔 질문을 대신 던집니다. <b>대화방마다 하나만</b> 걸 수 있고,
        새로 저장하면 기존 것을 대신합니다.
      </p>

      <pre class="cron-sample">분  시  일  월  요일
0   9   *   *   1-5   ← 평일 오전 9시</pre>

      <p class="warn-note">
        <b>맨 앞이 '분' 입니다.</b> <span class="data">*/3 * * * *</span> 는 3시간이 아니라
        3분마다입니다. n시간마다는 시(時) 칸에 넣고 분을 고정하세요.
      </p>

      <table class="ref">
        <tbody>
          <tr><td class="data">*</td><td>매번</td></tr>
          <tr><td class="data">*/n</td><td>n칸마다</td></tr>
          <tr><td class="data">a-b</td><td>a 부터 b 까지</td></tr>
          <tr><td class="data">a-b/n</td><td>그 범위에서 n칸마다</td></tr>
          <tr><td class="data">a,b,c</td><td>나열한 것만</td></tr>
        </tbody>
      </table>
      <p class="note">요일은 0(일)부터 6(토)까지입니다.</p>

      <p class="label">자주 쓰는 것</p>
      <table class="ref">
        <tbody>
          <tr><td>30분마다</td><td class="data">*/30 * * * *</td></tr>
          <tr><td>3시간마다</td><td class="data">0 */3 * * *</td></tr>
          <tr><td>매일 오전 9시</td><td class="data">0 9 * * *</td></tr>
          <tr><td>평일 오전 9시</td><td class="data">0 9 * * 1-5</td></tr>
          <tr><td>평일 2시간마다</td><td class="data">0 9-18/2 * * 1-5</td></tr>
          <tr><td>매주 월요일 8시</td><td class="data">0 8 * * 1</td></tr>
        </tbody>
      </table>

      <p class="note">
        입력하는 동안 실제 실행 시각이 아래에 미리 나옵니다. 그것으로 확인하는 편이 가장 확실합니다.
      </p>
    </InfoDialog>
  </aside>
</template>

<style scoped>
.bench {
  width: 316px;
  flex: none;
  border-left: 1px solid var(--line);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  min-height: 0; /* 자식이 넘칠 때 스크롤이 생기게 한다 */
}

/* --- 위: 에이전트. 남는 공간을 다 쓰고 여기서만 스크롤한다 --- */
.mid {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px 16px 8px;
}
.agents {
  list-style: none;
  margin: 0;
  padding: 0 2px 8px 0; /* 스크롤바와 카드 사이 여백 */
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

/* --- 아래: 설정. 접이식이라 항상 자리를 지킨다 --- */
.bottom {
  flex: none;
  border-top: 1px solid var(--line);
  background: var(--surface-sunk);
}
details {
  border-bottom: 1px solid var(--line);
}
details:last-child {
  border-bottom: none;
}
summary {
  padding: 10px 16px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-700);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  list-style: none;
}
summary::-webkit-details-marker {
  display: none;
}
/* 펼침 표시를 직접 그린다 */
summary::after {
  content: '';
  width: 5px;
  height: 5px;
  border-right: 1.5px solid var(--ink-300);
  border-bottom: 1.5px solid var(--ink-300);
  transform: rotate(45deg) translate(-1px, -1px);
  transition: transform 0.15s ease;
  flex: none;
  order: 3;
}
details[open] summary::after {
  transform: rotate(-135deg) translate(-1px, -1px);
}
summary:hover {
  background: #eef1f6;
}
.val {
  margin-left: auto;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--ink-400);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
details .body {
  padding: 2px 16px 14px;
}

/* --- 공통 입력 --- */
.eyebrow {
  margin: 0 0 8px;
}
.eyebrow.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex: none;
}
.eyebrow b {
  color: var(--accent-hi);
  font-weight: 700;
}
.hint {
  font-size: 11.5px;
  color: var(--ink-400);
  margin: 0 0 10px;
  line-height: 1.55;
  flex: none;
}
.hint.warn {
  color: var(--accent-hi);
}

select,
input.cron,
input.search,
textarea {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 7px;
  font-size: 13px;
  background: var(--surface);
  color: var(--ink-900);
}
select:hover,
input:hover,
textarea:hover {
  border-color: var(--line-strong);
}
input.search {
  margin-bottom: 10px;
  flex: none;
}
textarea {
  resize: vertical;
  font-family: var(--sans);
  margin-bottom: 8px;
}
input.cron {
  font-size: 12.5px;
  margin-bottom: 4px;
}
.legend {
  margin: 0 0 8px;
  color: var(--ink-400);
  padding-left: 2px;
}
.legend .sep {
  margin: 0 6px;
  color: var(--line-strong);
}

/* --- 스케줄 프리셋 --- */
.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.presets button {
  font-size: 11px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--surface);
  color: var(--ink-500);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s,
    color 0.15s;
}
.presets button:hover {
  border-color: var(--line-strong);
  color: var(--ink-900);
}
.presets button.picked {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-hi);
  font-weight: 600;
}

/* --- 실행 시각 미리보기 --- */
.preview {
  margin: 0 0 10px;
  font-size: 11px;
  color: var(--ink-400);
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
}
.preview .slot {
  color: var(--ink-700);
  background: var(--surface-sunk);
  border-radius: 4px;
  padding: 1px 6px;
}
.preview.bad {
  color: var(--danger);
}

/* --- 에이전트 카드 --- */
.agents label {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.agents label:hover {
  border-color: var(--line-strong);
}
.agents label.on {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.agents label.off {
  opacity: 0.72;
  cursor: default;
}
.agents input {
  margin: 3px 0 0;
  accent-color: var(--accent);
  flex: none;
}

.avatar {
  width: 26px;
  height: 26px;
  flex: none;
  border-radius: 7px;
  background: var(--surface-sunk);
  color: var(--ink-400);
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
  position: relative;
}
.avatar.live {
  background: var(--ink-900);
  color: #fff;
}
/* 온라인 표시는 아바타 모서리의 작은 점으로 */
.avatar.live::after {
  content: '';
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent-on-rail);
  border: 2px solid var(--surface);
}
/* 남이 쓰는 중 - 초록이 아니라 주황이다 */
.avatar.working::after {
  background: var(--busy-dot);
}
.flag.working {
  color: var(--busy);
}
/* 목록의 물음표. 평소엔 흐리게 두고 그 줄에 마우스를 올리면 또렷해진다. */
.more {
  flex: none;
  align-self: flex-start;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  background: var(--surface);
  color: var(--ink-400);
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.55;
  transition: opacity 0.12s;
}
li:hover .more,
.more:focus-visible {
  opacity: 1;
}
.more:hover {
  border-color: var(--accent);
  color: var(--accent-hi);
}

.order {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
}
.order li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0;
}
.order .no {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent-hi);
  display: grid;
  place-items: center;
  font-size: 10px;
  flex: none;
}
.order .nm {
  flex: 1;
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.order button {
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 6px;
  width: 22px;
  height: 22px;
  font-size: 11px;
  color: var(--ink-500);
  cursor: pointer;
  flex: none;
}
.order button:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent-hi);
}
.order button:disabled {
  color: var(--ink-300);
  cursor: default;
}

/* 이미 골라둔 에이전트가 사용 중이 되면, 고른 표시(틸)보다 사용 중(주황)이 앞선다.
   지금 부를 수 없다는 사실이 골라뒀다는 사실보다 중요하다. */
.agents label.busy,
.agents label.on.busy {
  border-color: var(--busy-dot);
  background: var(--busy-soft);
  cursor: default;
}
.agents label.busy .name {
  color: var(--ink-500);
}

.info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.top-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.name {
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.id {
  color: var(--ink-400);
  flex: none;
}
.flag {
  font-size: 11px;
  color: var(--danger);
}
.flag.muted {
  color: var(--ink-400);
}

/* --- 실행 방식 --- */
.modes {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.modes button {
  display: flex;
  flex-direction: column;
  gap: 1px;
  text-align: left;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.modes button:hover {
  border-color: var(--line-strong);
}
.modes button.picked {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.mname {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-900);
}
.mdesc {
  font-size: 11px;
  color: var(--ink-400);
}

/* --- 버튼 --- */
.row.gap {
  display: flex;
  gap: 6px;
}
.solid {
  flex: 1;
  padding: 8px 12px;
  border: none;
  border-radius: 7px;
  background: var(--accent);
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.solid:hover:not(:disabled) {
  background: var(--accent-hi);
}
.solid:disabled {
  background: var(--line-strong);
  cursor: default;
}
.ghost {
  padding: 5px 11px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink-500);
  font-size: 11.5px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}
.ghost:hover:not(:disabled) {
  border-color: var(--ink-400);
  color: var(--ink-900);
}
.ghost.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}

.next {
  margin: 10px 0 0;
  font-size: 11.5px;
  color: var(--ink-400);
}

/* --- 설명 창을 여는 것들 --- */
.tools {
  display: flex;
  align-items: center;
  gap: 5px;
}
.help {
  width: 18px;
  height: 18px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface);
  color: var(--ink-400);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}
.help:hover {
  border-color: var(--accent);
  color: var(--accent-hi);
}
/* 본문 흐름 안에 놓이는 글자 링크 */
.link {
  margin-top: 8px;
  padding: 0;
  border: none;
  background: none;
  color: var(--ink-400);
  font-size: 11.5px;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
  text-decoration-color: var(--line-strong);
}
.link:hover {
  color: var(--accent-hi);
  text-decoration-color: currentColor;
}

/* --- 설명 창 안쪽 --- */
:deep(.body p) {
  margin: 0 0 12px;
}
:deep(.body p:last-child) {
  margin-bottom: 0;
}
:deep(.body b) {
  font-weight: 650;
  color: var(--ink-900);
}
:deep(.body .label) {
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-400);
  margin: 18px 0 8px;
}
:deep(.body .full-desc) {
  white-space: pre-line; /* manifest 의 줄바꿈을 그대로 살린다 */
  margin: 0 0 4px;
}
:deep(.body .meta) {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 14px;
}
:deep(.body .tag) {
  padding: 2px 8px;
  border-radius: 20px;
  background: var(--surface-sunk);
  color: var(--ink-500);
}
:deep(.body .tag.on) {
  background: var(--accent-soft);
  color: var(--accent-hi);
}
:deep(.body .tag.busy) {
  background: var(--busy-soft);
  color: var(--busy);
}
:deep(.body .samples) {
  margin: 0;
  padding-left: 18px;
}
:deep(.body .samples li) {
  margin-bottom: 3px;
}
:deep(.body .facts) {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 4px 10px;
  margin: 16px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
}
:deep(.body .facts dt) {
  color: var(--ink-400);
  font-weight: 400;
}
:deep(.body .facts dd) {
  margin: 0;
  color: var(--ink-700);
  overflow-wrap: anywhere;
}

:deep(.body .note) {
  font-size: 11.5px;
  color: var(--ink-400);
}
:deep(.body .warn-note) {
  font-size: 11.5px;
  background: var(--accent-soft);
  color: var(--accent-hi);
  border-radius: 8px;
  padding: 9px 12px;
}
:deep(.body dl) {
  margin: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  align-items: baseline;
}
:deep(.body dt) {
  font-size: 11.5px;
  color: var(--ink-500);
  white-space: nowrap;
}
:deep(.body dt.warn) {
  color: var(--danger);
}
:deep(.body dd) {
  margin: 0;
  font-size: 11.5px;
  color: var(--ink-400);
}
:deep(.body dt .dot) {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-300);
  margin-right: 4px;
}
:deep(.body dt .dot.on) {
  background: var(--accent);
}
:deep(.body dt .dot.working) {
  background: var(--busy-dot);
}

/* 워크플로우 단계 */
:deep(.body .cron-sample) {
  margin: 0 0 12px;
  padding: 11px 13px;
  background: var(--ink-900);
  color: #e6e9f2;
  border-radius: 8px;
  font-family: var(--mono);
  font-size: 11.5px;
  line-height: 1.7;
  overflow-x: auto;
}
:deep(.body table.ref) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 12px;
}
:deep(.body table.ref td) {
  padding: 4px 0;
  font-size: 11.5px;
  border-bottom: 1px solid var(--line);
}
:deep(.body table.ref tr:last-child td) {
  border-bottom: none;
}
:deep(.body table.ref td:last-child) {
  text-align: right;
  color: var(--ink-500);
}
.next .data {
  color: var(--ink-700);
}

.empty {
  color: var(--ink-400);
  font-size: 12.5px;
  line-height: 1.7;
  padding: 40px 16px 0;
  text-align: center;
}
</style>
