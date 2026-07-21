/**
 * 判断是否为合成/连续合约（非具体交割月合约）。
 * 包括 .MAIN、88/99 指数合约及全 8/全 9 数字后缀。
 */
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

/**
 * 解析实际交割合约：合成合约时回退到主力合约列表中的 actual_contract。
 */
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
