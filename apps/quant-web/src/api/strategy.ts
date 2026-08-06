import { getStrategyRegistry } from './dashboard'
import type { StrategyInfo } from '@/types/strategy'

/** 获取策略 registry 的只读研究视图。 */
export function getStrategies() {
  return getStrategyRegistry().then((response) =>
    response.items.map((item) => ({
      id: item.strategy_code,
      name: item.name,
      type: (item.is_v1b ? 'trend' : 'pattern') as StrategyInfo['type'],
      status: 'running' as const,
      createdAt: '',
      updatedAt: '',
      description: item.description,
      params: {},
    })),
  )
}

/** 获取策略详情，不暴露已退役的回测能力。 */
export function getStrategyDetail(id: string) {
  return getStrategyRegistry().then((response) => {
    const item = response.items.find((entry) => entry.strategy_code === id)
    if (!item) throw new Error('strategy not found')
    return {
      id: item.strategy_code,
      name: item.name,
      type: (item.is_v1b ? 'trend' : 'pattern') as StrategyInfo['type'],
      status: 'running' as const,
      createdAt: '',
      updatedAt: '',
      description: item.description,
      params: {},
    }
  })
}
