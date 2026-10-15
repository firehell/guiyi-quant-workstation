/** A 304 can only reuse a body validated during this browser session. */
export function createConditionalResource<T>(read: (etag?: string, signal?: AbortSignal) => Promise<{ status: number; data: unknown; etag?: string }>, normalize: (value: unknown) => T) {
  let accepted: { etag: string; value: T } | undefined
  let generation = 0
  return async (signal?: AbortSignal) => {
    const owner = accepted, current = ++generation
    const response = await read(owner?.etag, signal)
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (response.status === 304) {
      if (!owner) throw new Error('HOME_304_WITHOUT_VALIDATED_BODY')
      return structuredClone(owner.value)
    }
    if (response.status !== 200) throw new Error('HOME_UNEXPECTED_STATUS')
    const value = normalize(response.data)
    if (current === generation) accepted = response.etag ? { etag: response.etag, value: structuredClone(value) } : undefined
    return value
  }
}
