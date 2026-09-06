<script setup>
/**
 * 실행 트레이스 - 이 화면의 중심 요소.
 *
 * 이 제품이 일반 챗봇과 다른 점은 "질문 하나가 여러 에이전트로 갈라졌다가 다시 합쳐진다"
 * 는 것이다. 게다가 로컬 모델이라 응답이 수십 초 걸린다. 그 과정을 "생각 중..." 뒤에
 * 숨기지 않고 그대로 보여준다.
 *
 * 병렬이면 하나의 지점에서 여러 갈래로 뻗고, 순차면 한 줄로 이어진다.
 * 즉 선의 모양이 plan.mode 라는 실제 값을 나타낸다.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  mode: { type: String, default: 'parallel' }, // parallel | sequential
  runs: { type: Array, default: () => [] }, // [{ agent, state, ms, model }]
  model: { type: String, default: '' }, // 방에서 고른 모델. 다른 것을 쓴 에이전트만 따로 표시한다
  reason: { type: String, default: '' }, // 라우터가 그렇게 고른 이유
  timings: { type: Object, default: () => ({}) }, // { route_ms, reduce_ms, direct_ms, total_ms }
  live: { type: Boolean, default: false }, // 진행 중이면 펼친 채로 둔다
})

const open = ref(true)
const isSequential = computed(() => props.mode === 'sequential')
const expanded = computed(() => props.live || open.value)

const totalMs = computed(() => {
  if (isSequential.value) return props.runs.reduce((sum, r) => sum + (r.ms || 0), 0)
  return Math.max(0, ...props.runs.map((r) => r.ms || 0)) // 병렬은 가장 오래 걸린 것
})

const LABELS = { pending: '대기', running: '실행 중', error: '실패', done: '완료' }

function stateLabel(state) {
  return LABELS[state] || LABELS.done
}

function seconds(ms) {
  if (!ms) return ''
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

// 코디네이터가 쓴 시간. 느릴 때 에이전트 탓인지 코어 탓인지 여기서 갈린다.
const coreSteps = computed(() =>
  [
    ['라우팅', props.timings.route_ms],
    ['합치기', props.timings.reduce_ms],
    ['직접 답변', props.timings.direct_ms],
  ].filter(([, ms]) => ms > 0),
)
const coreMs = computed(() => coreSteps.value.reduce((sum, [, ms]) => sum + ms, 0))
</script>

<template>
  <div v-if="runs.length" class="trace" :class="{ live }">
    <button class="bar" :aria-expanded="expanded" @click="open = !open">
      <span class="mark" :class="{ seq: isSequential }" aria-hidden="true"></span>
      <span class="label">{{ isSequential ? '순차 실행' : '병렬 실행' }}</span>
      <span class="data count">{{ runs.length }}</span>
      <span v-if="totalMs" class="data time">{{ seconds(totalMs) }}</span>
      <span class="chevron" :class="{ up: expanded }" aria-hidden="true"></span>
    </button>

    <ol v-if="expanded" class="nodes" :class="isSequential ? 'seq' : 'par'">
      <li v-for="run in runs" :key="run.agent" :class="run.state">
        <span class="dot" aria-hidden="true"></span>
        <span class="data agent">{{ run.agent }}</span>
        <span class="state">{{ stateLabel(run.state) }}</span>
        <!-- 자기 .env 로 모델을 고정한 에이전트는 화면 선택과 다른 모델로 돈다.
             그 사실이 안 보이면 "무슨 모델로 돌았지?" 를 알 길이 없다. -->
        <span v-if="run.model && run.model !== model" class="data other" :title="`이 에이전트는 ${run.model} 로 고정되어 있습니다`">
          {{ run.model }}
        </span>
        <span v-if="run.ms" class="data ms">{{ seconds(run.ms) }}</span>
        <span v-if="run.error" class="err">{{ run.error }}</span>
      </li>
    </ol>

    <p v-if="expanded && coreMs" class="core">
      코디네이터 <span class="data">{{ seconds(coreMs) }}</span>
      <span class="parts">
        ({{ coreSteps.map(([n, ms]) => `${n} ${seconds(ms)}`).join(' · ') }})
      </span>
    </p>

    <p v-if="expanded && reason" class="reason">{{ reason }}</p>
  </div>
</template>

<style scoped>
.trace {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-sunk);
  margin-bottom: 14px;
  overflow: hidden;
}
.trace.live {
  border-color: var(--accent);
  background: var(--accent-soft);
}

/* --- 접힘/펼침 바 --- */
.bar {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
  color: var(--ink-700);
}
.bar:hover .label {
  color: var(--ink-900);
}
.label {
  font-size: 12px;
  font-weight: 600;
}
.count::before {
  content: '에이전트 ';
}
.count,
.time {
  color: var(--ink-400);
}
.time {
  margin-left: auto;
}

/* 모드를 나타내는 작은 기호: 갈라짐 vs 이어짐 */
.mark {
  width: 12px;
  height: 12px;
  flex: none;
  border-left: 1.5px solid var(--accent);
  border-top: 1.5px solid var(--accent);
  border-bottom: 1.5px solid var(--accent);
  border-radius: 3px 0 0 3px;
}
.mark.seq {
  border: none;
  border-left: 1.5px solid var(--accent);
  height: 12px;
  width: 6px;
  margin-left: 3px;
}
.chevron {
  width: 6px;
  height: 6px;
  border-right: 1.5px solid var(--ink-300);
  border-bottom: 1.5px solid var(--ink-300);
  transform: rotate(45deg) translate(-2px, -2px);
  transition: transform 0.15s ease;
  flex: none;
}
.chevron.up {
  transform: rotate(-135deg) translate(-2px, -2px);
}

/* --- 노드 목록 --- */
.nodes {
  list-style: none;
  margin: 0;
  padding: 2px 12px 10px 20px;
  position: relative;
}
.nodes li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 3px 0 3px 16px;
  position: relative;
}

/* 병렬: 하나의 줄기에서 각 노드로 가지가 뻗는다 */
.nodes.par::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 12px;
  bottom: 14px;
  border-left: 1.5px solid var(--line-strong);
  border-radius: 2px;
}
.nodes.par li::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 12px;
  width: 11px;
  border-top: 1.5px solid var(--line-strong);
}

/* 순차: 노드끼리 사슬처럼 이어진다 */
.nodes.seq li::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 16px;
  bottom: -4px;
  border-left: 1.5px solid var(--line-strong);
}
.nodes.seq li:last-child::before {
  display: none;
}

.dot {
  position: absolute;
  left: 0;
  top: 8px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--surface);
  border: 1.5px solid var(--line-strong);
  box-sizing: border-box;
}
.agent {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-700);
}
.state,
.ms {
  font-size: 11px;
  color: var(--ink-400);
}
.ms {
  margin-left: auto;
}
.err {
  flex-basis: 100%;
  font-size: 11px;
  color: var(--danger);
}

/* 완료는 색을 빼서 가라앉히고, 지금 일하는 것만 강조한다 */
li.running .dot {
  border-color: var(--accent);
  background: var(--accent);
  animation: pulse 1.4s ease-in-out infinite;
}
li.running .agent,
li.running .state {
  color: var(--accent-hi);
}
li.error .dot {
  border-color: var(--danger);
  background: var(--danger);
}
li.error .agent,
li.error .state {
  color: var(--danger);
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(13, 122, 130, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(13, 122, 130, 0);
  }
}

.other {
  color: var(--busy);
  flex: none;
}
.core {
  margin: 0;
  padding: 7px 11px 0;
  font-size: 11.5px;
  color: var(--ink-500);
}
.core .parts {
  color: var(--ink-400);
}

.reason {
  margin: 0;
  padding: 0 12px 10px 20px;
  font-size: 11.5px;
  color: var(--ink-400);
  line-height: 1.5;
}
</style>
