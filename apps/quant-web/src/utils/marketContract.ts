export function isSyntheticFuturesContract(contract: string | null | undefined): boolean {
  const normalized = (contract || '').trim().toUpperCase()
  if (!normalized) return true
  if (normalized.endsWith('.MAIN')) return true

  const match = /^([A-Z]+)(\d+)$/.exec(normalized)
  if (!match) return false

  const digits = match[2]
  if (digits === '88' || digits === '99') return true
  if (digits.length >= 3 && /^8+$/.test(digits)) return true
  if (digits.length >= 3 && /^9+$/.test(digits)) return true
  return false
}

export function resolveActualContract(
  symbol: string | null | undefined,
  contract: string | null | undefined,
  dominants: Array<{ product: string; actual_contract: string }>,
): string | null {
  const product = (symbol || '').trim().toLowerCase()
  const dominant = dominants.find((item) => item.product === product)
  if (!contract || isSyntheticFuturesContract(contract)) {
    return dominant?.actual_contract || contract || null
  }
  return contract
}
