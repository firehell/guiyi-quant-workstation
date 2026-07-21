import request from './request'
import type { DashboardSummary, StrategyRegistryResponse } from '@/types/dashboard'

/** 获取 Dashboard 汇总（任务数、信号、运行健康等） */
export function getDashboardSummary() {
  return request.get<any, DashboardSummary>('/api/dashboard/summary')
}

/** 获取策略注册表（只读 registry） */
export function getStrategyRegistry() {
  return request.get<any, StrategyRegistryResponse>('/strategies/registry')
}
