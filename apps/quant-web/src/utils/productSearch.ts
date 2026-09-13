export interface ProductOption {
  symbol: string
  name: string
  contract: string | null
}

export interface ProductDirectoryLike {
  product: string
  product_name: string
  actual_contract?: string | null
}

export function normalizeProductOptions(items: readonly ProductDirectoryLike[]): ProductOption[] {
  const options = new Map<string, ProductOption>()
  for (const item of items) {
    const symbol = item.product.trim().toLowerCase()
    if (!/^[a-z]+$/.test(symbol) || options.has(symbol)) continue
    options.set(symbol, {
      symbol,
      name: item.product_name.trim() || symbol.toUpperCase(),
      contract: item.actual_contract?.trim().toUpperCase() || null,
    })
  }
  return [...options.values()].sort((left, right) => left.symbol.localeCompare(right.symbol))
}

export function searchProductOptions(
  options: readonly ProductOption[],
  query: string,
): ProductOption[] {
  const term = query.replace(/\s+/g, '').toLowerCase()
  if (!term) return [...options]
  return options.filter((option) => (
    option.symbol.toLowerCase().includes(term)
    || option.name.replace(/\s+/g, '').toLowerCase().includes(term)
  ))
}
