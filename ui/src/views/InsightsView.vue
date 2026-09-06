<script setup>
// 활용 현황. 어떤 질문이 많고 어떤 에이전트가 자주 불리는지.
//
// 화면의 실질적인 목적은 "점검 대상" 을 찾는 것이다. 그래서 숫자를 나열하는 데
// 그치지 않고, 문제 있는 항목을 위쪽에 따로 모아 보여준다.
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()

const PERIODS = [
  { key: 'today', label: '오늘' },
  { key: '7d', label: '7일' },
  { key: '30d', label: '30일' },
  { key: 'all', label: '전체' },
]
const SORTS = [
  { key: 'calls', label: '호출 많은 순' },
  { key: 'p95_ms', label: '느린 순' },
  { key: 'fail_rate', label: '실패 많은 순' },
]

const period = ref('7d')
const sort = ref('calls')
const data = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.insights(period.value)
  } catch (e) {
    error.value = e.message === 'UNAUTHORIZED' ? '' : `현황을 불러오지 못했습니다. ${e.message}`
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(period, load)

const agents = computed(() => {
  const list = [...(data.value?.agents || [])]
  return list.sort((a, b) => (b[sort.value] || 0) - (a[sort.value] || 0))
})

// --- 확인 표시 -------------------------------------------------------------
//
// 점검 대상은 "봤고 처리했다" 를 표시할 수 있어야 목록으로 쓸모가 있다.
// 사라진 뒤에도 문제가 다시 달라지면(새 이유가 붙으면) 다시 나타나야 하므로,
// 항목 자체가 아니라 '어떤 이유로 떴는지' 까지 합친 지문을 저장한다.
// 이 표시는 브라우저에만 남는다. 내가 확인했다고 남의 화면까지 지우면 안 된다.
const STORE_KEY = 'insights.checked'
const checked = ref(readChecked())

function readChecked() {
  try {
    return new Set(JSON.parse(localStorage.getItem(STORE_KEY) || '[]'))
  } catch {
    return new Set() // 사생활 보호 모드 등에서 막힐 수 있다. 그냥 다 보여준다.
  }
}
function writeChecked() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify([...checked.value]))
  } catch {
    /* 저장이 막혀도 화면은 돌아야 한다 */
  }
}
function markChecked(key) {
  checked.value = new Set(checked.value).add(key)
  writeChecked()
}
function clearChecked() {
  checked.value = new Set()
  writeChecked()
}

/** 점검 대상 - 문제가 있는 에이전트를 이유와 함께 모은다. */
const allTrouble = computed(() => {
  const warn = data.value?.fail_rate_warn ?? 0.2
  const out = []
  for (const a of data.value?.agents || []) {
    const reasons = []
    if (a.unregistered) reasons.push('registry.yaml 에서 빠짐')
    else if (!a.online) reasons.push('응답 없음')
    if (a.contract_mismatch) reasons.push('계약 버전 다름')
    if (a.calls === 0 && !a.unregistered) reasons.push('이 기간에 한 번도 안 불림')
    if (a.calls > 0 && a.fail_rate >= warn) reasons.push(`실패율 ${pct(a.fail_rate)}`)
    // 이유가 바뀌면 지문도 바뀌어 확인 표시가 저절로 풀린다.
    if (reasons.length) out.push({ ...a, reasons, key: `${a.agent_id}|${reasons.join('|')}` })
  }
  return out
})
const trouble = computed(() => allTrouble.value.filter((t) => !checked.value.has(t.key)))

// 건너뛴 예약도 같은 방식으로 확인 표시를 한다. 건수가 늘면 다시 뜬다.
const skipKey = computed(() => `skipped|${period.value}|${data.value?.summary?.skipped || 0}`)
const showSkipped = computed(
  () => !!data.value?.summary?.skipped && !checked.value.has(skipKey.value),
)
const hiddenCount = computed(
  () => allTrouble.value.length - trouble.value.length + (
    data.value?.summary?.skipped && !showSkipped.value ? 1 : 0
  ),
)

const routingBars = computed(() => {
  const r = data.value?.routing
  if (!r || !r.total) return []
  const labels = { auto: '자동 선택', manual: '사용자 지정', workflow: '워크플로우' }
  return Object.entries(r.by_source).map(([k, n]) => ({
    label: labels[k] || k,
    n,
    ratio: n / r.total,
  }))
})

const modeBars = computed(() => {
  const r = data.value?.routing
  if (!r || !r.total) return []
  const labels = { single: '단일', parallel: '병렬', sequential: '순차' }
  return Object.entries(r.by_mode).map(([k, n]) => ({
    label: labels[k] || k,
    n,
    ratio: n / r.total,
  }))
})

// 최근 질문에 실린 코어 시간의 평균. 별도 집계 없이 이미 받은 값으로 낸다.
const avgCoreMs = computed(() => {
  const rows = (data.value?.recent || []).filter((q) => q.core_ms > 0)
  if (!rows.length) return 0
  return Math.round(rows.reduce((sum, q) => sum + q.core_ms, 0) / rows.length)
})

const maxDaily = computed(() => Math.max(1, ...(data.value?.daily || []).map((d) => d.count)))
const peakDay = computed(
  () => (data.value?.daily || []).find((d) => d.count === maxDaily.value) || { day: '-', count: 0 },
)

/** 날짜 라벨을 몇 개나 보여줄지. 30일치를 다 찍으면 글자가 서로 겹친다. */
function labelAt(i) {
  const n = data.value?.daily?.length || 0
  if (n <= 12) return true
  const step = Math.ceil(n / 8)
  return i % step === 0 || i === n - 1
}

function ms(v) {
  if (!v) return '-'
  return v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`
}
function pct(v) {
  return `${Math.round((v || 0) * 100)}%`
}
/**
 * 모델 이름을 짧게. 단 **크기는 남긴다.**
 * gemma4:e2b / e4b / 12b 를 함께 쓰므로 이름만 남기면 셋이 구분되지 않는다.
 * 태그에서 배포 꼬리(-cloud, -instruct 등)만 떼고 크기는 그대로 둔다.
 *
 *   gemma4:31b-cloud  -> gemma4:31b
 *   gemma4:e2b        -> gemma4:e2b
 *   gpt-oss:20b-cloud -> gpt-oss:20b   (이름의 하이픈은 건드리지 않는다)
 */
function shortModel(name) {
  if (!name) return ''
  const at = name.indexOf(':')
  if (at < 0) return name
  return `${name.slice(0, at)}:${name.slice(at + 1).split('-')[0]}`
}
function when(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  const hm = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
  return today ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}
function openRoom() {
  // 개인 전용이라 남의 방은 열리지 않는다. 내 방이면 그 방으로 간다.
  router.push({ name: 'chat' })
}
</script>

<template>
  <div class="insights">
    <header class="head">
      <div>
        <p class="eyebrow">에이전트 허브</p>
        <h1>Dashboard</h1>
      </div>
      <div class="periods">
        <button
          v-for="p in PERIODS"
          :key="p.key"
          :class="{ picked: period === p.key }"
          @click="period = p.key"
        >
          {{ p.label }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading && !data" class="loading">불러오는 중…</p>

    <template v-if="data">
      <!-- 요약 -->
      <section class="tiles">
        <div class="tile">
          <span class="k">질문</span>
          <b>{{ data.summary.questions.toLocaleString() }}</b>
        </div>
        <div class="tile">
          <span class="k">에이전트 호출</span>
          <b>{{ data.summary.calls.toLocaleString() }}</b>
        </div>
        <div class="tile" :class="{ bad: data.summary.fail_rate >= data.fail_rate_warn }">
          <span class="k">실패율</span>
          <b>{{ pct(data.summary.fail_rate) }}</b>
          <span class="sub">{{ data.summary.errors }}건</span>
        </div>
        <div class="tile">
          <span class="k">평균 응답</span>
          <b>{{ ms(data.summary.avg_ms) }}</b>
        </div>
        <div class="tile" :title="'질문 하나에 코디네이터 LLM 이 쓴 평균 시간'">
          <span class="k">코디네이터</span>
          <b>{{ ms(avgCoreMs) }}</b>
          <span class="sub">에이전트 외 시간</span>
        </div>
        <div class="tile">
          <span class="k">사용자</span>
          <b>{{ data.summary.users }}</b>
        </div>

      </section>

      <!-- 일자별 질문 수. 날짜를 읽을 수 있어야 의미가 있어 한 줄을 통째로 쓴다. -->
      <section v-if="data.daily.length" class="panel trend">
        <h2>
          일자별 질문
          <span class="peak">최다 {{ peakDay.day }} · {{ peakDay.count }}건</span>
        </h2>
        <div class="chart">
          <div v-for="(d, i) in data.daily" :key="d.day" class="col" :title="`${d.day} · ${d.count}건`">
            <span class="n data" :class="{ show: d.count === maxDaily || data.daily.length <= 14 }">
              {{ d.count }}
            </span>
            <span
              class="bar"
              :class="{ top: d.count === maxDaily }"
              :style="{ height: `${(d.count / maxDaily) * 100}%` }"
            ></span>
            <!-- 날짜가 서로 겹치지 않게 개수에 따라 솎아낸다. 끝은 항상 남긴다. -->
            <span class="day data" :class="{ show: labelAt(i) }">{{ d.day }}</span>
          </div>
        </div>
      </section>

      <!-- ③ 점검 대상 - 문제부터 위에. 확인한 것은 지워 목록으로 쓸 수 있게 한다. -->
      <section v-if="trouble.length || showSkipped || hiddenCount" class="panel warn">
        <h2>
          점검 대상
          <span v-if="trouble.length || showSkipped" class="count">
            {{ trouble.length + (showSkipped ? 1 : 0) }}
          </span>
          <button v-if="hiddenCount" class="undo" @click="clearChecked">
            확인함 {{ hiddenCount }}개 · 다시 보기
          </button>
        </h2>

        <!-- 겹쳐서 못 돈 예약. 쌓이면 주기가 응답 시간보다 짧다는 뜻이다. -->
        <p v-if="showSkipped" class="skipped">
          예약 <b>{{ data.summary.skipped }}건</b>이 앞 실행과 겹치거나 에이전트가 사용 중이라
          건너뛰었습니다. 스케줄 주기를 응답 시간보다 길게 잡으세요.
          <button class="done" title="확인함" @click="markChecked(skipKey)">확인</button>
        </p>

        <ul v-if="trouble.length" class="trouble">
          <li v-for="a in trouble" :key="a.key">
            <span class="data aid">{{ a.agent_id }}</span>
            <span class="aname">{{ a.name }}</span>
            <span v-if="a.owner" class="owner">{{ a.owner }}</span>
            <span class="reasons">
              <span v-for="r in a.reasons" :key="r" class="reason">{{ r }}</span>
            </span>
            <button class="done" title="확인함" @click="markChecked(a.key)">확인</button>
          </li>
        </ul>

        <p v-if="trouble.length" class="hint">
          한 번도 안 불렸다면 대개 manifest 의 description 이 모호해서다. 무엇을, 어떤 단위로,
          어떤 형태로 주는지 구체적으로 쓰면 라우터가 찾아낸다.
        </p>
        <p v-else-if="hiddenCount" class="hint">
          지금 볼 것은 없습니다. 확인 표시는 이 브라우저에만 남고, 같은 문제가 다시 달라지면
          저절로 나타납니다.
        </p>
      </section>

      <!-- ① 에이전트별 활용 -->
      <section class="panel">
        <h2>
          에이전트별 활용
          <span class="sorts">
            <button
              v-for="s in SORTS"
              :key="s.key"
              :class="{ picked: sort === s.key }"
              @click="sort = s.key"
            >
              {{ s.label }}
            </button>
          </span>
        </h2>
        <div class="scroll-x">
          <table>
            <thead>
              <tr>
                <th>에이전트</th>
                <th>담당자</th>
                <th class="r">호출</th>
                <th class="r">실패</th>
                <th class="r">평균</th>
                <th class="r">p95</th>
                <th class="r">최대</th>
                <th class="r">num_ctx</th>
                <th class="r">마지막</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in agents" :key="a.agent_id" :class="{ idle: a.calls === 0 }">
                <td>
                  <span class="dot" :class="{ on: a.online }"></span>
                  <span class="aname">{{ a.name }}</span>
                  <span class="data aid">{{ a.agent_id }}</span>
                </td>
                <td class="muted">{{ a.owner || '-' }}</td>
                <td class="r data">{{ a.calls.toLocaleString() }}</td>
                <td class="r data" :class="{ bad: a.fail_rate >= data.fail_rate_warn && a.calls }">
                  {{ a.errors ? `${a.errors} (${pct(a.fail_rate)})` : '-' }}
                </td>
                <td class="r data">{{ ms(a.avg_ms) }}</td>
                <td class="r data">{{ ms(a.p95_ms) }}</td>
                <td class="r data">{{ ms(a.max_ms) }}</td>
                <td class="r data">{{ a.avg_num_ctx ? a.avg_num_ctx.toLocaleString() : '-' }}</td>
                <td class="r data muted">{{ when(a.last_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="hint">
          num_ctx 는 에이전트가 실제로 쓴 값이다. 최대치가 .env 의 NUM_CTX_MAX 에 자주 닿으면
          CHARS_PER_TOKEN 이 실제보다 크게 잡혀 있다는 뜻이다. LLM 을 쓰지 않는 에이전트는 비어 있다.
        </p>
      </section>

      <!-- ④ 라우팅 분석 -->
      <section class="panel two">
        <div>
          <h2>선택 방식</h2>
          <div class="bar-rows">
            <div v-for="b in routingBars" :key="b.label" class="row">
              <span class="lbl">{{ b.label }}</span>
              <span class="track"><span class="fill" :style="{ width: pct(b.ratio) }"></span></span>
              <span class="data val">{{ b.n }} · {{ pct(b.ratio) }}</span>
            </div>
          </div>

          <h2 class="mt">실행 방식</h2>
          <div class="bar-rows">
            <div v-for="b in modeBars" :key="b.label" class="row">
              <span class="lbl">{{ b.label }}</span>
              <span class="track"><span class="fill" :style="{ width: pct(b.ratio) }"></span></span>
              <span class="data val">{{ b.n }} · {{ pct(b.ratio) }}</span>
            </div>
          </div>
        </div>

        <div class="gap-box" :class="{ alert: data.routing.no_agent > 0 }">
          <span class="k">에이전트 미호출 질문</span>
          <b>{{ data.routing.no_agent }}</b>
          <span class="sub">
            전체 {{ data.routing.total }}건 중
            {{ pct(data.routing.total ? data.routing.no_agent / data.routing.total : 0) }}
          </span>
          <ul v-if="data.routing.no_agent_examples.length" class="examples">
            <li v-for="(q, i) in data.routing.no_agent_examples" :key="i">{{ q }}</li>
          </ul>
          <p class="hint">
            이 값이 높으면 사람들이 묻는 일에 맞는 에이전트가 아직 없다는 뜻이다.
            다음에 만들 에이전트를 여기서 고르면 된다.
          </p>
        </div>
      </section>

      <!-- ②-1 자주 묻는 질문 -->
      <section v-if="data.frequent?.length" class="panel">
        <h2>
          자주 묻는 질문
          <span class="sub-note">말끝만 다른 질문은 하나로 셉니다</span>
        </h2>
        <ul class="frequent">
          <li v-for="(f, i) in data.frequent" :key="i">
            <span class="n data" :title="`표현 ${f.variants}가지`">{{ f.count }}</span>
            <span class="q">{{ f.question }}</span>
            <span v-if="f.variants > 1" class="variants">{{ f.variants }}가지</span>
            <span class="chips">
              <span v-for="a in f.agents.slice(0, 3)" :key="a" class="chip">{{ a }}</span>
              <span v-if="f.agents.length > 3" class="chip more">+{{ f.agents.length - 3 }}</span>
              <span v-if="!f.agents.length" class="chip none">직접 답변</span>
            </span>
            <!-- 같은 질문을 다른 모델로 던진 결과를 나란히 두면 속도 차이가 바로 보인다 -->
            <span class="models">
              <span v-for="m in f.models.slice(0, 3)" :key="m.model" class="model">
                {{ shortModel(m.model) }} <b>{{ ms(m.avg_ms) }}</b>
                <i v-if="f.models.length > 1">×{{ m.count }}</i>
              </span>
            </span>
            <span class="data at">{{ when(f.last_at) }}</span>
          </li>
        </ul>
      </section>

      <!-- ⑤ 사용자별 -->
      <section class="panel">
        <h2>사용자별 활용</h2>
        <div class="scroll-x">
          <table>
            <thead>
              <tr>
                <th>사용자</th>
                <th class="r">질문</th>
                <th class="r">에이전트 호출</th>
                <th class="r">마지막</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in data.users" :key="u.name">
                <td>{{ u.name }}</td>
                <td class="r data">{{ u.questions.toLocaleString() }}</td>
                <td class="r data">{{ u.calls.toLocaleString() }}</td>
                <td class="r data muted">{{ when(u.last_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <!-- ② 최근 질문 -->
      <section class="panel">
        <h2>최근 질문</h2>
        <ul class="questions">
          <li v-for="(q, i) in data.recent" :key="i">
            <span class="q">{{ q.question }}</span>
            <span class="chips">
              <span v-if="q.scheduled" class="chip auto">예약</span>
              <span
                v-for="a in q.agents"
                :key="a"
                class="chip"
                :class="{ bad: q.failed.includes(a) }"
                >{{ a }}</span
              >
              <span v-if="!q.agents.length" class="chip none">직접 답변</span>
            </span>
            <span class="data who">{{ q.user }}</span>
            <span class="data mdl" :title="q.model">{{ shortModel(q.model) || '-' }}</span>
            <span class="data took" title="에이전트 시간">{{ ms(q.elapsed_ms) }}</span>
            <span class="data core" title="코디네이터(라우팅·합치기·직접답변) 시간">
              {{ q.core_ms ? '+' + ms(q.core_ms) : '' }}
            </span>
            <span class="data at">{{ when(q.created_at) }}</span>
          </li>
        </ul>
        <p v-if="!data.recent.length" class="hint">이 기간에 오간 질문이 없습니다.</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.insights {
  height: 100%;
  overflow-y: auto;
  background: var(--canvas);
  padding: 24px 28px 48px;
}
.insights > * {
  max-width: 1100px;
  margin-left: auto;
  margin-right: auto;
}

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}
h1 {
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.02em;
  margin: 6px 0 0;
}
.periods,
.sorts {
  display: flex;
  gap: 4px;
}
.periods button,
.sorts button {
  padding: 5px 13px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--surface);
  color: var(--ink-500);
  font-size: 12px;
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s,
    color 0.15s;
}
.periods button:hover,
.sorts button:hover {
  border-color: var(--line-strong);
  color: var(--ink-900);
}
.periods button.picked,
.sorts button.picked {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-hi);
  font-weight: 600;
}

.error {
  padding: 10px 14px;
  background: var(--danger-soft);
  color: var(--danger);
  border-radius: 8px;
  font-size: 13px;
}
.loading {
  color: var(--ink-400);
  font-size: 13px;
}

/* --- 요약 타일 --- */
.tiles {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}
.tile,
.gap-box {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 13px 15px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.k {
  font-size: 11px;
  color: var(--ink-400);
}
.tile b {
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.tile .sub,
.gap-box .sub {
  font-size: 11px;
  color: var(--ink-400);
}
.tile.bad b {
  color: var(--danger);
}

/* --- 일자별 질문 --- */
.trend .peak {
  margin-left: auto;
  font-size: 11px;
  font-weight: 400;
  color: var(--ink-400);
}
.chart {
  display: flex;
  align-items: flex-end;
  gap: 4px;
}
.col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  /* 막대를 아래에서 세우고 그 아래에 날짜를 둔다 */
  justify-content: flex-end;
  height: 108px;
}
.col .n {
  font-size: 10px;
  color: var(--ink-400);
  margin-bottom: 3px;
  visibility: hidden;
}
.col .n.show {
  visibility: visible;
}
.col .bar {
  width: 100%;
  max-width: 34px;
  min-height: 2px;
  background: var(--accent);
  border-radius: 3px 3px 0 0;
  opacity: 0.62;
  transition: opacity 0.15s;
}
/* 가장 많았던 날만 진하게. 나머지는 배경으로 가라앉힌다. */
.col .bar.top {
  opacity: 1;
}
.col:hover .bar {
  opacity: 1;
}
.col .day {
  margin-top: 6px;
  font-size: 10px;
  color: var(--ink-400);
  white-space: nowrap;
  visibility: hidden;
}
.col .day.show {
  visibility: visible;
}

/* --- 패널 --- */
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
.panel.warn {
  border-color: var(--danger);
  background: var(--danger-soft);
}
.skipped {
  margin: 0 0 14px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-700);
}
.skipped b {
  color: var(--busy);
}

/* --- 확인 표시 --- */
.done {
  margin-left: auto;
  flex: none;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  border-radius: 6px;
  padding: 2px 9px;
  font-size: 11px;
  color: var(--ink-500);
  cursor: pointer;
}
.done:hover {
  border-color: var(--ink-500);
  color: var(--ink-900);
}
.undo {
  margin-left: auto;
  border: none;
  background: none;
  font-size: 11px;
  color: var(--ink-500);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.undo:hover {
  color: var(--ink-900);
}
.panel.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 28px;
}
h2 {
  font-size: 13px;
  font-weight: 650;
  margin: 0 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
h2.mt {
  margin-top: 22px;
}
.count {
  font-size: 11px;
  background: var(--danger);
  color: #fff;
  padding: 1px 8px;
  border-radius: 20px;
}
.hint {
  margin: 12px 0 0;
  font-size: 11.5px;
  color: var(--ink-400);
  line-height: 1.6;
}

/* --- 점검 대상 --- */
.trouble {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trouble li {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  background: var(--surface);
  border-radius: 8px;
  padding: 8px 12px;
}
.aid {
  color: var(--ink-400);
}
.aname {
  font-size: 12.5px;
  font-weight: 600;
}
.owner {
  font-size: 11px;
  color: var(--ink-400);
}
.reasons {
  margin-left: auto;
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.reason {
  font-size: 11px;
  color: var(--danger);
  border: 1px solid currentColor;
  border-radius: 20px;
  padding: 1px 9px;
}

/* --- 표 --- */
.scroll-x {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
th {
  text-align: left;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-400);
  font-weight: 600;
  padding: 0 10px 8px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
tr:last-child td {
  border-bottom: none;
}
.r {
  text-align: right;
}
td.muted {
  color: var(--ink-400);
}
td.bad {
  color: var(--danger);
  font-weight: 600;
}
tr.idle td {
  opacity: 0.6;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-300);
  margin-right: 7px;
}
.dot.on {
  background: var(--accent);
}
td .aid {
  margin-left: 7px;
}

/* --- 비율 막대 --- */
.bar-rows {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.lbl {
  width: 74px;
  font-size: 12px;
  color: var(--ink-700);
  flex: none;
}
.track {
  flex: 1;
  height: 7px;
  background: var(--surface-sunk);
  border-radius: 4px;
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
}
.val {
  width: 74px;
  text-align: right;
  color: var(--ink-400);
  flex: none;
}

.gap-box b {
  font-size: 26px;
  font-weight: 650;
  letter-spacing: -0.02em;
}
.gap-box.alert {
  border-color: var(--accent);
}
.gap-box.alert b {
  color: var(--accent-hi);
}
.examples {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.examples li {
  font-size: 11.5px;
  color: var(--ink-500);
  background: var(--surface-sunk);
  border-radius: 6px;
  padding: 5px 9px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.questions .core {
  color: var(--ink-400);
}

/* --- 최근 질문 --- */
.questions {
  list-style: none;
  margin: 0;
  padding: 0;
}
.questions li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 4px;
  border-bottom: 1px solid var(--line);
}
.questions li:last-child {
  border-bottom: none;
}
.q {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chips {
  display: flex;
  gap: 4px;
  flex: none;
}
.chip {
  font-size: 10.5px;
  font-family: var(--mono);
  padding: 2px 8px;
  border-radius: 20px;
  background: var(--surface-sunk);
  color: var(--ink-500);
}
.chip.bad {
  background: var(--danger-soft);
  color: var(--danger);
}
.chip.auto {
  background: var(--accent-soft);
  color: var(--accent-hi);
}
.chip.none {
  color: var(--ink-400);
  font-family: var(--sans);
}
.who {
  width: 70px;
  color: var(--ink-500);
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap; /* 없으면 긴 이름이 접혀 줄 높이가 들쭉날쭉해진다 */
}
/* 어떤 모델로 답했는지. 모델마다 속도가 달라 소요시간과 나란히 둔다. */
.mdl {
  width: 88px;
  text-align: right;
  color: var(--ink-400);
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* --- 자주 묻는 질문 --- */
.sub-note {
  font-size: 11px;
  font-weight: 400;
  color: var(--ink-400);
}
.frequent {
  list-style: none;
  margin: 0;
  padding: 0;
}
/* 한 줄에 담는다. 질문만 늘어나고 나머지는 제 폭을 지킨다. */
.frequent li {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 4px;
  border-bottom: 1px solid var(--line);
}
.frequent li:last-child {
  border-bottom: none;
}
.frequent .n {
  min-width: 24px;
  height: 20px;
  padding: 0 6px;
  flex: none;
  border-radius: 6px;
  background: var(--ink-900);
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
}
.frequent .q {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.frequent .variants {
  flex: none;
  font-size: 10.5px;
  color: var(--ink-400);
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 1px 7px;
}
.frequent .models {
  display: flex;
  gap: 4px;
  flex: none;
}
.frequent .model {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--ink-400);
  background: var(--surface-sunk);
  border-radius: 20px;
  padding: 2px 9px;
  white-space: nowrap;
}
.frequent .model b {
  color: var(--ink-700);
  font-weight: 600;
}
.frequent .model i {
  font-style: normal;
  color: var(--ink-300);
}
.chip.more {
  color: var(--ink-400);
}
.took {
  width: 58px;
  text-align: right;
  color: var(--ink-400);
  flex: none;
}
/* "8/26 22:58" 이 접히면 줄 높이가 두 배가 된다. 한 줄에 들어갈 만큼 준다. */
.at {
  width: 76px;
  text-align: right;
  color: var(--ink-400);
  flex: none;
  white-space: nowrap;
}
</style>
