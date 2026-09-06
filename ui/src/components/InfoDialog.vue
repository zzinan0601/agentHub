<script setup>
// 당장 필요하지 않은 설명을 담아두는 창.
//
// 패널에 작은 글씨로 늘어놓으면 매번 눈에 걸리지만 정작 필요할 때는 잘 안 읽힌다.
// 필요한 사람이 눌러서 보게 하고, 패널에는 지금 상태를 나타내는 값만 남긴다.
//
// 브라우저 기본 <dialog> 를 쓴다. Esc 로 닫히고 포커스가 갇히는 동작을 공짜로 얻는다.
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  // 'wide' 는 워크플로우 편집기처럼 두 칸으로 나뉘는 창에 쓴다.
  size: { type: String, default: 'normal' },
})
const emit = defineEmits(['close'])

const el = ref(null)

watch(
  () => props.open,
  (isOpen) => {
    const dialog = el.value
    if (!dialog) return
    if (isOpen && !dialog.open) dialog.showModal()
    if (!isOpen && dialog.open) dialog.close()
  },
)

onBeforeUnmount(() => {
  if (el.value?.open) el.value.close()
})
</script>

<template>
  <!-- close 는 Esc 로 닫을 때도 발생한다. 바깥 클릭은 dialog 자신이 대상이 된다. -->
  <dialog ref="el" :class="size" @close="emit('close')" @click.self="emit('close')">
    <div class="inner">
      <header>
        <h3>{{ title }}</h3>
        <button class="x" aria-label="닫기" @click="emit('close')">×</button>
      </header>
      <div class="body">
        <slot />
      </div>
    </div>
  </dialog>
</template>

<style scoped>
dialog {
  border: none;
  border-radius: 12px;
  padding: 0;
  max-width: 460px;
  width: calc(100% - 48px);
  background: var(--surface);
  color: var(--ink-900);
  box-shadow: 0 16px 48px rgba(18, 23, 42, 0.28);
}
dialog.wide {
  max-width: 880px;
}
dialog::backdrop {
  background: rgba(18, 23, 42, 0.45);
}
.inner {
  padding: 18px 20px 20px;
}
header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
h3 {
  font-size: 14px;
  font-weight: 650;
  margin: 0;
  margin-right: auto;
}
.x {
  border: none;
  background: none;
  color: var(--ink-400);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
.x:hover {
  color: var(--ink-900);
}
.body {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink-700);
  max-height: 68vh;
  overflow-y: auto;
}
dialog.wide .body {
  /* 편집기는 안쪽에서 스스로 스크롤을 나눠 쓴다 */
  max-height: 74vh;
  overflow: visible;
}
</style>
