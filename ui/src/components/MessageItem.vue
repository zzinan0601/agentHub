<script setup>
// 메시지 한 개. 답변은 Markdown 으로 렌더하고 원문 그대로 복사할 수 있다. (요구사항 19)
import { computed, ref } from 'vue'
import { renderMarkdown } from '../markdown'
import RunTrace from './RunTrace.vue'

const props = defineProps({
  role: { type: String, required: true },
  content: { type: String, default: '' },
  meta: { type: Object, default: () => ({}) },
  streaming: { type: Boolean, default: false },
  statuses: { type: Array, default: () => [] }, // 진행 중인 에이전트 상태
  agentOutputs: { type: Array, default: () => [] }, // 에이전트별 중간 출력
  createdAt: { type: String, default: '' }, // 응답 시각 (ISO)
})

const copied = ref(false)
const isUser = computed(() => props.role === 'user')
const isSchedule = computed(() => props.role === 'schedule')
// 사람이 쓴 것도 에이전트가 만든 것도 아닌, 시스템이 남긴 한 줄 (예: 스케줄 건너뜀)
const isNotice = computed(() => props.role === 'system')
const html = computed(() => renderMarkdown(props.content))

// 트레이스에 넘길 형태로 정리한다. 스트리밍 중이든 저장된 대화든 모양이 같다.
const runs = computed(() =>
  (props.meta?.runs || []).map((r) => ({
    agent: r.agent_id || r.agent,
    state: r.state || (r.status === 'error' ? 'error' : 'done'),
    ms: r.elapsed_ms || r.ms || 0,
    model: r.model,
    error: r.error,
  })),
)

// 본문에 이미 삽입된 이미지는 아래 목록에서 뺀다. (같은 그림이 두 번 나오지 않게)
const attachments = computed(() =>
  (props.meta?.attachments || []).filter((a) => !props.content.includes(a.url)),
)

const lastStatus = computed(() => props.statuses[props.statuses.length - 1] || null)

// 시각은 본문이 아니라 카드 구석에 작게 둔다. 같은 날이면 시:분만 보여준다.
const timeText = computed(() => {
  if (!props.createdAt) return ''
  const d = new Date(props.createdAt)
  if (Number.isNaN(d.getTime())) return ''
  const hm = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
  const today = new Date().toDateString() === d.toDateString()
  return today ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
})
const timeFull = computed(() =>
  props.createdAt ? new Date(props.createdAt).toLocaleString('ko-KR') : '',
)

async function copy() {
  await navigator.clipboard.writeText(props.content)
  copied.value = true
  setTimeout(() => (copied.value = false), 1600)
}

function sizeText(bytes) {
  if (!bytes) return ''
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}
</script>

<template>
  <!-- 시스템 안내: 답변 카드가 아니라 조용한 한 줄로 둔다 -->
  <p v-if="isNotice" class="notice">
    <span class="mark" aria-hidden="true"></span>
    {{ content }}
    <span v-if="timeText" class="data time" :title="timeFull">{{ timeText }}</span>
  </p>

  <!-- 질문: 오른쪽으로 붙은 담백한 블록 -->
  <div v-else-if="isUser" class="ask" :class="{ auto: meta?.scheduled }">
    <span v-if="meta?.scheduled" class="by">예약</span>
    <p>{{ content }}</p>
  </div>

  <!-- 답변 -->
  <article v-else class="reply" :class="{ scheduled: isSchedule }">
    <header>
      <span class="who">{{ isSchedule ? '예약 실행' : '코디네이터' }}</span>
      <span v-if="meta?.cancelled" class="stopped">중단됨</span>
      <span v-if="meta?.model" class="data model">{{ meta.model }}</span>
      <span v-if="timeText" class="data time" :title="timeFull">{{ timeText }}</span>
      <button v-if="content" class="copy" @click="copy">
        {{ copied ? '복사함' : '복사' }}
      </button>
    </header>

    <RunTrace
      v-if="runs.length"
      :mode="meta?.plan?.mode"
      :runs="runs"
      :reason="meta?.plan?.reason || ''"
      :timings="meta?.timings || {}"
      :model="meta?.model || ''"
      :live="streaming"
    />

    <!-- 아직 어느 에이전트도 응답하지 않은 구간 -->
    <p v-if="streaming && !runs.length && lastStatus" class="thinking">
      <span class="spark" aria-hidden="true"></span>
      {{ lastStatus.message }}
    </p>

    <!-- 에이전트가 만드는 중인 원문. 최종 답변이 오면 사라진다. -->
    <div v-if="agentOutputs.length" class="drafts">
      <section v-for="o in agentOutputs" :key="o.agent">
        <span class="data draft-name">{{ o.agent }}</span>
        <pre>{{ o.text }}</pre>
      </section>
    </div>

    <div v-if="content" class="md" v-html="html"></div>
    <span v-if="streaming && content" class="caret" aria-hidden="true"></span>

    <!-- 본문에서 참조하지 않은 첨부는 내려받기 링크로 -->
    <div v-if="attachments.length" class="files">
      <a v-for="a in attachments" :key="a.url" :href="a.url" :download="a.name" class="file">
        <span class="ext data">{{ (a.name.split('.').pop() || '?').slice(0, 4) }}</span>
        <span class="fname">{{ a.name }}</span>
        <span class="data fsize">{{ sizeText(a.size) }}</span>
      </a>
    </div>
  </article>
</template>

<style scoped>
/* --- 시스템 안내 --- */
.notice {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 0;
  padding: 9px 13px;
  border-radius: 8px;
  background: var(--busy-soft);
  color: var(--busy);
  font-size: 12.5px;
  line-height: 1.6;
}
.notice .mark {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--busy-dot);
  flex: none;
}
.notice .time {
  margin-left: auto;
  color: var(--busy);
  opacity: 0.75;
}
.stopped {
  padding: 1px 7px;
  border-radius: 20px;
  background: var(--busy-soft);
  color: var(--busy);
  font-size: 11px;
  font-weight: 600;
}

/* --- 질문 --- */
.ask {
  margin: 26px 0 14px auto;
  max-width: 72%;
  width: fit-content;
  background: var(--ink-900);
  color: #eef0f6;
  padding: 10px 16px;
  border-radius: 12px 12px 3px 12px;
  box-shadow: var(--shadow-sm);
}
.ask p {
  margin: 0;
  white-space: pre-wrap;
  font-size: 13.5px;
}
.ask.auto {
  border: 1px solid var(--accent);
}
.by {
  display: block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--accent-on-rail);
  margin-bottom: 2px;
}

/* --- 답변 --- */
.reply {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 20px 18px;
  margin-bottom: 14px;
  box-shadow: var(--shadow-md);
  animation: rise 0.25s ease both;
}
.reply.scheduled {
  border-left: 3px solid var(--accent);
}
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
}

header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.who {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-500);
  margin-right: auto; /* 이 뒤의 것들(모델·시각·복사)은 전부 오른쪽 구석에 붙는다 */
}
.model {
  color: var(--ink-400);
}
.time {
  color: var(--ink-400);
}
.copy {
  font-size: 11.5px;
  padding: 4px 11px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink-500);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s;
}
.copy:hover {
  border-color: var(--accent);
  color: var(--accent-hi);
}

/* --- 첫 응답을 기다리는 구간 --- */
.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--accent-hi);
}
.spark {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(13, 122, 130, 0.4);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(13, 122, 130, 0);
  }
}

/* --- 에이전트별 중간 출력 --- */
.drafts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}
.drafts section {
  border: 1px solid var(--line);
  border-left: 2px solid var(--accent);
  border-radius: 0 8px 8px 0;
  padding: 8px 12px;
  background: var(--surface-sunk);
}
.draft-name {
  color: var(--accent-hi);
  font-weight: 600;
}
.drafts pre {
  margin: 4px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--sans);
  font-size: 12px;
  color: var(--ink-500);
  max-height: 150px;
  overflow-y: auto;
}

.caret {
  display: inline-block;
  width: 2px;
  height: 15px;
  background: var(--accent);
  vertical-align: text-bottom;
  animation: blink 1.1s steps(2) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

/* --- 첨부 --- */
.files {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.file {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 12px 7px 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  text-decoration: none;
  color: var(--ink-700);
  font-size: 12.5px;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.file:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.ext {
  background: var(--ink-900);
  color: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
  font-size: 9.5px;
  letter-spacing: 0.06em;
}
.fname {
  font-weight: 500;
}
.fsize {
  color: var(--ink-400);
}
</style>
