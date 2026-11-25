<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, ref, watch } from 'vue'
import request from '@/api/request'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import ReturnCurveSvg from '@/components/charts/ReturnCurveSvg.vue'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
import {
  backtestSelection, createBacktestReader, type BacktestKind, type BacktestRow, type LatestBacktest,
} from '@/utils/newowBacktestReader'

const props = defineProps<{ product: string; strategy: string; frequency: string; afterMarket?: boolean }>()
const emit = defineEmits<{ published: [result: LatestBacktest['result']] }>()
const open = ref(!!props.afterMarket)
const trial = ref(false)
const selected = shallowRef<BacktestRow | null>(null)
const frozenBar = computed(() => {
  const decision = selected.value?.decision as { bar?: Record<string, unknown> } | undefined
  return decision?.bar
})
const current = shallowRef<ReturnType<typeof createBacktestReader>['state']>()
const path = '/newow/backtests'
const reader = createBacktestReader({
  latest: (params, signal) => request.get<unknown, LatestBacktest>(`${path}/latest`, { params, signal }),
  page: (run, kind, cursor, signal) => request.get(`${path}/${encodeURIComponent(run)}/${kind}`, {
    params: { limit: kind === 'trades' ? 5 : 20, ...(cursor ? { cursor } : {}) }, signal,
  }),
}, value => { current.value = value })

const key = computed(() => backtestSelection(props.product, props.strategy, props.frequency, trial.value))
const result = computed(() => current.value?.latest?.result)
watch(result, value => emit('published', value ?? null), { flush: 'sync' })
const referenceOnly = computed(() => result.value?.summary.result_kind === 'reference_only')
const attempt = computed(() => current.value?.latest?.last_attempt)
const equityPlot = computed(() => {
  const run = result.value
  const initial = Number(run?.summary.initial_equity)
  if (!run || !Number.isFinite(initial)) return null
  const rows = current.value?.equity.items ?? []
  if (!rows.length) return null
  return returnCurveLayout(rows.map(row => ({
    value: typeof row.equity === 'string' ? Number(row.equity) - initial : null,
    date: text(row.trading_day), segment: run.run_id, position: row.seq,
  })), { valueUnit: 'currency', headroom: 1.15, areaBaseline: 'zero' })
})
const labels = { trades: '逐笔成交', equity: '结算权益' }
const kinds: BacktestKind[] = ['trades', 'equity']
const sides: Record<string, string> = { BUY: '买', SELL: '卖' }
const effects: Record<string, string> = { OPEN: '开仓', CLOSE: '平仓', CLOSE_TODAY: '平今' }
const stateLabels = { RUNNING: '计算中', SUCCEEDED: '成功', FAILED: '失败' }
const diagnostics: Record<string, string> = {
  RANK1_AS_KNOWN_UNPROVEN: '主力历史数据资格不足',
  BACKTEST_WARMUP_INSUFFICIENT: '预热数据不足',
  BACKTEST_EXECUTION_POLICY_UNAVAILABLE: '当前执行策略未覆盖跨时段成交',
  ROLLOVER_INTERRUPTED_OR_QUALITY_GAP: '物理合约切换或数据质量未通过',
}

function refresh() {
  selected.value = null
  void reader.select(open.value || props.afterMarket ? key.value : null)
}

function show() {
  open.value = true
}

function text(value: unknown): string {
  if (Array.isArray(value)) return value.map(text).join('、')
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '—'
}

watch(() => [props.product, props.strategy, props.frequency], () => { trial.value = false }, { flush: 'sync' })
watch([open, key], refresh, { immediate: true })
onBeforeUnmount(reader.dispose)
defineExpose({ show })
</script>

<template>
  <details :open="open" class="backtest-panel" data-testid="newow-backtest" @toggle="open = ($event.target as HTMLDetailsElement).open">
    <summary>{{ afterMarket ? '牛哇盘后参考与历史回测' : '历史回测交易 · RQAlpha' }}</summary>
    <div class="backtest-panel__body">
      <div class="backtest-panel__controls">
        <label>结果系列 <select v-model="trial"><option :value="false">正式研究</option><option :value="true">历史试验</option></select></label>
        <button type="button" :disabled="current?.loading" @click="refresh">刷新结果</button>
      </div>
      <p v-if="current?.loading" role="status">正在读取回测结果…</p>
      <p v-else-if="current?.error" role="status">回测结果读取失败，请刷新重试。</p>
      <p v-else-if="!result" role="status">{{ afterMarket ? '暂无成功发布结果。' : '暂无成功回测结果。' }}</p>
      <p v-if="frequency === '1d' || frequency === '1w'">当前执行策略仅允许同交易时段内成交。日周收盘后没有符合该策略的开盘价。</p>
      <p v-if="attempt" role="status">
        最近尝试 {{ attempt.as_of_trading_day }} · {{ stateLabels[attempt.status] }}
        <template v-if="attempt.error_code"> · {{ diagnostics[attempt.error_code] ?? attempt.error_code }}</template>
        <template v-if="result && attempt.run_id !== result.run_id"> · 当前结果仍截至 {{ result.as_of_trading_day }}</template>
      </p>
      <template v-if="result">
        <p data-testid="newow-backtest-identity"><strong>{{ result.qualification === 'TRIAL' ? '历史试验' : '数据资格已核验' }}</strong>
          · {{ afterMarket ? '数据截至交易日' : '数据截至' }} {{ result.as_of_trading_day }} · 计算完成 {{ formatBeijingInstant(result.finished_at) }} · {{ text(result.manifest.since) }} 至 {{ text(result.manifest.through) }}
          · {{ text(result.manifest.physical_contract) }}</p>
        <dl v-if="!referenceOnly" class="backtest-panel__stats">
          <div><dt>净收益额</dt><dd>{{ text(result.summary.net_equity_change) }}</dd></div>
          <div><dt>最大回撤（元）</dt><dd>{{ text(result.summary.max_drawdown) }}</dd></div>
          <div><dt>手续费</dt><dd>{{ text(result.summary.fees) }}</dd></div>
          <div><dt>期末权益</dt><dd>{{ text(result.summary.final_equity) }}</dd></div>
        </dl>
        <details>
          <summary>策略版本与运行身份</summary>
          <p>{{ text(result.manifest.formula_versions) }} · {{ text(result.manifest.decision_version) }} <template v-if="!referenceOnly">· RQAlpha {{ text(result.manifest.engine_version) }}</template></p>
          <p>Run {{ result.run_id }}</p>
        </details>
        <section v-for="kind in referenceOnly ? [] : kinds" :key="kind" :aria-label="labels[kind]">
          <h3>{{ labels[kind] }}</h3>
          <ReturnCurveSvg v-if="kind === 'equity' && equityPlot" :plot="equityPlot" label="已加载结算点的权益变化（元）" area zero-line />
          <table v-if="current?.[kind].items.length">
            <thead v-if="kind === 'trades'"><tr><th>成交时间</th><th>合约</th><th>方向 / 开平</th><th>手数</th><th>成交价</th><th>费用</th><th>净盈亏</th><th>信号切片</th></tr></thead>
            <thead v-else><tr><th>交易日</th><th>权益</th><th>现金</th><th>费用</th><th>回撤（元）</th></tr></thead>
            <tbody>
              <tr v-for="row in current?.[kind].items" :key="row.seq">
                <template v-if="kind === 'trades'">
                  <td>{{ text(row.modeled_fill_at) }}</td><td>{{ text(row.physical_contract) }}</td>
                  <td>{{ sides[text(row.side)] ?? text(row.side) }} / {{ effects[text(row.position_effect)] ?? text(row.position_effect) }}</td><td>{{ text(row.quantity) }}</td>
                  <td>{{ text(row.price) }}</td><td>{{ text(row.fee) }}</td><td>{{ text(row.net_pnl) }}</td>
                  <td><button type="button" :aria-expanded="selected?.seq === row.seq" @click="selected = selected?.seq === row.seq ? null : row">信号切片</button></td>
                </template>
                <template v-else>
                  <td>{{ text(row.trading_day) }}</td><td>{{ text(row.equity) }}</td><td>{{ text(row.cash) }}</td>
                  <td>{{ text(row.fees) }}</td><td>{{ text(row.drawdown) }}</td>
                </template>
              </tr>
            </tbody>
          </table>
          <p v-else-if="current?.[kind].loaded">暂无{{ labels[kind] }}。</p>
          <p v-if="current?.[kind].loading" role="status">正在读取{{ labels[kind] }}…</p>
          <p v-if="current?.[kind].error" role="status">{{ labels[kind] }}读取失败。</p>
          <button v-if="current?.[kind].cursor || current?.[kind].error" type="button"
            :disabled="current?.[kind].loading" @click="reader.more(kind)">{{ current?.[kind].error ? '重试' : `更多${labels[kind]}` }}</button>
          <div v-if="kind === 'trades' && selected" class="backtest-panel__slice">
            <strong>{{ text(selected.physical_contract) }} · {{ text(selected.signal_bar_end) }}</strong>
            <p>信号可用 {{ text(selected.signal_available_at) }} · 原生成交回报 {{ text(selected.native_fill_event_at) }}</p>
            <p v-if="frozenBar">冻结K线 · 开 {{ text(frozenBar.open) }} · 高 {{ text(frozenBar.high) }} · 低 {{ text(frozenBar.low) }} · 收 {{ text(frozenBar.close) }}</p>
            <details v-if="selected.decision">
              <summary>原始决策与输入证据</summary>
              <pre>{{ JSON.stringify(selected.decision, null, 2) }}</pre>
            </details>
          </div>
        </section>
      </template>
    </div>
  </details>
</template>

<style scoped>
.backtest-panel { background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: 8px; margin-block: 12px; }
.backtest-panel > summary { cursor: pointer; padding: 12px; font-weight: 600; }
.backtest-panel__body { padding: 0 12px 12px; overflow-x: auto; }
.backtest-panel__controls, .backtest-panel__stats { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.backtest-panel__body { display: grid; gap: 10px; }
.backtest-panel__body p, .backtest-panel__body h3 { margin: 0; }
.backtest-panel__body button {
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: 6px;
  padding: 5px 10px;
  color: var(--gy-text-primary);
  cursor: pointer;
}
.backtest-panel__body button:hover, .backtest-panel__body button[aria-expanded="true"] { border-color: var(--gy-detail-accent); }
.backtest-panel__body button:disabled { opacity: .6; cursor: wait; }
.backtest-panel__stats { margin: 0; }
.backtest-panel__stats dt { color: var(--gy-text-secondary); }
.backtest-panel__slice p { margin-top: 5px; }
.backtest-panel__stats dd { margin: 4px 0 0; font-variant-numeric: tabular-nums; font-weight: 600; }
.backtest-panel th, .backtest-panel td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--gy-border); }
.backtest-panel table { width: 100%; border-collapse: collapse; }
.backtest-panel__slice { border: 1px solid var(--gy-border); padding: 12px; margin-block: 8px; }
.backtest-panel :deep(.return-curve) { position: relative; }
.backtest-panel pre { max-height: 18rem; overflow: auto; }
</style>
