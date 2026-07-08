import request from './request'
import type { DashboardSummary, StrategyRegistryResponse } from '@/types/dashboard'

export function getDashboardSummary() {
  return request.get<any, DashboardSummary>('/api/dashboard/summary')
}

export function getStrategyRegistry() {
  return request.get<any, StrategyRegistryResponse>('/api/v1/strategies/registry')
}
