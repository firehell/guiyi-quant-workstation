import { isLocalBacktestHostname, mapBacktestError } from '../api/backtests.ts'
export { isLocalBacktestHostname } from '../api/backtests.ts'
import type {
  BacktestCapability,
  BacktestFormErrors,
  BacktestHealth,
  BacktestHttpErrorCode,
  BacktestParameterDescriptor,
  BacktestRunDetail,
  BacktestRunForm,
  BacktestSafeError,
  BacktestStrategy,
} from '../types/backtest.ts'


export const BACKTEST_POLL_INTERVAL_MS = 2000

const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'timed_out', 'interrupted'])
const DECIMAL_PATTERN = /^-?(?:\d+(?:\.\d*)?|\.\d+)$/

export async function probeBacktestCapability(
  hostname: string,
  probe: () => Promise<BacktestHealth>,
): Promise<BacktestCapability> {
  if (!isLocalBacktestHostname(hostname)) {
    return {
      kind: 'remote_blocked',
      showMenu: false,
      canStart: false,
      health: null,
      error: null,
    }
  }

  try {
    const health = await probe()
    const canStart = health.status === 'ready' && !health.busy
    return {
      kind: canStart ? 'ready' : 'local_unavailable',
      showMenu: true,
      canStart,
      health,
      error: canStart ? null : safeHealthError(health),
    }
  } catch (error) {
    return {
      kind: 'local_unavailable',
      showMenu: true,
      canStart: false,
      health: null,
      error: mapBacktestError(error),
    }
  }
}

export function validateBacktestForm(
  form: BacktestRunForm,
  strategy: BacktestStrategy,
): BacktestFormErrors {
  const errors: BacktestFormErrors = {}
  if (form.strategyId !== strategy.id) {
    errors.strategyId = '请选择有效的注册策略。'
  }
  if (!strategy.supported_frequencies.includes(form.frequency)) {
    errors.frequency = '该策略不支持所选频率。'
  }
  if (!isIsoDate(form.startDate) || !isIsoDate(form.endDate)) {
    errors.dateRange = '请输入有效的 ISO 日期。'
  } else if (form.startDate > form.endDate) {
    errors.dateRange = '开始日期不能晚于结束日期。'
  }
  if (
    (form.frequency === '1d' && form.matchingType !== 'current_bar')
    || (form.frequency === '1m' && !['current_bar', 'next_bar'].includes(form.matchingType))
  ) {
    errors.matchingType = form.frequency === '1d'
      ? '1d 只支持 current_bar 撮合。'
      : '1m 只支持 current_bar 或 next_bar 撮合。'
  }
  if (!['PriceRatioSlippage', 'TickSizeSlippage'].includes(form.slippageModel)) {
    errors.slippageModel = '只支持注册的滑点模型。'
  }

  requireDecimal(form.futureCash, true, 'futureCash', '初始资金', errors)
  requireDecimal(form.marginMultiplier, true, 'marginMultiplier', '保证金倍数', errors)
  requireDecimal(
    form.futuresCommissionMultiplier,
    false,
    'futuresCommissionMultiplier',
    '手续费倍数',
    errors,
  )
  requireDecimal(form.slippage, false, 'slippage', '滑点', errors)

  const registeredParameters = new Set(strategy.parameters.map(({ name }) => name))
  for (const descriptor of strategy.parameters) {
    validateParameter(descriptor, form.parameters[descriptor.name], errors)
  }
  for (const name of Object.keys(form.parameters)) {
    if (!registeredParameters.has(name)) {
      errors[`parameters.${name}`] = `参数 ${name} 未在策略注册表中。`
    }
  }
  return errors
}

export interface PollScheduler {
  setTimeout(callback: () => void, delay: number): unknown
  clearTimeout(handle: unknown): void
}

export interface BacktestPollerOptions {
  scheduler?: PollScheduler
  onError?: (error: BacktestSafeError) => void
}

export class BacktestPoller {
  private readonly fetchRun: (runId: string) => Promise<BacktestRunDetail>
  private readonly onUpdate: (run: BacktestRunDetail) => void
  private readonly scheduler: PollScheduler
  private readonly onError?: (error: BacktestSafeError) => void
  private timer: unknown
  private generation = 0
  private active = false
  private disposed = false

  constructor(
    fetchRun: (runId: string) => Promise<BacktestRunDetail>,
    onUpdate: (run: BacktestRunDetail) => void,
    options: BacktestPollerOptions = {},
  ) {
    this.fetchRun = fetchRun
    this.onUpdate = onUpdate
    this.scheduler = options.scheduler ?? browserScheduler
    this.onError = options.onError
  }

  get isPolling() {
    return this.active
  }

  start(runId: string) {
    if (this.disposed) return
    this.stop()
    this.active = true
    const generation = this.generation
    void this.tick(runId, generation)
  }

  stop() {
    this.active = false
    this.generation += 1
    if (this.timer !== undefined) {
      this.scheduler.clearTimeout(this.timer)
      this.timer = undefined
    }
  }

  dispose() {
    this.disposed = true
    this.stop()
  }

  private async tick(runId: string, generation: number) {
    try {
      const run = await this.fetchRun(runId)
      if (!this.isCurrent(generation)) return
      this.onUpdate(run)
      if (!this.isCurrent(generation)) return
      if (TERMINAL_STATUSES.has(run.status)) {
        this.stop()
        return
      }
    } catch (error) {
      if (!this.isCurrent(generation)) return
      this.onError?.(mapBacktestError(error))
    }
    if (!this.isCurrent(generation)) return
    this.timer = this.scheduler.setTimeout(() => {
      this.timer = undefined
      void this.tick(runId, generation)
    }, BACKTEST_POLL_INTERVAL_MS)
  }

  private isCurrent(generation: number) {
    return this.active && !this.disposed && this.generation === generation
  }
}

const browserScheduler: PollScheduler = {
  setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
}

function safeHealthError(health: BacktestHealth): BacktestSafeError {
  const code = health.error?.code ?? healthErrorCode(health)
  return mapBacktestError({ response: { data: { detail: { code } } } })
}

function healthErrorCode(health: BacktestHealth): BacktestHttpErrorCode {
  if (!health.registry_available) return 'REGISTRY_INVALID'
  if (!health.bundle_available) return 'BUNDLE_UNAVAILABLE'
  if (!health.runner.available) return 'RUNNER_UNAVAILABLE'
  return health.busy ? 'BACKTEST_ALREADY_RUNNING' : 'BACKTEST_LOCAL_UNAVAILABLE'
}

function requireDecimal(
  value: unknown,
  strictlyPositive: boolean,
  field: string,
  label: string,
  errors: BacktestFormErrors,
) {
  if (!isDecimalString(value) || (strictlyPositive ? compareDecimal(value, '0') <= 0 : compareDecimal(value, '0') < 0)) {
    const comparison = strictlyPositive ? '大于 0' : '大于等于 0'
    errors[field] = `${label}必须是${comparison} 的十进制字符串。`
  }
}

function validateParameter(
  descriptor: BacktestParameterDescriptor,
  value: unknown,
  errors: BacktestFormErrors,
) {
  const field = `parameters.${descriptor.name}`
  if (descriptor.type === 'integer') {
    const minimum = typeof descriptor.minimum === 'number' ? descriptor.minimum : undefined
    const maximum = typeof descriptor.maximum === 'number' ? descriptor.maximum : undefined
    if (
      typeof value !== 'number'
      || !Number.isInteger(value)
      || (minimum !== undefined && value < minimum)
      || (maximum !== undefined && value > maximum)
    ) {
      errors[field] = `参数 ${descriptor.name} 必须是 ${minimum ?? '-∞'} 到 ${maximum ?? '+∞'} 之间的整数。`
    }
    return
  }
  if (descriptor.type === 'decimal') {
    const minimum = typeof descriptor.minimum === 'string' ? descriptor.minimum : undefined
    const maximum = typeof descriptor.maximum === 'string' ? descriptor.maximum : undefined
    if (
      !isDecimalString(value)
      || (minimum !== undefined && compareDecimal(value, minimum) < 0)
      || (maximum !== undefined && compareDecimal(value, maximum) > 0)
    ) {
      errors[field] = `参数 ${descriptor.name} 必须是 ${minimum ?? '-∞'} 到 ${maximum ?? '+∞'} 之间的十进制字符串。`
    }
    return
  }
  if (descriptor.type === 'boolean') {
    if (typeof value !== 'boolean') {
      errors[field] = `参数 ${descriptor.name} 必须是布尔值。`
    }
    return
  }
  if (typeof value !== 'string' || !descriptor.options.includes(value)) {
    errors[field] = `参数 ${descriptor.name} 必须选择注册选项。`
  }
}

function isIsoDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return false
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1) return false
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return day <= (daysInMonth[month - 1] ?? 0)
}

function isDecimalString(value: unknown): value is string {
  return typeof value === 'string' && DECIMAL_PATTERN.test(value)
}

function compareDecimal(left: string, right: string) {
  const a = decimalParts(left)
  const b = decimalParts(right)
  if (a.negative !== b.negative) return a.negative ? -1 : 1
  const scale = Math.max(a.scale, b.scale)
  const aDigits = `${a.digits}${'0'.repeat(scale - a.scale)}`.replace(/^0+(?=\d)/, '')
  const bDigits = `${b.digits}${'0'.repeat(scale - b.scale)}`.replace(/^0+(?=\d)/, '')
  const magnitude = aDigits.length === bDigits.length
    ? aDigits.localeCompare(bDigits)
    : aDigits.length < bDigits.length ? -1 : 1
  return a.negative ? -magnitude : magnitude
}

function decimalParts(value: string) {
  const negative = value.startsWith('-') && !/^-(?:0+(?:\.0*)?|\.0+)$/.test(value)
  const unsigned = value.replace(/^-/, '')
  const [integer = '', fraction = ''] = unsigned.split('.')
  return {
    negative,
    digits: `${integer || '0'}${fraction}`,
    scale: fraction.length,
  }
}
