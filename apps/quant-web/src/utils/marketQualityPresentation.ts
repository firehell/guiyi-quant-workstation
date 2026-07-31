import type { MarketAccessMode } from '@/types/market'
import type { ContractViewMode } from '@/utils/marketChartWindow'
import { redactSensitiveText } from './errorRedaction.ts'

export type MarketQualityAction = 'evidence' | 'profile' | 'actual'

export interface MarketQualityImpactInput {
  qualityStatus: string | null | undefined
  warningReasons: string[]
  crossFileConflicts: number
  accessMode: MarketAccessMode
  profileId: string | null | undefined
  canonicalIdentity?: boolean
  strictResearchReady: boolean
  contractView: ContractViewMode
  dataMode: 'historical' | 'live'
  /** null 表示尚未完成 lineage 读取，不应提前制造告警。 */
  lineageReady: boolean | null
}

export interface MarketQualityImpact {
  severity: 'warning' | 'error'
  title: string
  reasons: string[]
  allowed: string[]
  blocked: string[]
  actions: MarketQualityAction[]
}

function safeReasons(values: string[]) {
  return [...new Set(values.map((value) => redactSensitiveText(value)).filter(Boolean))]
}

function availableActions(input: MarketQualityImpactInput): MarketQualityAction[] {
  const actions: MarketQualityAction[] = ['evidence']
  if (input.dataMode === 'historical' && !input.profileId && !input.canonicalIdentity) {
    actions.push('profile')
  }
  if (input.contractView === 'continuous') actions.push('actual')
  return actions
}

/**
 * 把后端 quality/Profile/lineage 事实翻译为可行动的影响说明。
 * 只生成展示模型，不改变数据读取顺序或研究资格。
 */
export function buildMarketQualityImpact(
  input: MarketQualityImpactInput,
): MarketQualityImpact | null {
  const status = (input.qualityStatus || 'unknown').toLowerCase()
  const reasons = safeReasons(input.warningReasons)

  if (status === 'failed') {
    return {
      severity: 'error',
      title: '数据质量未通过',
      reasons: safeReasons(['数据质量状态为 failed。', ...reasons]),
      allowed: ['查看质量与 lineage 证据'],
      blocked: ['当前数据用于研究、回测或信号输入'],
      actions: availableActions(input),
    }
  }

  if (input.accessMode === 'research' && !input.profileId && !input.canonicalIdentity) {
    return {
      severity: 'warning',
      title: '严格研究缺少 Profile',
      reasons: ['当前研究请求未绑定明确 Profile。'],
      allowed: ['选择 Profile 后重新校验'],
      blocked: ['K 线加载与严格研究资格'],
      actions: availableActions(input),
    }
  }

  const conflictReason =
    input.crossFileConflicts > 0
      ? `发现 ${input.crossFileConflicts.toLocaleString('zh-CN')} 个跨文件 OHLCV 冲突。`
      : null
  const lineageReason =
    input.lineageReady === false
      ? '当前读取缺少完整 lineage 资格证据。'
      : null
  const hasWarning =
    status === 'warning' ||
    input.crossFileConflicts > 0 ||
    input.lineageReady === false ||
    (input.accessMode === 'research' && !input.strictResearchReady)

  if (!hasWarning) return null

  return {
    severity: 'warning',
    title: '数据仅可观察',
    reasons: safeReasons([conflictReason || '', ...reasons, lineageReason || '']),
    allowed: ['浏览当前 K 线（仅供观察）', '查看质量与 lineage 证据'],
    blocked: ['严格研究', '当前 warning 数据作为正式回测或信号输入'],
    actions: availableActions(input),
  }
}
