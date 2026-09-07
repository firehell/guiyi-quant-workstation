<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
const props = defineProps<{ open: boolean; title: string; identityKey: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
let opener: HTMLElement | null = null
let generation = 0
let closing = false
let scrollLocks: Array<{ element: HTMLElement; overflow: string; top: number; left: number }> = []
function unlockScroll() {
  for (const lock of scrollLocks) {
    lock.element.style.overflow = lock.overflow
    lock.element.scrollTop = lock.top; lock.element.scrollLeft = lock.left
  }
  scrollLocks = []
}
function lockScroll() {
  let element = dialog.value?.parentElement ?? null
  while (element) {
    if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) {
      scrollLocks.push({ element, overflow: element.style.overflow, top: element.scrollTop, left: element.scrollLeft })
      element.style.overflow = 'hidden'
    }
    element = element.parentElement
  }
}
watch(() => [props.open, props.identityKey] as const, async ([open, identity], prior) => {
  const current = ++generation
  if (!open || (prior && prior[1] !== identity)) {
    closing = true
    dialog.value?.close()
    unlockScroll()
    if (!open && prior?.[1] === identity && opener?.isConnected) opener.focus({ preventScroll: true })
    opener = null
    closing = false
    return
  }
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  if (generation === current && props.open && dialog.value && !dialog.value.open) { lockScroll(); dialog.value.showModal() }
}, { immediate: true, flush: 'post' })
function trapTab(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = [...dialog.value.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex]')]
    .filter(element => element.tabIndex >= 0 && !element.hasAttribute('disabled') && element.getClientRects().length > 0)
  const first = focusable[0]; const last = focusable.at(-1)
  if (!first || !last) { event.preventDefault(); dialog.value.focus(); return }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
function close() { emit('close') }
function backdrop(event: MouseEvent) {
  if (event.target !== dialog.value) return
  const bounds = dialog.value!.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close()
}
onBeforeUnmount(() => { ++generation; closing = true; dialog.value?.close(); unlockScroll(); opener = null })
</script>
<template>
  <dialog ref="dialog" class="newow-detail-dialog" aria-labelledby="newow-dialog-title" @cancel.prevent="close" @close="!closing && open && close()" @click="backdrop" @keydown="trapTab">
    <header><h2 id="newow-dialog-title">{{ title }}</h2><button type="button" aria-label="关闭解释" autofocus @click="close">×</button></header>
    <div class="newow-detail-dialog__body"><slot /></div>
    <footer><button type="button" @click="close">知道了</button></footer>
  </dialog>
</template>
<style scoped>
.newow-detail-dialog { width:min(480px, calc(100vw - 32px)); box-sizing:border-box; margin:auto; max-height:calc(100dvh - 48px); padding:0; border:1px solid #ebedf0; border-radius:12px; background:#fff; color:#20242b; box-shadow:0 24px 70px #0003; }
.newow-detail-dialog[open] { display:flex; flex-direction:column; overflow:hidden; }
.newow-detail-dialog::backdrop { background:#17202c66; }
header, footer { display:flex; align-items:center; justify-content:space-between; padding:16px 20px; flex-shrink:0; }
h2 { margin:0; font-size:18px; }
.newow-detail-dialog__body { padding:0 20px; min-height:0; overflow:auto; overflow-wrap:anywhere; }
button { min-height:44px; min-width:44px; border:0; border-radius:7px; background:#fff4ee; color:#d94b10; cursor:pointer; }
footer { justify-content:center; } footer button { width:100%; }
</style>
