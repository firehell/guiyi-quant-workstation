/** Exact candidate cutoff comparison; JS Date alone truncates fractional seconds. */
export function previewInstant(value: string): bigint | null {
  const match = /^(\d{4}-\d{2}-\d{2})T((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value)
  if (!match) return null
  const base = Date.parse(`${match[1]}T${match[2]}${match[4]}`)
  const day = Date.parse(`${match[1]}T00:00:00Z`)
  if (!Number.isFinite(base) || !Number.isFinite(day) || new Date(day).toISOString().slice(0, 10) !== match[1]) return null
  return BigInt(base) * 1_000_000n + BigInt((match[3] ?? '').padEnd(9, '0'))
}
