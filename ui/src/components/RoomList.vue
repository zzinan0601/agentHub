<script setup>
// 좌측 레일: 채팅방 목록. 여러 개 만들고, 이름을 바꾸고, 지운다. (요구사항 13)
import { nextTick, ref } from 'vue'

defineProps({
  rooms: { type: Array, default: () => [] },
  activeId: { type: Number, default: null },
  online: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
})
const emit = defineEmits(['select', 'create', 'remove', 'rename'])

// 이름을 고치는 중인 방. 제목 자리를 그대로 입력칸으로 바꾼다.
// 다이얼로그를 띄우면 "어느 방을 고치는 중인지" 를 다시 설명해야 한다.
const editingId = ref(null)
const draft = ref('')
const input = ref(null)

// Esc 로 닫으면 입력칸이 사라지면서 blur 가 함께 터진다. 그대로 두면 취소가
// 저장으로 뒤집히므로, 취소였다는 것을 한 번만 기억해 뒤따라온 blur 를 흘려보낸다.
let cancelled = false

function startRename(room) {
  cancelled = false
  editingId.value = room.id
  draft.value = room.title
  nextTick(() => input.value?.[0]?.select())
}

function cancelRename() {
  cancelled = true
  editingId.value = null
}

function commit(room) {
  if (cancelled) {
    cancelled = false
    return
  }
  const title = draft.value.trim()
  editingId.value = null
  // 비웠거나 그대로면 아무 일도 하지 않는다. 빈 제목은 목록에서 찾을 수 없게 된다.
  if (title && title !== room.title) emit('rename', room.id, title)
}
</script>

<template>
  <nav class="rail">
    <div class="brand">
      <span class="wordmark">에이전트 허브</span>
      <span class="data status">
        <i :class="{ live: online > 0 }"></i>{{ online }}/{{ total }} 온라인
      </span>
    </div>

    <button class="new" @click="emit('create')">
      <span class="plus" aria-hidden="true">+</span> 새 대화
    </button>

    <p class="eyebrow section">대화</p>

    <ul>
      <li
        v-for="room in rooms"
        :key="room.id"
        :class="{ active: room.id === activeId, unread: room.unread > 0 }"
        @click="editingId === room.id || emit('select', room.id)"
        @dblclick="startRename(room)"
      >
        <span v-if="room.unread && editingId !== room.id" class="bell" aria-hidden="true"></span>

        <!-- 이름 고치는 중: 제목 자리가 그대로 입력칸이 된다 -->
        <input
          v-if="editingId === room.id"
          ref="input"
          v-model="draft"
          class="rename"
          maxlength="200"
          @click.stop
          @keydown.enter="commit(room)"
          @keydown.esc="cancelRename"
          @blur="commit(room)"
        />

        <template v-else>
          <span class="title">{{ room.title }}</span>
          <span v-if="room.unread" class="data fresh">+{{ room.unread }}</span>
          <span v-else-if="room.agents.length" class="data pinned">{{ room.agents.length }}</span>
          <button class="act" title="이름 변경" @click.stop="startRename(room)">✎</button>
          <button class="act del" title="대화 삭제" @click.stop="emit('remove', room.id)">×</button>
        </template>
      </li>
    </ul>

    <p v-if="!rooms.length" class="empty">
      아직 대화가 없습니다.<br />새 대화를 시작하면 여기에 쌓입니다.
    </p>
  </nav>
</template>

<style scoped>
.rail {
  width: 248px;
  flex: none;
  background: var(--rail);
  color: var(--rail-text);
  display: flex;
  flex-direction: column;
  padding: 18px 12px 12px;
}

.brand {
  padding: 0 8px 16px;
}
.wordmark {
  display: block;
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 5px;
  color: var(--rail-muted);
}
.status i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #4a5270;
}
.status i.live {
  background: var(--accent-on-rail);
  box-shadow: 0 0 0 3px rgba(79, 209, 197, 0.15);
}

.new {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #2c3454;
  border-radius: 8px;
  background: var(--rail-hi);
  color: #dfe4f0;
  cursor: pointer;
  font-size: 13px;
  transition:
    background 0.15s,
    border-color 0.15s;
}
.new:hover {
  background: #253055;
  border-color: var(--accent-on-rail);
}
.plus {
  color: var(--accent-on-rail);
  font-size: 15px;
  line-height: 1;
}

.section {
  padding: 0 8px;
  margin: 20px 0 6px;
  color: var(--rail-muted);
}

ul {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  flex: 1;
}
li {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  position: relative;
  transition: background 0.12s;
}
li:hover {
  background: rgba(255, 255, 255, 0.05);
}
li.active {
  background: rgba(79, 209, 197, 0.1);
  color: #fff;
}

/* 스케줄이 남긴 결과를 아직 안 본 방.
   레일이 어두우니 밝기를 올리는 것만으로 충분히 눈에 띈다.
   방을 열면 서버의 unread 가 0 이 되어 저절로 원래대로 돌아간다. */
li.unread {
  color: #fff;
  font-weight: 600;
}
.bell {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--accent-on-rail);
  box-shadow: 0 0 0 3px rgba(79, 209, 197, 0.18);
  animation: breathe 2.4s ease-in-out infinite;
}
@keyframes breathe {
  50% {
    box-shadow: 0 0 0 5px rgba(79, 209, 197, 0);
  }
}
.fresh {
  flex: none;
  color: var(--rail);
  background: var(--accent-on-rail);
  border-radius: 20px;
  padding: 1px 7px;
  font-weight: 700;
}
/* 선택된 방은 왼쪽에 강조 표시를 붙인다 */
li.active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--accent-on-rail);
  border-radius: 0 2px 2px 0;
}
.title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 이 방에 고정해 둔 에이전트 수 */
.pinned {
  color: var(--rail-muted);
  flex: none;
}
.pinned::after {
  content: '개';
}
/* 이름 변경·삭제. 평소에는 숨어 있다가 그 줄에 마우스를 올리면 나온다. */
.act {
  border: none;
  background: none;
  color: var(--rail-muted);
  cursor: pointer;
  line-height: 1;
  padding: 0 2px;
  opacity: 0;
  flex: none;
  font-size: 13px;
}
.del {
  font-size: 16px;
}
li:hover .act,
.act:focus-visible {
  opacity: 1;
}
.act:hover {
  color: #fff;
}
.del:hover {
  color: #ff9a90;
}

/* 제목 자리를 그대로 대신한다. 줄 높이가 흔들리면 목록이 출렁인다. */
.rename {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--accent-on-rail);
  border-radius: 5px;
  background: var(--rail-hi);
  color: #fff;
  font-size: 13px;
  font-family: inherit;
  padding: 1px 6px;
  margin: -2px 0;
}
.rename:focus {
  outline: none;
}

.empty {
  font-size: 12px;
  color: var(--rail-muted);
  padding: 4px 10px;
  line-height: 1.7;
}
</style>
