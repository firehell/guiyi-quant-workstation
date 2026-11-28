<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  cancelRun, diagnosticCode, extendRun, readEquity, readReport, readRun, readRunEvents, readTrades, rerun, runInProgress,
  type Equity, type EvidenceFields, type Run, type RunEvent, type RunRows, type Trade,
} from '@/api/backtestCenter'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import BacktestChart from './BacktestChart.vue'
import BacktestTradeReplay from './BacktestTradeReplay.vue'
import { pendingRunRequest } from './backtestSubmission'
import { diagnosticLabel, displayValue, metricLabels, metricValue, sampleLabels, statusLabel } from './backtestDisplay'

const props = defineProps<{ runId: string }>()
const router = useRouter()
const run = shallowRef<Run>()
const update = ref(0)
const error = ref('')
const actionError = ref('')
const busy = ref(false)
const extensionOpen = ref(false)
const extensionEnd = ref('')
const canExtend = computed(() => run.value?.status === 'SUCCEEDED' && run.value.can_extend === true)
const sourceRunId = computed(() => run.value?.incremental?.source_run_id ?? run.value?.source_run_id)
const rolloverInterruption = computed(() => {
  const current = run.value
  const mark = current?.interruption
  if (current?.status === 'FAILED' && current.diagnostic === 'ROLLOVER_INTERRUPTED'
    && mark?.status === 'ROLLOVER_INTERRUPTED' && mark.contract === current.config.contract) return mark
})
const loading = ref(false)
const tab = ref('overview')
const tabs = [
  ['overview', '概览'], ['equity', '资金曲线'], ['trades', '交易明细'], ['risk', '风险分析'], ['report', '报告'],
] as const
const pageSize = 50
const equityPage = shallowRef<RunRows<Equity>>()
const tradePage = shallowRef<RunRows<Trade>>()
const offset = ref(0)
const artifactLoading = ref(false)
const artifactError = ref('')
const report = shallowRef<EvidenceFields>()
const replayTrade = shallowRef<Trade>()
const events = shallowRef<RunEvent[]>([])
const eventsError = ref('')
const alive = new AbortController()

const overviewMetrics = ['net_return', 'max_drawdown', 'win_rate', 'profit_loss_ratio', 'profit_factor', 'trade_count']
const riskMetrics = ['max_drawdown', 'volatility', 'sharpe']
const metrics = computed(() => run.value?.summary?.metrics ?? {})
const requiredMetrics = computed(() => {
  const selected = tab.value === 'risk' ? riskMetrics : overviewMetrics
  const keys = tab.value === 'risk' ? selected : [...new Set([...selected, ...Object.keys(metrics.value)])]
  return keys.map(key => {
    const value = metrics.value[key]
    return { key, label: metricLabels[key] ?? key, value: metricValue(key, value), definition: value?.definition, source: value?.source, reason: value?.reason ?? (value?.value == null ? '本 Run 未提供可用指标' : null) }
  })
})
const resultTotal = computed(() => tab.value === 'equity' ? equityPage.value?.total ?? 0 : tradePage.value?.total ?? 0)
const eventCode = (value: string) => /^[A-Z0-9_]{1,100}$/.test(value) ? diagnosticLabel(value) : '无法显示'
const evidenceLabels: Record<string, string> = {
  source: '指标来源', sample_type: '样本类型', cost_basis: '成本口径', pairing_basis: '配对口径',
  benchmark: '基准', engine_version: '引擎版本', data_revision: '数据修订',
}

watch(update, async (_, __, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  error.value = ''
  eventsError.value = ''
  loading.value = true
  const details = readRun(props.runId, controller.signal).then(value => {
    if (controller.signal.aborted) return
    if (value.run_id !== props.runId) error.value = 'Run 详情身份不一致。'
    else run.value = value
  }, reason => {
    if (!controller.signal.aborted) error.value = diagnosticCode(reason) ?? 'Run 读取失败'
  }).finally(() => {
    if (!controller.signal.aborted) loading.value = false
  })
  const history = readRunEvents(props.runId, controller.signal).then(value => {
    if (controller.signal.aborted) return
    if (value.run_id !== props.runId) eventsError.value = '任务日志的 Run 身份不一致。'
    else if (!Array.isArray(value.items)) eventsError.value = '任务日志格式无效。'
    else events.value = value.items.slice(-32)
  }, reason => {
    if (!controller.signal.aborted) eventsError.value = diagnosticCode(reason) ?? '任务日志读取失败'
  })
  await Promise.all([details, history])
}, { immediate: true })

watch([tab, offset, () => run.value?.status], async ([section, start, status], _, onCleanup) => {
  if (status !== 'SUCCEEDED') return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  artifactError.value = ''
  if (section === 'equity') equityPage.value = undefined
  if (section === 'trades') tradePage.value = undefined
  artifactLoading.value = section === 'equity' || section === 'trades' || section === 'report'
  try {
    if (section === 'equity') {
      const value = await readEquity(props.runId, start, pageSize, controller.signal)
      if (controller.signal.aborted) return
      if (value.run_id !== props.runId) artifactError.value = '权益页的 Run 身份不一致。'
      else equityPage.value = value
    } else if (section === 'trades') {
      const value = await readTrades(props.runId, start, pageSize, controller.signal)
      if (controller.signal.aborted) return
      if (value.run_id !== props.runId) artifactError.value = '交易页的 Run 身份不一致。'
      else tradePage.value = value
    } else if (section === 'report') {
      const value = await readReport(props.runId, controller.signal)
      if (!controller.signal.aborted) report.value = value
    }
  } catch (reason) {
    if (!controller.signal.aborted) artifactError.value = diagnosticCode(reason) ?? '结果读取失败'
  } finally {
    if (!controller.signal.aborted) artifactLoading.value = false
  }
}, { immediate: true })

function change(tabId: string) {
  offset.value = 0
  tab.value = tabId
  replayTrade.value = undefined
}

async function act(action: 'cancel' | 'rerun') {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  try {
    if (action === 'cancel') {
      await cancelRun(props.runId)
      if (!alive.signal.aborted) update.value += 1
    } else {
      const pending = await pendingRunRequest('rerun', { source_run_id: props.runId })
      const result = await rerun(props.runId, pending.key)
      pending.accepted()
      if (!alive.signal.aborted) await router.push({ name: 'backtests', params: { runId: result.run_id } })
    }
  } catch (reason) {
    if (!alive.signal.aborted) {
      actionError.value = diagnosticCode(reason) ?? (action === 'rerun' ? '重跑提交未确认。再次点击将沿用原请求。' : '取消结果未确认，正在读取任务状态。')
      update.value += 1
    }
  } finally {
    busy.value = false
  }
}

async function requestExtension() {
  const source = run.value
  if (busy.value || !source || !canExtend.value) return
  const end = extensionEnd.value
  actionError.value = ''
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(end) || end <= source.config.end) {
    actionError.value = '新的评价结束日须晚于来源 Run 的评价结束日。'
    return
  }
  busy.value = true
  try {
    const pending = await pendingRunRequest('extend', { source_run_id: source.run_id, end })
    const child = await extendRun(source.run_id, end, pending.key)
    const parent = child.incremental?.source_run_id ?? child.source_run_id
    if (child.run_id === source.run_id || (parent && parent !== source.run_id)) {
      throw new Error('BACKTEST_SUBMISSION_UNCONFIRMED')
    }
    pending.accepted()
    if (!alive.signal.aborted) await router.push({ name: 'backtests', params: { runId: child.run_id } })
  } catch (reason) {
    if (!alive.signal.aborted) actionError.value = diagnosticCode(reason) ?? '延长提交未确认。再次提交相同结束日将沿用原请求。'
  } finally {
    busy.value = false
  }
}

let timer: number | undefined
onMounted(() => {
  timer = window.setInterval(() => {
    if (runInProgress(run.value?.status) && !busy.value && !loading.value) update.value += 1
  }, 4000)
})
onScopeDispose(() => {
  alive.abort()
  window.clearInterval(timer)
})
</script>

<template>
  <section v-if="run" aria-labelledby="bt-run-heading">
    <div class="bt-panel-header">
      <div>
        <h2 id="bt-run-heading">{{ run.config.strategy_id }} · {{ run.config.contract }} · {{ run.config.signal_frequency }}</h2>
        <p class="bt-id">Run {{ run.run_id }}</p>
      </div>
      <div class="bt-actions">
        <button class="bt-button" @click="update += 1">刷新状态</button>
        <button v-if="canExtend" class="bt-button" type="button" :disabled="busy" :aria-expanded="extensionOpen"
          @click="extensionOpen = !extensionOpen; actionError = ''">延长回测</button>
        <button v-if="run.status === 'QUEUED' || run.status === 'RUNNING'" class="bt-button" :disabled="busy" @click="act('cancel')">取消任务</button>
        <button v-if="!run.incremental && !runInProgress(run.status)" class="bt-button" :disabled="busy" @click="act('rerun')">按原配置重跑</button>
      </div>
    </div>
    <div class="bt-run-meta">
      <span class="bt-status" :data-status="run.status">{{ statusLabel(run.status) }}</span>
      <span>研究资格 {{ statusLabel(run.qualification) }}</span>
      <span v-if="run.phase">阶段 {{ run.phase }}</span>
      <time>{{ formatBeijingInstant(run.updated_at) }}</time>
      <RouterLink v-if="sourceRunId" :to="{ name: 'backtests', params: { runId: sourceRunId } }">来源 Run {{ sourceRunId }}</RouterLink>
    </div>
    <form v-if="canExtend && extensionOpen" class="bt-actions bt-extension" aria-label="延长回测" novalidate @submit.prevent="requestExtension">
      <p class="bt-note">来源 Run 评价结束日 <time :datetime="run.config.end">{{ run.config.end }}</time></p>
      <label>新的评价结束日 <input v-model="extensionEnd" type="date" required :disabled="busy" /></label>
      <button class="bt-button bt-primary" type="submit" :disabled="busy">{{ busy ? '正在提交' : '提交延长' }}</button>
    </form>
    <div v-if="run.incremental" role="region" aria-label="延长范围">
      <dl class="bt-facts">
        <dt>继承边界</dt><dd><time :datetime="run.incremental.through">{{ run.incremental.through }}</time></dd>
        <dt>评价结束日</dt><dd><time :datetime="run.config.end">{{ run.config.end }}</time></dd>
        <template v-if="run.incremental.appended_trading_days?.length">
          <dt>实际追加交易日</dt><dd>{{ run.incremental.appended_trading_days.join('、') }}</dd>
        </template>
        <template v-if="run.incremental.executed_minutes != null">
          <dt>追加执行分钟</dt><dd>{{ run.incremental.executed_minutes }} 分钟</dd>
        </template>
      </dl>
    </div>
    <p v-if="run.diagnostic" class="bt-alert" role="status">{{ diagnosticLabel(run.diagnostic) }}</p>
    <section v-if="rolloverInterruption" aria-labelledby="bt-rollover-heading">
      <h3 id="bt-rollover-heading">换月中断估值</h3>
      <dl class="bt-facts">
        <dt>原物理合约</dt><dd>{{ rolloverInterruption.contract }}</dd>
        <dt>中断交易日</dt><dd><time :datetime="rolloverInterruption.trading_day">{{ rolloverInterruption.trading_day }}</time></dd>
        <dt>未平仓仓位</dt><dd>多头 {{ rolloverInterruption.quantity }} 手</dd>
        <dt>原仓位进场</dt><dd><time :datetime="rolloverInterruption.entry_at">{{ rolloverInterruption.entry_at }}</time> · {{ rolloverInterruption.entry_price }}</dd>
        <dt>中断估值时点</dt><dd><time :datetime="rolloverInterruption.marked_at">{{ rolloverInterruption.marked_at }}</time></dd>
        <dt>原合约估值价</dt><dd>{{ rolloverInterruption.mark_price }}</dd>
        <dt>未实现盈亏</dt><dd>{{ rolloverInterruption.unrealized_pnl }}</dd>
      </dl>
    </section>
    <p v-if="error || actionError" class="bt-alert" role="alert">{{ diagnosticLabel(actionError || error) }}</p>
    <details v-if="events.length || eventsError" class="bt-evidence">
      <summary>任务日志 <span v-if="events.length">（最近 {{ events.length }} 条）</span></summary>
      <p v-if="eventsError" class="bt-note">{{ diagnosticLabel(eventsError) }}</p>
      <ol v-if="events.length" class="bt-list" aria-label="任务状态事件">
        <li v-for="(event, index) in events" :key="[event.at, event.phase, index].join('/')">
          <span><time :datetime="event.at">{{ formatBeijingInstant(event.at) }}</time> · {{ statusLabel(event.status) }} · {{ eventCode(event.phase) }}</span>
          <small v-if="event.diagnostic">{{ eventCode(event.diagnostic) }}</small>
        </li>
      </ol>
    </details>
    <nav v-if="run.status === 'SUCCEEDED'" class="bt-tabs bt-result-tabs" aria-label="Run 结果">
      <button v-for="[key, label] in tabs" :key="key" type="button" :aria-pressed="tab === key" @click="change(key)">{{ label }}</button>
    </nav>
    <p v-if="artifactError" class="bt-alert" role="alert">{{ artifactError }}</p>
    <p v-else-if="artifactLoading" class="bt-note" role="status">正在读取已归档结果</p>

    <template v-if="tab === 'overview' || tab === 'risk'">
      <dl v-if="run.status === 'SUCCEEDED'" class="bt-metrics">
        <div v-for="item in requiredMetrics" :key="item.key">
          <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
          <dd v-if="item.reason || item.definition || item.source" class="bt-metric-definition">{{ [item.source, item.definition, item.reason ? diagnosticLabel(item.reason) : null].filter(Boolean).join(' · ') }}</dd>
        </div>
      </dl>
      <dl v-if="run.status === 'SUCCEEDED' && run.summary" class="bt-facts">
        <template v-for="(label, key) in evidenceLabels" :key="key">
          <dt>{{ label }}</dt><dd>{{ key === 'sample_type' ? sampleLabels[run.summary.sample_type ?? run.config.sample_type ?? 'historical'] : displayValue(run.summary[key] ?? run.snapshot?.[key] ?? run.config[key] ?? (key === 'pairing_basis' ? metrics.trade_count?.definition : null)) }}</dd>
        </template>
        <dt>手续费倍率 / 滑点</dt><dd>{{ run.config.commission_multiplier ?? '—' }} / {{ run.config.slippage_ticks ?? '—' }} 跳</dd>
        <dt>执行延迟</dt><dd>{{ run.config.parameters?.execution_delay_minutes ?? 0 }} 分钟</dd>
      </dl>
      <details v-if="tab === 'overview'" class="bt-evidence">
        <summary>提交时冻结的配置请求</summary>
        <pre>{{ JSON.stringify(run.config, null, 2) }}</pre>
      </details>
      <details v-if="tab === 'overview' && run.snapshot" class="bt-evidence">
        <summary>引擎准入快照</summary>
        <pre>{{ JSON.stringify(run.snapshot, null, 2) }}</pre>
      </details>
    </template>

    <template v-if="tab === 'equity' && equityPage">
      <BacktestChart v-if="equityPage.items.length" :series="{ kind: 'equity', rows: equityPage.items }" />
      <p v-else class="bt-note">本 Run 没有归档的估值点。</p>
      <div v-if="equityPage.items.length" class="bt-table-scroll">
        <table class="bt-table"><thead><tr><th>估值时点</th><th>结算权益</th><th>回撤</th></tr></thead>
          <tbody><tr v-for="row in equityPage.items" :key="row.at"><td>{{ formatBeijingInstant(row.at) }}</td>
            <td>{{ row.equity }}</td><td>{{ metricValue('max_drawdown', row.drawdown) }}</td></tr></tbody>
        </table>
      </div>
    </template>

    <template v-if="tab === 'trades' && tradePage">
      <div v-if="tradePage.items.length" class="bt-table-scroll">
        <table class="bt-table">
          <thead><tr><th>交易</th><th>物理合约 / 方向</th><th>状态</th><th>手数</th><th>建模进场</th><th>建模出场</th><th>费用</th><th>净盈亏</th><th>未实现盈亏</th></tr></thead>
          <tbody><tr v-for="row in tradePage.items" :key="row.trade_id">
            <td><button type="button" class="bt-link bt-id" :aria-pressed="replayTrade?.trade_id === row.trade_id" @click="replayTrade = row">{{ row.trade_id }}</button></td>
            <td>{{ row.contract }} / {{ row.direction }}</td><td>{{ statusLabel(row.status) }}</td><td>{{ row.quantity }}</td>
            <td class="bt-nowrap">{{ formatBeijingInstant(row.entry_at) }} · {{ row.entry_price ?? '—' }}</td>
            <td class="bt-nowrap">{{ formatBeijingInstant(row.exit_at) }} · {{ row.exit_price ?? '—' }}</td>
            <td>{{ row.fees ?? '—' }}</td><td>{{ row.net_pnl ?? '—' }}</td><td>{{ row.unrealized_pnl ?? '—' }}</td>
          </tr></tbody>
        </table>
      </div>
      <p v-else class="bt-note">本 Run 没有可读的研究交易。</p>
    </template>

    <div v-if="(tab === 'trades' || tab === 'equity') && resultTotal > pageSize" class="bt-pager">
      <button class="bt-button" :disabled="offset === 0 || artifactLoading" @click="offset -= pageSize">上一页</button>
      <span>第 {{ Math.floor(offset / pageSize) + 1 }} 页 · {{ resultTotal }} 项</span>
      <button class="bt-button" :disabled="offset + pageSize >= resultTotal || artifactLoading" @click="offset += pageSize">下一页</button>
    </div>

    <BacktestTradeReplay v-if="tab === 'trades' && replayTrade"
      :key="replayTrade.trade_id" :run="run" :trade="replayTrade" @close="replayTrade = undefined" />

    <template v-if="tab === 'report' && report">
      <details v-for="(fact, key) in report" :key="key" class="bt-evidence" :open="['summary', 'metrics'].includes(key)">
        <summary>{{ evidenceLabels[key] ?? key }}</summary>
        <pre>{{ JSON.stringify(fact, null, 2) }}</pre>
      </details>
    </template>
  </section>
  <section v-else>
    <p v-if="error" class="bt-alert" role="alert">{{ diagnosticLabel(error) }} <button class="bt-button" @click="update += 1">重读 Run</button></p>
    <p v-else class="bt-note" role="status">正在读取 Run {{ runId }}</p>
  </section>
</template>
