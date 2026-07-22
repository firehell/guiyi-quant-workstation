import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { getRuntimeHealth } from '@/api/runtime'
import type { RuntimeHealth } from '@/types/runtime'
import { toSafeApiError } from '@/utils/errorRedaction'
import { RUNTIME_PULSE_STALE_MS, shouldRefreshRuntimePulse } from '@/utils/runtimePulse'

export const useRuntimePulseStore = defineStore('runtime-pulse', () => {
  const health = shallowRef<RuntimeHealth | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const loadedAt = ref(0)
  let inFlight: Promise<RuntimeHealth | null> | null = null
  let timer: number | null = null
  let started = false

  const status = computed(() => health.value?.status ?? 'unknown')
  const generatedAt = computed(() => health.value?.generated_at ?? null)

  async function refresh(force = false): Promise<RuntimeHealth | null> {
    if (inFlight) return inFlight
    if (
      !force &&
      !shouldRefreshRuntimePulse({
        visible: typeof document === 'undefined' || document.visibilityState === 'visible',
        inFlight: false,
        now: Date.now(),
        loadedAt: loadedAt.value,
      })
    ) {
      return health.value
    }

    loading.value = true
    error.value = null
    inFlight = getRuntimeHealth()
      .then((snapshot) => {
        health.value = snapshot
        loadedAt.value = Date.now()
        return snapshot
      })
      .catch((err: unknown) => {
        error.value = toSafeApiError(err, '加载运行状态失败')
        return null
      })
      .finally(() => {
        loading.value = false
        inFlight = null
      })
    return inFlight
  }

  function handleVisibilityChange() {
    if (document.visibilityState === 'visible') void refresh()
  }

  function start() {
    if (started || typeof window === 'undefined') return
    started = true
    document.addEventListener('visibilitychange', handleVisibilityChange)
    timer = window.setInterval(() => void refresh(), RUNTIME_PULSE_STALE_MS)
    void refresh()
  }

  function stop() {
    if (!started || typeof window === 'undefined') return
    started = false
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    if (timer !== null) window.clearInterval(timer)
    timer = null
  }

  return { health, loading, error, loadedAt, status, generatedAt, refresh, start, stop }
})
