<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  cancelRun, diagnosticCode, readEquity, readReplay, readReport, readRun, readTrades, rerun, runInProgress,
  type Equity, type EvidenceFields, type Replay, type Rows, type Run, type Trade,
} from '@/api/backtestCenter'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import BacktestChart from './BacktestChart.vue'
import { diagnosticLabel, displayValue, metricLabels, metricValue, sampleLabels, statusLabel } from './backtestDisplay'

const props = defineProps<{ runId: string }>()
const router = useRouter()
const run = shallowRef<Run>()
const update = ref(0)
const error = ref('')
const actionError = ref('')
const busy = ref(false)
const loading = ref(false)
const tab = ref('overview')
const tabs = [
  ['overview', '概览'], ['equity', '资金曲线'], ['trades', '交易明细'], ['risk', '风险分析'], ['report', '报告'],
] as const
const pageSize = 50
const equityPage = shallowRef<Rows<Equity>>()
const tradePage = shallowRef<Rows<Trade>>()
const offset = ref(0)
const artifactLoading = ref(false)
const artifactError = ref('')
const report = shallowRef<EvidenceFields>()
const replay = shallowRef<Replay>()
const replayTrade = shallowRef<Trade>()
const replayError = ref('')
const rerunKey = ref('')
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
const shownTrade = computed(() => replay.value?.trade ?? replayTrade.value)
const tradeSignals = computed(() => [shownTrade.value?.entry_signal_id, shownTrade.value?.exit_signal_id]
  .filter((id): id is string => typeof id === 'string'))
const tradeClocks = computed(() => (replay.value?.native_fills ?? []).map(fill => ({
  fill, attempt: replay.value?.attempts?.find(attempt => attempt.signal_id === fill.signal_id),
})))
const evidenceLabels: Record<string, string> = {
  source: '指标来源', sample_type: '样本类型', cost_basis: '成本口径', pairing_basis: '配对口径',
  benchmark: '基准', engine_version: '引擎版本', data_revision: '数据修订',
}

watch(update, async (_, __, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  error.value = ''
  loading.value = true
  try {
    const value = await readRun(props.runId, controller.signal)
    if (!controller.signal.aborted) run.value = value
  } catch (reason) {
    if (!controller.signal.aborted) error.value = diagnosticCode(reason) ?? 'Run 读取失败'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
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
      if (!controller.signal.aborted) equityPage.value = value
    } else if (section === 'trades') {
      const value = await readTrades(props.runId, start, pageSize, controller.signal)
      if (!controller.signal.aborted) tradePage.value = value
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

watch(replayTrade, async (selected, _, onCleanup) => {
  replay.value = undefined
  replayError.value = ''
  if (!selected) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const value = await readReplay(props.runId, selected.trade_id, controller.signal)
    if (controller.signal.aborted) return
    if (value.run_id !== props.runId || value.trade?.trade_id !== selected.trade_id
      || (value.available && (value.contract !== selected.contract
        || value.frequency !== run.value?.config.signal_frequency || !value.revision
        || (run.value?.snapshot?.data_revision && value.revision !== run.value.snapshot.data_revision)))) {
      replayError.value = '归档图窗的 Run、交易或修订身份不一致。'
      return
    }
    replay.value = value
  } catch (reason) {
    if (!controller.signal.aborted) replayError.value = diagnosticCode(reason) ?? '图窗读取失败'
  }
})

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
      if (!rerunKey.value) rerunKey.value = crypto.randomUUID()
      const result = await rerun(props.runId, rerunKey.value)
      rerunKey.value = ''
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
        <button v-if="run.status === 'QUEUED' || run.status === 'RUNNING'" class="bt-button" :disabled="busy" @click="act('cancel')">取消任务</button>
        <button v-if="!runInProgress(run.status)" class="bt-button" :disabled="busy" @click="act('rerun')">按原配置重跑</button>
      </div>
    </div>
    <div class="bt-run-meta">
      <span class="bt-status" :data-status="run.status">{{ statusLabel(run.status) }}</span>
      <span>研究资格 {{ statusLabel(run.qualification) }}</span>
      <span v-if="run.phase">阶段 {{ run.phase }}</span>
      <time>{{ formatBeijingInstant(run.updated_at) }}</time>
      <RouterLink v-if="run.source_run_id" :to="{ name: 'backtests', params: { runId: run.source_run_id } }">来源 Run {{ run.source_run_id }}</RouterLink>
    </div>
    <p v-if="run.diagnostic" class="bt-alert" role="status">{{ diagnosticLabel(run.diagnostic) }}</p>
    <p v-if="error || actionError" class="bt-alert" role="alert">{{ diagnosticLabel(actionError || error) }}</p>
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
      <button class="bt-button" :disabled="offset === 0 || artifactLoading" @click="replayTrade = undefined; offset -= pageSize">上一页</button>
      <span>第 {{ Math.floor(offset / pageSize) + 1 }} 页 · {{ resultTotal }} 项</span>
      <button class="bt-button" :disabled="offset + pageSize >= resultTotal || artifactLoading" @click="replayTrade = undefined; offset += pageSize">下一页</button>
    </div>

    <section v-if="tab === 'trades' && shownTrade" class="bt-replay" aria-labelledby="trade-replay-heading">
      <div class="bt-panel-header">
        <h3 id="trade-replay-heading">逐笔回放 · {{ shownTrade.contract }} · {{ shownTrade.direction }}</h3>
        <button type="button" class="bt-button" @click="replayTrade = undefined">关闭回放</button>
      </div>
      <p v-if="replayError" class="bt-alert" role="alert">{{ replayError }}</p>
      <p v-else-if="!replay" class="bt-note" role="status">正在读取同 Run 图窗</p>
      <template v-else>
        <p v-if="replay.revision" class="bt-note">{{ replay.contract }} · {{ replay.frequency }} · 数据修订 <code>{{ replay.revision }}</code></p>
        <BacktestChart v-if="replay.available && replay.bars?.length" :series="{ kind: 'trades', bars: replay.bars, markers: replay.markers ?? [], tradeId: shownTrade.trade_id, signalIds: tradeSignals }" />
        <p v-else role="status" class="bt-note">{{ replay.reason ? diagnosticLabel(replay.reason) : '原修订的归档图窗不可重建' }}</p>
      </template>
      <dl class="bt-facts">
        <dt>交易身份</dt><dd>{{ shownTrade.trade_id }}</dd>
        <dt>状态</dt><dd>{{ statusLabel(shownTrade.status) }}</dd>
        <dt>建模进场</dt><dd>{{ formatBeijingInstant(shownTrade.entry_at) }} · {{ shownTrade.entry_price ?? '—' }}</dd>
        <dt>建模出场</dt><dd>{{ formatBeijingInstant(shownTrade.exit_at) }} · {{ shownTrade.exit_price ?? '—' }}</dd>
        <dt>费用</dt><dd>{{ shownTrade.fees ?? '—' }}</dd>
        <template v-if="shownTrade.status === 'OPEN' || shownTrade.status === 'ROLLOVER_INTERRUPTED'">
          <dt>未实现盈亏</dt><dd>{{ shownTrade.unrealized_pnl ?? '缺结算估值' }}</dd>
        </template>
        <template v-else><dt>净盈亏</dt><dd>{{ shownTrade.net_pnl ?? '—' }}</dd></template>
      </dl>
      <div v-if="tradeClocks.length" class="bt-table-scroll">
        <table class="bt-table" aria-label="成交时钟与对账">
          <thead><tr><th>原生成交</th><th>信号收线</th><th>信号可用</th><th>原生委托</th><th>建模成交</th><th>原生成交回调</th><th>价格 / 费用</th></tr></thead>
          <tbody><tr v-for="{ fill, attempt } in tradeClocks" :key="displayValue(fill.native_trade_id)">
            <td>{{ displayValue(fill.native_trade_id) }} · {{ displayValue(fill.position_effect) }}</td>
            <td>{{ displayValue(attempt?.signal_bar_end) }}</td><td>{{ displayValue(attempt?.signal_available_at) }}</td>
            <td>{{ displayValue(fill.native_order_at) }}</td><td>{{ displayValue(fill.modeled_fill_at) }}</td>
            <td>{{ displayValue(fill.native_fill_at) }}</td><td>{{ displayValue(fill.price) }} / {{ displayValue(fill.fee) }}</td>
          </tr></tbody>
        </table>
      </div>
      <details class="bt-evidence"><summary>原生成交、信号与配对证据</summary><pre>{{ JSON.stringify({ trade: shownTrade, native_fills: replay?.native_fills, attempts: replay?.attempts }, null, 2) }}</pre></details>
    </section>

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
