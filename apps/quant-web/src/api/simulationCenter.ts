import request from './request'

interface Deployment {
  strategy_id: string
  formula_version: string
  profile_id: string
  risk_policy_version: string
  instruments: string[]
}

interface CabinetInstrument {
  id: string
  exchange: string
  contract: string
  direction: string
  quantity: number
}

interface Balance {
  equity: string
  available: string
  margin: string
  currency: string
}

interface Position extends CabinetInstrument {
  today: number
  yesterday: number
  frozen: number
  pnl: string
}

interface Order extends CabinetInstrument {
  offset: string
  filled: number
  price: string
  status: string
}

export interface Fill extends CabinetInstrument {
  order_id: string
  offset: string
  price: string
  occurred_at: string
  fee: string | null
}

export interface SimulationWorkspace {
  source: 'SIMNOW_CTP'
  status: 'AVAILABLE' | 'NOT_CONFIGURED'
  selected: string | null
  accounts: Array<{ alias: string; deployment: Deployment | null; status: string; status_at: string }>
  readback: {
    observed_at: string
    trading_day: string
    account: Balance
    positions: Position[]
    orders: Order[]
  } | null
  equity: Array<{ observed_at: string; equity: string }>
  fills: Fill[]
  next_fill: string | null
}

export function readSimulationWorkspace(signal: AbortSignal, account?: string, before?: string) {
  return request.get<unknown, SimulationWorkspace>('/simulations', { signal, params: { account, before } })
}
