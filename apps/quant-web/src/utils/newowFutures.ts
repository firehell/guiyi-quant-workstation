import type { MarketDetailIdentity } from '../types/marketDetail.ts'
export type FuturesVariant = 'trend' | 'oscillation' | 'dual_fusion' | 'main_rise' | 'osc-test' | 'osc-test2' | 'osc-test3' | 'osc-test4'
export function futuresVariant(identity: MarketDetailIdentity): FuturesVariant {
  return identity.newowTest ?? (identity.newowMode === 'dual' ? 'dual_fusion' : identity.strategy ?? 'trend')
}
export function switchFuturesModel(identity: MarketDetailIdentity, enabled: boolean): MarketDetailIdentity {
  const { strategyModel: _, homeContext: _home, focusBarEnd: _focus, ...rest } = identity
  return { ...rest, ...(enabled ? { strategyModel: 'futures_bidir_v1' as const } : {}) }
}
/** Routing retains unsupported combinations so disabling futures never changes the chosen period. */
export function originalNewowCombinationSupported(identity: MarketDetailIdentity): boolean {
  return !(identity.strategy === 'main_rise' && ['5m','15m','30m'].includes(identity.frequency))
}
