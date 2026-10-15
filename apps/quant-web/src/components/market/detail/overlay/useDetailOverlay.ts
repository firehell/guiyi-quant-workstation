import './detailOverlay.css'
import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

type ScrollLock = { count: number; overflow: string; top: number; left: number }
const scrollLocks = new Map<HTMLElement, ScrollLock>()
const overlays: symbol[] = []

/** Each owner releases only its own locks; nested overlays retain the original scroll position. */
export function lockOverlayScroll(panel: HTMLElement): () => void {
  const elements = new Set<HTMLElement>([document.body, document.scrollingElement as HTMLElement])
  for (let element = panel.parentElement; element; element = element.parentElement) {
    if (scrollLocks.has(element) || /(auto|scroll)/.test(getComputedStyle(element).overflowY)) elements.add(element)
  }
  for (const element of elements) {
    const existing = scrollLocks.get(element)
    if (existing) existing.count++
    else {
      scrollLocks.set(element, { count: 1, overflow: element.style.overflow, top: element.scrollTop, left: element.scrollLeft })
      element.style.overflow = 'hidden'
    }
  }
  let released = false
  return () => {
    if (released) return
    released = true
    for (const element of elements) {
      const lock = scrollLocks.get(element)!
      if (--lock.count > 0) continue
      element.style.overflow = lock.overflow
      element.scrollTop = lock.top
      element.scrollLeft = lock.left
      scrollLocks.delete(element)
    }
  }
}

function focusableElements(panel: HTMLElement): HTMLElement[] {
  return [...panel.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex]')]
    .filter(element => element.tabIndex >= 0 && !element.matches(':disabled, [inert]') && element.getClientRects().length > 0)
}

export function useDetailOverlay(options: {
  panel: Ref<HTMLElement | null>
  open: () => boolean
  identity?: () => string
  native?: boolean
  close: () => void
}) {
  const owner = Symbol('detail-overlay')
  let generation = 0
  let pendingCloses = 0
  let releaseScroll: (() => void) | undefined
  let opener: HTMLElement | null = null
  let active = false

  function deactivate(restoreFocus: boolean) {
    const panel = options.panel.value
    if (options.native && panel instanceof HTMLDialogElement && panel.open) {
      // HTMLDialogElement.close() queues its close event; it can arrive after a new showModal().
      pendingCloses++
      panel.close()
    }
    const index = overlays.indexOf(owner)
    const wasTop = index === overlays.length - 1
    if (index >= 0) overlays.splice(index, 1)
    releaseScroll?.()
    releaseScroll = undefined
    document.removeEventListener('keydown', onKeydown)
    active = false
    if (restoreFocus && wasTop && opener?.isConnected) opener.focus({ preventScroll: true })
    opener = null
  }

  function onKeydown(event: KeyboardEvent) {
    if (!active || overlays.at(-1) !== owner) return
    // Native dialog cancel handles Escape; prevent the drawer behind it from also closing.
    if (event.key === 'Escape' && !options.native) {
      event.preventDefault()
      options.close()
    }
    if (event.key !== 'Tab' || !options.panel.value) return
    const panel = options.panel.value
    const elements = focusableElements(panel)
    const first = elements[0]
    const last = elements.at(-1)
    if (!first || !last) { event.preventDefault(); panel.focus(); return }
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
      event.preventDefault(); first.focus()
    }
  }

  watch(() => [options.open(), options.identity?.()] as const, async ([open, identity], prior) => {
    const current = ++generation
    const identityChanged = Boolean(prior && prior[1] !== identity)
    if (!open || identityChanged) {
      deactivate(!identityChanged)
      if (identityChanged && open) options.close()
      return
    }
    if (active) return
    opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (current !== generation || !options.open() || !options.panel.value) return
    const panel = options.panel.value
    releaseScroll = lockOverlayScroll(panel)
    overlays.push(owner)
    active = true
    document.addEventListener('keydown', onKeydown)
    if (options.native && panel instanceof HTMLDialogElement) panel.showModal()
    else (focusableElements(panel)[0] ?? panel).focus({ preventScroll: true })
  }, { immediate: true, flush: 'post' })

  function onNativeClose() {
    if (pendingCloses > 0) { pendingCloses--; return }
    if (active && options.open()) options.close()
  }

  function onBackdrop(event: MouseEvent) {
    const panel = options.panel.value
    if (!panel || event.target !== panel) return
    const bounds = panel.getBoundingClientRect()
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) options.close()
  }

  onBeforeUnmount(() => { ++generation; deactivate(true) })
  return { onNativeClose, onBackdrop }
}
