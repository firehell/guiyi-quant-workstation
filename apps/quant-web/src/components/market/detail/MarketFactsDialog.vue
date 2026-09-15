<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import MarketDetailIcon from './MarketDetailIcon.vue'

const props = defineProps<{
  open: boolean
  title: string
  identityKey: string
}>()

const emit = defineEmits<{ close: [] }>()

const dialog = ref<HTMLDialogElement | null>(null)
let opener: HTMLElement | null = null
let generation = 0
let closing = false
let scrollLocks: Array<{ element: HTMLElement; overflow: string; top: number; left: number }> = []

function unlockScroll() {
  for (const lock of scrollLocks) {
    lock.element.style.overflow = lock.overflow
    lock.element.scrollTop = lock.top
    lock.element.scrollLeft = lock.left
  }
  scrollLocks = []
}

function lockScroll() {
  let element = dialog.value?.parentElement ?? null
  while (element) {
    if (element === document.scrollingElement || /(auto|scroll)/.test(getComputedStyle(element).overflowY)) {
      scrollLocks.push({ element, overflow: element.style.overflow, top: element.scrollTop, left: element.scrollLeft })
      element.style.overflow = 'hidden'
    }
    element = element.parentElement
  }
}

watch(() => [props.open, props.identityKey] as const, async ([open, identity], prior) => {
  const current = ++generation
  const identityChanged = Boolean(prior && prior[1] !== identity)
  if (!open || identityChanged) {
    closing = true
    dialog.value?.close()
    unlockScroll()
    if (!open && prior?.[1] === identity && opener?.isConnected) opener.focus({ preventScroll: true })
    opener = null
    if (identityChanged && prior?.[0]) emit('close')
    closing = false
    return
  }

  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  if (generation === current && props.open && dialog.value && !dialog.value.open) {
    lockScroll()
    dialog.value.showModal()
  }
}, { immediate: true, flush: 'post' })

function trapTab(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = [...dialog.value.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex]')]
    .filter(element => element.tabIndex >= 0 && !element.hasAttribute('disabled') && element.getClientRects().length > 0)
  const first = focusable[0]
  const last = focusable.at(-1)
  if (!first || !last) {
    event.preventDefault()
    dialog.value.focus()
    return
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function close() {
  emit('close')
}

function backdrop(event: MouseEvent) {
  const dialogElement = dialog.value
  if (!dialogElement || event.target !== dialogElement) return
  const bounds = dialogElement.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close()
}

onBeforeUnmount(() => {
  ++generation
  closing = true
  dialog.value?.close()
  unlockScroll()
  opener = null
})
</script>

<template>
  <dialog
    ref="dialog"
    class="market-facts-dialog"
    aria-labelledby="market-facts-dialog-title"
    @cancel.prevent="close"
    @close="!closing && open && close()"
    @click="backdrop"
    @keydown="trapTab"
  >
    <header class="market-facts-dialog__header">
      <div class="market-facts-dialog__title-row">
        <h2 id="market-facts-dialog-title">{{ title }}</h2>
        <slot name="status" />
      </div>
      <button type="button" aria-label="关闭行情数据详情" autofocus @click="close">
        <MarketDetailIcon name="close" :size="18" />
      </button>
    </header>
    <div class="market-facts-dialog__body"><slot /></div>
  </dialog>
</template>

<style scoped>
.market-facts-dialog { width: min(520px, calc(100vw - 32px)); box-sizing: border-box; margin: auto; max-height: calc(100dvh - 48px); padding: 0; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-detail-card-bg); color: var(--gy-text-primary); box-shadow: 0 24px 70px #0003; }
.market-facts-dialog[open] { display: flex; flex-direction: column; overflow: hidden; }
.market-facts-dialog::backdrop { background: #17202c66; }
.market-facts-dialog__header { display: flex; align-items: center; justify-content: space-between; gap: var(--gy-space-3); padding: var(--gy-space-4) var(--gy-space-5); border-bottom: 1px solid var(--gy-border); flex-shrink: 0; }
.market-facts-dialog__title-row { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; }
.market-facts-dialog h2 { margin: 0; font-size: var(--gy-font-size-lg); }
.market-facts-dialog button { display: grid; place-items: center; flex: 0 0 auto; width: 36px; height: 36px; padding: 0; border: 0; border-radius: var(--gy-radius-md); color: var(--gy-text-muted); background: var(--gy-bg-hover); cursor: pointer; }
.market-facts-dialog button:hover { color: var(--gy-text-primary); }
.market-facts-dialog button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.market-facts-dialog__body { min-height: 0; padding: var(--gy-space-4) var(--gy-space-5) var(--gy-space-5); overflow: auto; overflow-wrap: anywhere; }

@media (max-width: 480px) {
  .market-facts-dialog__header { padding: var(--gy-space-3) var(--gy-space-4); }
  .market-facts-dialog__body { padding: var(--gy-space-3) var(--gy-space-4) var(--gy-space-4); }
}
</style>
