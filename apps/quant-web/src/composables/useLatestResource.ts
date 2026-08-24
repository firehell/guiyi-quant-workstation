import { shallowRef } from 'vue'

interface LatestResourceOptions<T> {
  fetch: () => Promise<T>
  preserveOnError?: boolean
}

export function useLatestResource<T>(options: LatestResourceOptions<T>) {
  const data = shallowRef<T | null>(null)
  const loading = shallowRef(false)
  const failed = shallowRef(false)
  let generation = 0

  async function refresh() {
    const requestGeneration = ++generation
    loading.value = true
    failed.value = false
    try {
      const response = await options.fetch()
      if (requestGeneration !== generation) return
      data.value = response
    } catch {
      if (requestGeneration !== generation) return
      failed.value = true
      if (options.preserveOnError === false) data.value = null
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function invalidate() {
    generation += 1
    loading.value = false
  }

  return { data, loading, failed, refresh, invalidate }
}
