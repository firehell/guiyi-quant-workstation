<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import MarketDetailIcon from './MarketDetailIcon.vue'

const props = defineProps<{
  open: boolean
  title: string
}>()

const emit = defineEmits<{
  close: []
}>()

const panel = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
let previousOverflow = ''
let bodyLocked = false

function focusableElements(): HTMLElement[] {
  if (!panel.value) return []
  return Array.from(panel.value.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
}

function onKeydown(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab') return
  const focusable = focusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    panel.value?.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

async function syncOpen(open: boolean) {
  if (open) {
    if (bodyLocked) return
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    bodyLocked = true
    document.addEventListener('keydown', onKeydown)
    await nextTick()
    ;(focusableElements()[0] ?? panel.value)?.focus()
    return
  }
  document.removeEventListener('keydown', onKeydown)
  if (bodyLocked) document.body.style.overflow = previousOverflow
  bodyLocked = false
  previousFocus?.focus()
  previousFocus = null
}

watch(() => props.open, syncOpen)
onMounted(() => syncOpen(props.open))

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  if (bodyLocked) document.body.style.overflow = previousOverflow
  previousFocus?.focus()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="detail-drawer" @mousedown.self="emit('close')">
      <section
        ref="panel"
        class="detail-drawer__panel"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <header>
          <h2>{{ title }}</h2>
          <button type="button" aria-label="关闭" @click="emit('close')">
            <MarketDetailIcon name="close" />
          </button>
        </header>
        <div class="detail-drawer__content"><slot /></div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.detail-drawer { position: fixed; inset: 0; z-index: 1200; display: grid; align-items: end; background: rgba(15, 31, 56, 0.34); }
.detail-drawer__panel { max-height: min(78vh, 680px); overflow: auto; border-radius: var(--gy-radius-xl) var(--gy-radius-xl) 0 0; background: var(--gy-bg-overlay); box-shadow: var(--gy-shadow-overlay); }
.detail-drawer__panel:focus { outline: none; }
.detail-drawer header { position: sticky; top: 0; display: flex; align-items: center; justify-content: space-between; gap: var(--gy-space-3); padding: var(--gy-space-3) var(--gy-space-4); border-bottom: 1px solid var(--gy-border); background: var(--gy-bg-overlay); }
.detail-drawer h2 { margin: 0; color: var(--gy-text-primary); font-size: var(--gy-font-size-lg); }
.detail-drawer button { display: inline-grid; min-width: 44px; min-height: 44px; place-items: center; border: 0; border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: transparent; cursor: pointer; }
.detail-drawer button:hover { background: var(--gy-bg-hover); }
.detail-drawer button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.detail-drawer__content { padding: var(--gy-space-4); }
</style>
