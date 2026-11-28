import type { Metric, ReplayMarker } from '@/api/backtestCenter'

export const statusLabels: Record<string, string> = {
  QUEUED: '排队', RUNNING: '运行中', CANCELING: '取消中', SUCCEEDED: '成功', FAILED: '失败',
  CANCELED: '已取消', TRIAL: '试验', QUALIFIED: '正式研究资格', UNVERIFIED: '未核验', UNAVAILABLE: '暂不可用',
  BLOCKED: '受阻', DOMAIN_OWNED: '独立领域', UNSUPPORTED: '暂不支持',
  OPEN: '未平仓', CLOSED: '已平仓', ROLLOVER_INTERRUPTED: '换月中断',
  train: '训练', test: '样本外测试', comparison: '比较', READY: '可读', PENDING: '待派工',
  TRAINING: '训练中', SELECTED: '已选参', INSUFFICIENT: '证据不足',
  INSUFFICIENT_EVIDENCE: '证据不足', DATA_INSUFFICIENT: '数据不足',
}

export const metricLabels: Record<string, string> = {
  net_return: '净累计收益', total_return: '累计收益', max_drawdown: '最大回撤', win_rate: '胜率',
  profit_loss_ratio: '盈亏比', profit_factor: '收益因子', trade_count: '有效交易数',
  closed_trades: '已平仓交易数', sharpe: '夏普比率', volatility: '波动率', annualized_return: '年化收益',
}

const ratios = new Set(['net_return', 'total_return', 'max_drawdown', 'win_rate', 'volatility', 'annualized_return'])
export const statusLabel = (value?: string | null) => value ? statusLabels[value] ?? value : '—'
export const displayValue = (value: unknown) => typeof value === 'number' || typeof value === 'string' ? String(value) : '—'
export const formatRatio = (value: number | string) => new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(Number(value))

export function metricValue(key: string, value?: Metric | number | string | null) {
  const raw = typeof value === 'object' && value !== null ? value.value : value
  if (raw == null) return '—'
  if (ratios.has(key) && Number.isFinite(Number(raw))) return formatRatio(raw)
  return String(raw)
}

export function safeLocalLink(value: string) {
  return value.startsWith('/') && !value.startsWith('//') && !value.includes('\\')
}

export const diagnosticLabels: Record<string, string> = {
  PLUS_INPUT_AND_EXECUTION_COVERAGE_REQUIRED: 'FU 试验须先验证 Plus 授权、原生分钟覆盖和成交资格。',
  OSCILLATION_SAME_BAR_POLICY_UNVERIFIED: '震荡同 Bar 执行政策待核验。',
  MAIN_RISE_REDUCTION_POLICY_UNVERIFIED: '主升浪减仓政策待核验。',
  FUSION_INPUT_AND_EXECUTION_POLICY_UNVERIFIED: '双策略输入版本与融合执行政策待核验。',
  HTDY_LOOKBACK_REPAINTS: '原公式含回看重绘。',
  SUBING_DOMAIN_REPLAY_AND_PAPER: '沿用苏冰独立历史回放与共享 Paper。',
  PLUS_LICENSE_NOT_CONFIGURED: '本机 Plus 授权未配置。',
  PLUS_LICENSE_UNVERIFIED: '本机 Plus 授权未通过验证。',
  PLUS_LICENSE_SERVICE_UNREACHABLE: '本机无法连接 Plus 授权服务。',
  PLUS_LICENSE_OR_NATIVE_ADMISSION_UNVERIFIED: 'Plus 授权或原生模块未通过核验。',
  PLUS_ENGINE_NOT_INSTALLED: '指定执行环境缺少 RQAlpha Plus。',
  PLUS_EXECUTION_MINUTE_COVERAGE_MISSING: '原生执行分钟缺失。请核对合约和评价窗口。',
  PLUS_WARMUP_OR_EVALUATION_COVERAGE_MISSING: 'Plus 数据无法覆盖预热或评价窗口。',
  PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE: '当前 Plus 本地数据缺少按交易日生效的手续费和保证金依据。',
  PLUS_DECIMAL_RECONCILIATION_FAILED: '原生成交或结算未通过 Decimal 对账。',
  STRATEGY_PARAMETERS_UNSUPPORTED: '当前研究 Profile 暂不接受自定义参数。',
  ROLLOVER_INTERRUPTED: '原合约仍有未平仓仓位，回测在换月边界中断。',
  POINT_IN_TIME_RANK1_EVIDENCE_MISSING: '缺少当时可知的主力映射证据。',
  INPUT_VALIDATION_FAILED: '请核对配置字段及允许范围。',
  BACKTEST_CHECKPOINT_UNAVAILABLE: '这个 Run 没有可用的增量检查点。',
  BACKTEST_CHECKPOINT_INVALID: '归档的增量检查点未通过校验。',
  BACKTEST_CHECKPOINT_VERSION_CHANGED: '当前执行代码与生成检查点时的版本不同。',
  BACKTEST_CHECKPOINT_UNAUTHENTICATED: '无法核验增量检查点的来源和完整性。',
  BACKTEST_INCREMENTAL_PREFIX_CHANGED: '来源 Run 的区间数据已变化，无法沿原有边界延长。',
  BACKTEST_INCREMENTAL_NO_NEW_TRADING_DAY: '所选范围内没有可追加的交易日。',
  BACKTEST_INCREMENTAL_ENGINE_STATE_INVALID: '原生引擎状态无法从检查点恢复。',
  BACKTEST_INCREMENTAL_RERUN_UNAVAILABLE: '延长 Run 的原配置重跑不可用。',
  BACKTEST_EXTENSION_SOURCE_UNAVAILABLE: '来源 Run 缺少可用的检查点。',
  BACKTEST_EXTENSION_WINDOW_INVALID: '新的评价结束日须晚于来源结束日，并在允许的回测窗口内。',
  BACKTEST_EXTENSION_RESULT_INVALID: '追加范围与归档结果无法对账。',
  BACKTEST_EXTENSION_CHECKPOINT_INVALID: '新的检查点与归档交易日无法对账。',
  BACKTEST_INCREMENTAL_ENGINE_COVERAGE_MISMATCH: '原生引擎的实际执行范围与待追加窗口不一致。',
  NO_CLOSED_TRADES: '缺少已平仓交易',
  NO_WIN_TRADES: '缺少正净盈亏交易',
  NO_LOSS_TRADES: '缺少负净盈亏交易',
  RUN_CHART_WINDOW_UNAVAILABLE: '原修订的归档图窗不可重建。',
  RUN_CHART_EVIDENCE_MISMATCH: '归档图窗的输入或范围证据不一致。',
}
export const sampleLabels: Record<string, string> = { historical: '历史回测', experiment: '实验成员', train: '训练样本', oos: '样本外' }
export const diagnosticLabel = (code: string) => diagnosticLabels[code] ?? code

export function replayMarkerLabel(marker: ReplayMarker) {
  const label = { ENTRY: '进场', EXIT: '出场', VALUATION: '估值' }[marker.kind]
  if (!label) return marker.label ?? marker.kind
  return [label, marker.quantity == null ? null : `${marker.quantity} 手`, marker.price].filter(value => value != null).join(' · ')
}
