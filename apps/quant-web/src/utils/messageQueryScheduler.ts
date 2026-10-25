/** Coalesce search typing while letting Enter and filter changes submit immediately. */
export function createMessageQueryScheduler(submit: () => void, delay = 350) {
  let timer: ReturnType<typeof setTimeout> | undefined
  function cancel() { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  function schedule(immediate = false) {
    cancel()
    if (immediate) submit()
    else timer = setTimeout(() => { timer = undefined; submit() }, delay)
  }
  return { schedule, cancel }
}
