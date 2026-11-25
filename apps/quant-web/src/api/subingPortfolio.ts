export interface SubingPortfolioContract {
  contract: string
  valuation_at: string | null
  summary: { open_quantity: number }
  open_layers: { side: string }[]
  pending: { kind: string; at: string } | null
  fills: { fill_at: string; price: string; action: string; quantity?: number }[]
}

export interface SubingPortfolioStatus {
  run_id: string | null
  status: string
  worker_at?: string
  worker_code?: string | null
  observed_at?: string | null
  trading_day?: string | null
  day_net?: string | null
  products: { product: string; enabled: boolean; accounts: SubingPortfolioContract[] }[]
  account: {
    equity?: string
    policy?: { products?: string[] }
    pending_exit_contracts?: string[]
    valuation_unproven?: string[]
  }
  auto_order: false
}

export async function readSubingPortfolioStatus(signal: AbortSignal): Promise<SubingPortfolioStatus> {
  const response = await fetch('/api/v1/subing-portfolio/status', { signal })
  if (!response.ok) throw Error('PORTFOLIO_STATUS_UNAVAILABLE')
  const value: SubingPortfolioStatus = await response.json()
  if (!value || value.auto_order !== false || typeof value.status !== 'string'
    || (value.run_id !== null && !value.run_id) || !value.account
    || !Array.isArray(value.products) || value.products.some(product => !product || typeof product.product !== 'string'
      || typeof product.enabled !== 'boolean' || !Array.isArray(product.accounts)
      || product.accounts.some(account => !account || typeof account.contract !== 'string' || !Array.isArray(account.open_layers)
        || !Number.isSafeInteger(account.summary?.open_quantity) || account.summary.open_quantity < 0))) {
    throw Error('PORTFOLIO_STATUS_INVALID')
  }
  return value
}
