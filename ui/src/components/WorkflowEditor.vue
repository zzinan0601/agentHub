<script setup>
// 워크플로우 편집기. 파일 원문(yaml)을 그대로 보여주고 그 자리에서 고친다.
//
// 폼으로 감싸지 않은 이유: 워크플로우의 정의는 yaml 파일 하나이고, 주석에 "왜 이 순서인가"
// 가 적힌다. 폼으로 받으면 주석이 사라지고, 파일을 직접 고치는 사람과 화면으로 고치는
// 사람이 서로 다른 것을 보게 된다. 대신 문법 오류와 없는 에이전트는 서버가 잡아준다.
import { computed, nextTick, ref, watch } from 'vue'
import { api } from '../api'
import InfoDialog from './InfoDialog.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'changed'])

const list = ref([])
const editable = ref(true)

const activeKey = ref(null) // 지금 열어 둔 워크플로우. isNew 면 아직 파일이 없다.
const isNew = ref(false)
const newKey = ref('')
const source = ref('')
const original = ref('')
const baseMtime = ref(null)

const check = ref(null) // 서버 검증 결과
const busy = ref(false)
const error = ref('')

const dirty = computed(() => source.value !== original.value)
const lines = computed(() => source.value.split('\n').length)
const canSave = computed(
  () => editable.value && !busy.value && !!check.value?.valid && (dirty.value || isNew.value),
)
// 목록에 실려 온 '마지막 수정' 문구. 공용 파일이라 누가 손댔는지 보여준다.
const updatedBy = computed(() => list.value.find((w) => w.key === activeKey.value)?.updated || '')

// 새 워크플로우는 빈 화면이 아니라 주석 달린 본보기로 시작한다.
// 원문 편집을 처음 하는 사람이 형식을 몰라 막히지 않게 하는 것이 폼을 포기한 대가다.
const TEMPLATE = `# 이 워크플로우가 왜 필요한지 여기에 적어두면 다음 사람이 이해합니다.

name: 새 워크플로우
description: 무엇을 하는 워크플로우인지 한 줄로 적습니다.
mode: sequential # sequential = 앞 결과를 다음으로 / parallel = 동시에 부르고 합침
steps:
  - agent: 에이전트id
`

const gutter = ref(null)

/** 목록을 다시 읽는다. 창을 열 때와 저장·삭제 뒤에 부른다. */
async function loadList() {
  const res = await api.listWorkflows()
  list.value = res.workflows
  editable.value = res.editable
}

/** 워크플로우 하나를 열어 원문을 띄운다. */
async function openItem(key) {
  if (!leaveOk()) return
  error.value = ''
  busy.value = true
  try {
    const res = await api.getWorkflowSource(key)
    activeKey.value = key
    isNew.value = false
    source.value = res.source
    original.value = res.source
    baseMtime.value = res.mtime
    await validate()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function startNew() {
  if (!leaveOk()) return
  error.value = ''
  activeKey.value = null
  isNew.value = true
  newKey.value = ''
  source.value = TEMPLATE
  original.value = TEMPLATE
  baseMtime.value = null
  await validate()
}

/** 저장하지 않은 변경이 있으면 한 번 물어본다. */
function leaveOk() {
  if (!dirty.value) return true
  return window.confirm('저장하지 않은 변경이 있습니다. 그대로 두고 옮길까요?')
}

// 타이핑이 멈추면 서버에 검사를 맡긴다. 편집기와 저장이 같은 규칙을 쓰게 하려면
// 검사를 화면에서 흉내 내지 않고 서버 함수 하나를 함께 부르는 편이 낫다.
let timer = null
function scheduleValidate() {
  clearTimeout(timer)
  timer = setTimeout(validate, 400)
}
async function validate() {
  try {
    check.value = await api.validateWorkflow(source.value)
  } catch {
    check.value = null
  }
}

/** yaml 은 들여쓰기가 곧 문법이다. Tab 이 포커스를 옮겨버리면 편집을 할 수 없다. */
function onTab(e) {
  e.preventDefault()
  const el = e.target
  const at = el.selectionStart
  source.value = source.value.slice(0, at) + '  ' + source.value.slice(el.selectionEnd)
  nextTick(() => {
    el.selectionStart = el.selectionEnd = at + 2
  })
  scheduleValidate()
}

/** 줄번호 칸이 편집기와 같이 움직이게 한다. */
function syncScroll(e) {
  if (gutter.value) gutter.value.scrollTop = e.target.scrollTop
}

async function save() {
  const key = isNew.value ? newKey.value.trim() : activeKey.value
  if (!key) return
  busy.value = true
  error.value = ''
  try {
    const res = await api.saveWorkflow(key, source.value, isNew.value ? null : baseMtime.value)
    // 서버가 맨 윗줄 수정 이력을 갈아 끼우므로 저장 결과를 그대로 다시 띄운다.
    source.value = res.source
    original.value = res.source
    baseMtime.value = res.mtime
    activeKey.value = key
    isNew.value = false
    await loadList()
    emit('changed')
  } catch (e) {
    error.value = cleanError(e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  const key = activeKey.value
  if (!key) return
  if (!window.confirm(`'${key}' 워크플로우를 지웁니다. 되돌릴 수 없습니다.`)) return
  busy.value = true
  error.value = ''
  try {
    await api.deleteWorkflow(key)
    activeKey.value = null
    source.value = ''
    original.value = ''
    check.value = null
    await loadList()
    emit('changed')
  } catch (e) {
    error.value = cleanError(e)
  } finally {
    busy.value = false
  }
}

/** 서버 오류는 '409 {"detail":"..."}' 꼴로 온다. 사람이 읽을 문장만 꺼낸다. */
function cleanError(e) {
  const body = e.message.replace(/^\d+\s/, '')
  try {
    return JSON.parse(body).detail || body
  } catch {
    return body
  }
}

async function close() {
  if (!leaveOk()) return
  emit('close')
}

// 창을 열 때마다 목록을 새로 읽는다. 다른 사람이 그 사이에 고쳤을 수 있다.
watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return
    error.value = ''
    activeKey.value = null
    isNew.value = false
    source.value = ''
    original.value = ''
    check.value = null
    await loadList()
    if (list.value.length) openItem(list.value[0].key)
  },
)
</script>

<template>
  <InfoDialog :open="open" size="wide" title="워크플로우" @close="close">
    <div class="editor">
      <!-- 왼쪽: 무엇을 고칠지 고른다 -->
      <aside class="picker">
        <p class="eyebrow">등록된 워크플로우</p>
        <ul>
          <li v-for="w in list" :key="w.key">
            <button :class="{ on: w.key === activeKey }" @click="openItem(w.key)">
              <span class="nm">
                {{ w.name }}
                <span v-if="w.key === activeKey && dirty" class="dot" title="저장 안 됨"></span>
              </span>
              <span class="sub data">{{ w.key }} · {{ w.steps.length }}단계</span>
            </button>
          </li>
          <li v-if="!list.length" class="none">아직 없습니다</li>
        </ul>
        <button v-if="editable" class="new" :class="{ on: isNew }" @click="startNew">
          ＋ 새 워크플로우
        </button>
      </aside>

      <!-- 오른쪽: 파일 원문 -->
      <section v-if="isNew || activeKey" class="pane">
        <div class="filename">
          <template v-if="isNew">
            <input
              v-model="newKey"
              class="data key"
              placeholder="weekly-report"
              maxlength="50"
              spellcheck="false"
            />
            <span class="ext data">.yaml</span>
            <span class="rule">영문 소문자 · 숫자 · 하이픈</span>
          </template>
          <template v-else>
            <span class="data key fixed">{{ activeKey }}</span>
            <span class="ext data">.yaml</span>
            <span v-if="updatedBy" class="rule">{{ updatedBy }}</span>
          </template>
        </div>

        <div class="code">
          <div ref="gutter" class="gutter data" aria-hidden="true">
            <span v-for="n in lines" :key="n">{{ n }}</span>
          </div>
          <textarea
            v-model="source"
            class="data"
            spellcheck="false"
            :readonly="!editable"
            @input="scheduleValidate"
            @scroll="syncScroll"
            @keydown.tab="onTab"
          ></textarea>
        </div>

        <!-- 검증 결과. 오류가 있으면 저장 버튼이 잠긴다. -->
        <div v-if="check" class="verdict">
          <p v-for="(m, i) in check.errors" :key="'e' + i" class="bad">{{ m }}</p>
          <p v-for="(m, i) in check.warnings" :key="'w' + i" class="soft">{{ m }}</p>
          <p v-if="check.valid && !check.warnings.length" class="ok">이상 없습니다.</p>
        </div>

        <div v-if="check && check.preview.steps.length" class="run">
          <p class="eyebrow">
            {{ check.preview.mode === 'sequential' ? '이 순서로 이어집니다' : '한꺼번에 부릅니다' }}
          </p>
          <ol class="steps" :class="check.preview.mode">
            <li v-for="(s, i) in check.preview.steps" :key="i">
              <span class="no data">{{ i + 1 }}</span>
              <span class="dot2" :class="{ on: s.online }"></span>
              <span class="nm">{{ s.name }}</span>
              <span class="aid data">{{ s.agent }}</span>
            </li>
          </ol>
        </div>

        <p v-if="error" class="err">{{ error }}</p>

        <footer>
          <button v-if="editable" class="solid" :disabled="!canSave" @click="save">
            {{ isNew ? '등록' : '저장' }}
          </button>
          <button v-if="editable && !isNew" class="ghost danger" :disabled="busy" @click="remove">
            삭제
          </button>
          <span class="grow"></span>
          <span v-if="!editable" class="ro">이 서버는 보기 전용입니다</span>
          <button class="ghost" @click="close">닫기</button>
        </footer>
      </section>

      <section v-else class="pane empty">
        <p>
          매번 같은 순서로 돌아야 하는 일에 씁니다. 방에서 워크플로우를 고르면 코디네이터의
          판단을 건너뛰고 정해진 에이전트를 정해진 차례대로 부릅니다.
        </p>
        <p>
          로컬 모델의 판단은 매번 조금씩 달라집니다. 정기 보고서처럼 결과 형식이 일정해야
          하는 작업이라면 워크플로우로 고정하고 스케줄과 묶어 쓰는 편이 낫습니다.
        </p>
        <p class="note">왼쪽에서 하나를 고르거나 새로 만드세요.</p>
      </section>
    </div>

    <details class="about">
      <summary>파일은 어디에 있나요?</summary>
      <p>
        <span class="data">core/workflows/</span> 폴더의 yaml 파일 하나가 워크플로우 하나입니다.
        여기서 저장하면 그 파일을 고치는 것이고, <b>코어를 다시 띄우지 않아도</b> 다음 질문부터
        바로 반영됩니다. 폴더에 파일을 직접 놓아도 똑같이 인식됩니다.
      </p>
      <p>
        맨 윗줄의 <span class="data">#&nbsp;마지막&nbsp;수정:</span> 줄은 저장할 때 서버가 자동으로
        갱신합니다. 공용 파일이라 누가 마지막에 손댔는지 남겨둡니다.
      </p>
    </details>
  </InfoDialog>
</template>

<style scoped>
.editor {
  display: grid;
  grid-template-columns: 190px 1fr;
  gap: 18px;
  align-items: start;
}

/* --- 왼쪽 목록 --- */
.picker {
  border-right: 1px solid var(--line);
  padding-right: 16px;
  min-height: 320px;
}
.picker ul {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
  max-height: 46vh;
  overflow-y: auto;
}
.picker li button {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  border-radius: 8px;
  padding: 7px 9px;
  cursor: pointer;
  color: var(--ink-700);
}
.picker li button:hover {
  background: var(--surface-sunk);
}
.picker li button.on {
  background: var(--accent-soft);
  color: var(--accent-hi);
}
.nm {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
}
.sub {
  display: block;
  color: var(--ink-400);
  margin-top: 1px;
}
.picker li button.on .sub {
  color: var(--accent-hi);
}
.none {
  color: var(--ink-400);
  font-size: 12px;
  padding: 7px 9px;
}
.dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--danger);
  vertical-align: middle;
  margin-left: 4px;
}
.new {
  width: 100%;
  border: 1px dashed var(--line-strong);
  background: none;
  border-radius: 8px;
  padding: 7px;
  font-size: 12px;
  color: var(--ink-500);
  cursor: pointer;
}
.new:hover,
.new.on {
  border-color: var(--accent);
  color: var(--accent-hi);
}

/* --- 오른쪽 편집 --- */
.pane.empty {
  padding-top: 4px;
}
.filename {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 8px;
}
.key {
  font-size: 12px;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  padding: 5px 8px;
  width: 190px;
}
.key:focus {
  outline: none;
  border-color: var(--accent);
}
.key.fixed {
  border-color: transparent;
  padding-left: 0;
  width: auto;
  font-weight: 700;
  color: var(--ink-900);
}
.ext {
  color: var(--ink-400);
}
.rule {
  margin-left: auto;
  font-size: 11px;
  color: var(--ink-400);
}

.code {
  display: flex;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  overflow: hidden;
  background: var(--surface-sunk);
}
.gutter {
  display: flex;
  flex-direction: column;
  padding: 10px 8px 10px 10px;
  color: var(--ink-400);
  text-align: right;
  user-select: none;
  overflow: hidden;
  border-right: 1px solid var(--line);
}
.gutter span {
  line-height: 1.6;
  font-size: 12px;
}
.code textarea {
  flex: 1;
  border: none;
  background: var(--surface);
  resize: vertical;
  padding: 10px 12px;
  min-height: 300px;
  font-size: 12px;
  line-height: 1.6;
  letter-spacing: 0;
  color: var(--ink-900);
  tab-size: 2;
  white-space: pre;
  overflow-wrap: normal;
  overflow-x: auto;
}
.code textarea:focus {
  outline: none;
}

/* --- 검증 --- */
.verdict {
  margin: 9px 0 0;
}
.verdict p {
  margin: 0 0 3px;
  font-size: 12px;
  padding-left: 15px;
  position: relative;
  line-height: 1.6;
}
.verdict p::before {
  position: absolute;
  left: 0;
  top: 0;
}
.verdict .bad {
  color: var(--danger);
}
.verdict .bad::before {
  content: '×';
  font-weight: 700;
}
.verdict .soft {
  color: var(--ink-500);
}
.verdict .soft::before {
  content: '!';
  font-weight: 700;
}
.verdict .ok {
  color: var(--accent-hi);
}
.verdict .ok::before {
  content: '✓';
}

/* --- 실행 순서 미리보기 (기존 다이얼로그의 표현을 그대로 쓴다) --- */
.run {
  margin-top: 12px;
}
.steps {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
}
.steps li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 0 5px 2px;
  position: relative;
}
.steps.sequential li:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 9px;
  top: 27px;
  height: 7px;
  width: 1px;
  background: var(--line-strong);
}
.no {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--surface-sunk);
  border: 1px solid var(--line-strong);
  display: grid;
  place-items: center;
  font-size: 10px;
  color: var(--ink-500);
  flex: none;
}
.dot2 {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ink-300);
  flex: none;
}
.dot2.on {
  background: var(--accent);
}
.steps .nm {
  display: inline;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-700);
}
.aid {
  color: var(--ink-400);
  margin-left: auto;
}

.err {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 8px 11px;
  line-height: 1.6;
}

footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding-top: 13px;
  border-top: 1px solid var(--line);
}
.grow {
  flex: 1;
}
.ro {
  font-size: 11.5px;
  color: var(--ink-400);
}
footer button {
  border-radius: 8px;
  padding: 7px 15px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--ink-700);
}
footer .solid {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}
footer .solid:disabled {
  border-color: var(--line-strong);
  background: var(--surface-sunk);
  color: var(--ink-400);
  cursor: default;
}
footer .ghost:hover:not(:disabled) {
  border-color: var(--ink-500);
}
footer .danger {
  color: var(--danger);
}
footer .danger:hover:not(:disabled) {
  border-color: var(--danger);
}

.about {
  margin-top: 16px;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
.about summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--ink-500);
}
.about p {
  margin: 8px 0 0;
  font-size: 11.5px;
  color: var(--ink-400);
  line-height: 1.7;
}

.pane.empty p {
  margin: 0 0 10px;
}
.pane.empty .note {
  color: var(--ink-400);
  font-size: 11.5px;
}
</style>
