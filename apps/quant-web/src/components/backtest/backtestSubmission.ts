const storagePrefix = 'guiyi.backtest.pending.'
const pending = new Map<string, string>()

function canonicalBody(body: unknown) {
  return JSON.stringify(body, (_, value: unknown) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return value
    return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)))
  })
}

/** Store a digest of the submitted body and the key until the server acknowledges it. */
export async function pendingRunRequest(action: 'submit' | 'rerun' | 'experiment', body: unknown) {
  const encoded = new TextEncoder().encode(canonicalBody(body))
  const digest = await crypto.subtle.digest('SHA-256', encoded)
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  const scope = `${storagePrefix}${action}.${hex}`
  let stored: string | null = null
  try {
    stored = sessionStorage.getItem(scope)
  } catch {
    // A blocked session store still permits retrying within the current page session.
  }
  const key = pending.get(scope) ?? (stored && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(stored) ? stored : crypto.randomUUID())
  pending.set(scope, key)
  try {
    sessionStorage.setItem(scope, key)
  } catch {
    // Keep the key in memory for the current page session.
  }
  return {
    key,
    accepted() {
      if (pending.get(scope) === key) pending.delete(scope)
      try {
        if (sessionStorage.getItem(scope) === key) sessionStorage.removeItem(scope)
      } catch {
        // The acknowledgement already resolved the request in the current page session.
      }
    },
  }
}
