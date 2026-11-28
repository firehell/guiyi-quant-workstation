<script setup lang="ts">
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { readSimulationWorkspace, type Fill, type SimulationWorkspace } from '@/api/simulationCenter'
import { monitorClient } from '@/api/simulationMonitor'
import { readSubingPortfolioStatus } from '@/api/subingPortfolio'
import { useWorkstationRead } from '@/composables/useWorkstationRead'
import { observerLabel } from '@/utils/simulationPresentation'
import ReturnCurveSvg from '@/components/charts/ReturnCurveSvg.vue'
import { physicalContract } from '@/utils/workstationAccounts'
import { workstationChartLink } from '@/utils/workstationRoutes'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { returnCurveLayout } from '@/utils/returnCurveLayout'

const { value: tq, state: tqRead, refresh: refreshTq } = useWorkstationRead(monitorClient.overview)
const { value: paper, state: paperRead, refresh: refreshPaper } = useWorkstationRead(readSubingPortfolioStatus)
const modelStatus = computed(() => {
  if (!paper.value) return paperRead.value === 'error' ? '读取失败' : '读取中'
  if (paper.value.status === 'STALE_OR_STOPPED') return '心跳过期或已停止'
  return paper.value.run_id ? paper.value.status : '尚无模型 Run'
})
function refreshSources() {
  void load()
  void refreshTq()
  void refreshPaper()
}

const tabs = [
  ['overview', '模拟概览'], ['accounts', '账户管理'], ['deployments', '策略运行'],
  ['records', '交易记录'], ['performance', '绩效分析'],
] as const
const statuses: Record<string, string> = {
  REGISTERED: '已登记',
  CONNECTING: '连接中', RECONCILING: '对账中', OBSERVING: '账户观察', DISCONNECTED: '连接中断',
  READBACK_FAILED: '对账失败', OBSERVER_FAILED: '进程故障', STOPPED: '已停止', STALE: '状态过期',
}
const orderStatuses: Record<string, string> = {
  '0': '全部成交', '1': '部分成交 · 排队', '2': '部分成交 · 已结束', '3': '未成交 · 排队',
  '4': '未成交 · 已结束', '5': '已撤销', a: '未知', b: '尚未触发', c: '已触发',
}
const strategies: Record<string, string> = { htdy_60m: '火天大有 60m', subing_portfolio_16: '苏冰 16 品种组合' }
const offsets: Record<string, string> = { OPEN: '开仓', CLOSE: '平仓', CLOSETODAY: '平今', CLOSEYESTERDAY: '平昨' }

const route = useRoute()
const router = useRouter()
const view = computed(() => tabs.find(([key]) => key === route.query.view)?.[0] ?? 'overview')
const account = computed(() => typeof route.query.account === 'string' ? route.query.account : undefined)
const workspace = shallowRef<SimulationWorkspace>()
const fills = shallowRef<Fill[]>([])
const cursor = ref<string | null>(null)
const loading = ref(false)
const error = ref(false)
const pageError = ref(false)
let pending: AbortController | undefined
const selected = computed(() => workspace.value?.accounts.find(row => row.alias === workspace.value?.selected))
const snapshot = computed(() => workspace.value?.readback)
const plot = computed(() => returnCurveLayout((workspace.value?.equity ?? []).map(item => ({
  value: Number(item.equity), date: new Date(Date.parse(item.observed_at) + 8 * 3600000).toISOString().slice(0, 10),
  position: Date.parse(item.observed_at), segment: workspace.value?.selected ?? 'simnow',
})), { areaBaseline: 'bottom', headroom: 1.02, valueUnit: 'currency' }))

async function load(more = false) {
  if (more && (loading.value || !cursor.value || !workspace.value?.selected)) return
  pending?.abort()
  const request = new AbortController()
  pending = request
  loading.value = true
  pageError.value = false
  if (!more) error.value = false
  try {
    const response = await readSimulationWorkspace(request.signal,
      more ? workspace.value?.selected ?? undefined : account.value, more ? cursor.value ?? undefined : undefined)
    if (request.signal.aborted) return
    if (!more) workspace.value = response
    const seen = new Set(more ? fills.value.map(fill => fill.id) : [])
    fills.value = [...(more ? fills.value : []), ...response.fills.filter(fill => !seen.has(fill.id))]
    cursor.value = response.next_fill
  } catch {
    if (!request.signal.aborted) {
      if (more) pageError.value = true
      else error.value = true
    }
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

watch(account, () => {
  workspace.value = undefined
  fills.value = []
  cursor.value = null
  void load()
}, { immediate: true })
onScopeDispose(() => pending?.abort())

function selectAccount(event: Event) {
  const alias = (event.target as HTMLSelectElement).value
  void router.replace({ name: 'simulations', query: { ...route.query, account: alias } })
}
function contractChart(id: string) {
  const product = id.replace(/\d+$/, '').toLowerCase()
  const contract = physicalContract(product, id)
  if (!contract) return null
  return workstationChartLink({ view: 'free', symbol: product, contract, seriesKind: 'contract', frequency: '1m' })
}
function amount(value?: string) {
  return value === undefined ? '—' : `¥ ${value}`
}
function side(value: string) { return value === 'LONG' ? '买 / 多' : '卖 / 空' }
</script>

<template>
  <div class="simulation-shell">
    <main class="simulation">
      <header class="simulation-heading">
        <div><h1>模拟交易中心</h1><p>账户读回与模拟运行</p></div>
        <div class="simulation-actions">
          <label v-if="workspace?.accounts.length">账户
            <select :value="workspace.selected" @change="selectAccount">
              <option v-for="row in workspace.accounts" :key="row.alias" :value="row.alias">{{ row.alias }}</option>
            </select>
          </label>
          <button type="button" :disabled="loading" @click="refreshSources">刷新</button>
        </div>
      </header>

      <nav class="account-sources" aria-label="模拟来源">
        <div><strong>SimNow 柜台读回</strong><small>{{ snapshot?.trading_day ?? (workspace?.status === 'NOT_CONFIGURED' ? '读回未配置' : selected?.alias ?? '暂无读回') }}</small></div>
        <RouterLink to="/market?tab=simulation"><strong>快期模拟账户</strong><small>{{ tq ? observerLabel(tq) : tqRead === 'error' ? '读取失败' : '读取中' }} · {{ tq?.trading_day ?? '无已核验交易日' }}</small></RouterLink>
        <RouterLink to="/research/subing-decision"><strong>苏冰共享 Paper</strong><small>{{ modelStatus }} · {{ paper?.trading_day ?? '无已核验交易日' }}</small></RouterLink>
        <RouterLink v-if="snapshot?.trading_day" :to="{ name: 'trade-journal', query: { day: snapshot.trading_day } }">复盘此交易日</RouterLink>
      </nav>
      <nav class="simulation-tabs" aria-label="模拟交易中心导航">
        <RouterLink v-for="[key, title] in tabs" :key="key"
          :to="{ name: 'simulations', query: { account, view: key === 'overview' ? undefined : key } }"
          :aria-current="view === key ? 'page' : undefined">{{ title }}</RouterLink>
      </nav>

      <p v-if="error" role="alert">账户证据读取失败。{{ workspace ? ' 下方为上次读取。' : '' }}</p>
      <p v-if="loading && !workspace" role="status">正在读取账户证据…</p>
      <p v-else-if="workspace?.status === 'NOT_CONFIGURED'" class="panel" role="status">尚未配置 SimNow 账户读回。</p>
      <p v-else-if="workspace && !selected" class="panel" role="status">暂无已登记的 SimNow 账户。</p>

      <template v-if="selected">
        <p class="simulation-as-of" role="status">
          <strong>{{ statuses[selected.status] ?? selected.status }}</strong>
          <span v-if="snapshot">交易日 {{ snapshot.trading_day }} · 最近完整读回 {{ formatBeijingInstant(snapshot.observed_at) }}</span>
          <span v-else>尚无完整柜台读回</span>
        </p>

        <section v-if="view === 'overview'" aria-label="账户摘要">
          <dl class="metrics">
            <div><dt>账户权益</dt><dd>{{ amount(snapshot?.account.equity) }}</dd></div>
            <div><dt>可用资金</dt><dd>{{ amount(snapshot?.account.available) }}</dd></div>
            <div><dt>占用保证金</dt><dd>{{ amount(snapshot?.account.margin) }}</dd></div>
            <div><dt>物理合约持仓</dt><dd>{{ snapshot ? new Set(snapshot.positions.filter(row => row.quantity).map(row => row.id.split(':').slice(0, 2).join(':'))).size : '—' }}</dd></div>
          </dl>
          <div class="panel equity">
            <h2>柜台账户权益</h2>
            <ReturnCurveSvg v-if="workspace?.equity.length" :plot="plot" label="SimNow 账户权益采样" area />
            <p v-else>暂无权益采样。</p>
          </div>
        </section>

        <section v-else-if="view === 'accounts'" class="panel">
          <h2>账户登记</h2>
          <div class="table-scroll"><table>
            <thead><tr><th>账户别名</th><th>来源</th><th>运行状态</th><th>最近状态变更</th></tr></thead>
            <tbody><tr v-for="row in workspace?.accounts" :key="row.alias">
              <td>{{ row.alias }}</td><td>SimNow CTP</td><td>{{ statuses[row.status] ?? row.status }}</td><td>{{ formatBeijingInstant(row.status_at) }}</td>
            </tr></tbody>
          </table></div>
        </section>

        <section v-else-if="view === 'deployments'" class="panel">
          <h2>策略部署</h2>
          <p v-if="!selected.deployment">此账户暂无已登记的策略部署。</p>
          <dl v-else class="deployment">
            <dt>策略</dt><dd><RouterLink :to="{ name: 'strategies', params: { strategyId: selected.deployment.strategy_id } }">{{ strategies[selected.deployment.strategy_id] ?? selected.deployment.strategy_id }}</RouterLink></dd>
            <dt>执行状态</dt><dd>等待仿真执行验收</dd>
            <dt>公式版本</dt><dd>{{ selected.deployment.formula_version }}</dd>
            <dt>参数 Profile</dt><dd>{{ selected.deployment.profile_id }}</dd>
            <dt>风险政策</dt><dd>{{ selected.deployment.risk_policy_version }}</dd>
            <dt>物理合约</dt><dd>{{ selected.deployment.instruments.join('、') }}</dd>
          </dl>
        </section>

        <section v-else-if="view === 'records' && snapshot" class="records" aria-label="交易记录">
          <div class="panel">
            <h2>持仓</h2><p v-if="!snapshot.positions.length">最近完整读回为空仓。</p>
            <div v-else class="table-scroll"><table>
              <thead><tr><th>合约</th><th>方向</th><th>手数</th><th>今仓</th><th>昨仓</th><th>冻结</th><th>持仓盈亏</th></tr></thead>
              <tbody><tr v-for="row in snapshot.positions" :key="row.id"><td><RouterLink v-if="contractChart(row.contract)" :to="contractChart(row.contract)!">{{ row.contract }}</RouterLink><template v-else>{{ row.contract }}</template> · {{ row.exchange }}</td>
                <td>{{ side(row.direction) }}</td><td>{{ row.quantity }}</td><td>{{ row.today }}</td>
                <td>{{ row.yesterday }}</td><td>{{ row.frozen }}</td><td>{{ row.pnl }}</td>
              </tr></tbody>
            </table></div>
          </div>
          <div class="panel">
            <h2>当日委托</h2><p v-if="!snapshot.orders.length">本交易日暂无柜台委托。</p>
            <div v-else class="table-scroll"><table>
              <thead><tr><th>原生委托身份</th><th>合约</th><th>方向 · 开平</th><th>委托价</th><th>成交 / 委托手数</th><th>状态</th></tr></thead>
              <tbody><tr v-for="row in snapshot.orders" :key="row.id"><td>{{ row.id }}</td><td>{{ row.contract }}</td>
                <td>{{ side(row.direction) }} · {{ offsets[row.offset] ?? row.offset }}</td><td>{{ row.price }}</td>
                <td>{{ row.filled }} / {{ row.quantity }}</td><td>{{ orderStatuses[row.status] ?? row.status }}</td>
              </tr></tbody>
            </table></div>
          </div>
          <div class="panel">
            <h2>柜台成交</h2><p v-if="!fills.length">暂无已归档柜台成交。</p>
            <div v-else class="table-scroll"><table>
              <thead><tr><th>原生委托身份</th><th>合约</th><th>方向 · 开平</th><th>成交价</th><th>手数</th><th>柜台时间</th><th>手续费</th></tr></thead>
              <tbody><tr v-for="row in fills" :key="row.id"><td>{{ row.order_id }}</td><td>{{ row.contract }}</td>
                <td>{{ side(row.direction) }} · {{ offsets[row.offset] ?? row.offset }}</td><td>{{ row.price }}</td>
                <td>{{ row.quantity }}</td><td>{{ formatBeijingInstant(row.occurred_at) }}</td><td>{{ row.fee ?? '待确认' }}</td>
              </tr></tbody>
            </table></div>
            <p v-if="pageError" role="alert">更早成交读取失败。</p>
            <button v-if="cursor" type="button" :disabled="loading" @click="load(true)">加载更早成交</button>
          </div>
        </section>

        <section v-else-if="view === 'performance'" class="panel equity">
          <h2>柜台账户权益</h2>
          <ReturnCurveSvg v-if="workspace?.equity.length" :plot="plot" label="SimNow 账户权益采样" area />
          <p v-else>暂无权益采样。</p>
          <p>净收益、回撤与策略归因等待完整资金流和逐笔成本事实。</p>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.simulation-shell { min-height: 100%; }
.account-sources { display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap: 8px; margin: 14px 0 0; }
.account-sources > * { display: grid; align-content: center; gap: 5px; min-height: 48px; padding: 9px 12px; border: 1px solid var(--gy-border); border-radius: 5px; background: var(--gy-bg-panel); }
.account-sources small { color: var(--gy-text-secondary); }
.account-sources a:hover { border-color: var(--gy-detail-accent); }
.simulation { max-width: 1320px; padding: clamp(14px, 3vw, 38px); margin: auto; color: var(--gy-text-primary); }
.simulation-heading, .simulation-actions, .simulation-as-of { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.simulation-heading { justify-content: space-between; }
.simulation h1, .simulation h2, .simulation-heading p { margin: 0; }
.simulation h1 { font-size: clamp(24px, 3vw, 34px); }
.simulation h2 { font-size: 17px; }
.simulation p, .simulation-as-of, dt { color: var(--gy-text-secondary); }
.simulation-heading p { margin-top: 7px; }
.simulation-tabs { display: flex; gap: 18px; margin: 22px 0 14px; border-bottom: 1px solid var(--gy-border-subtle); overflow: auto; }
.simulation-tabs a { color: var(--gy-text-secondary); padding: 10px 2px; white-space: nowrap; }
.simulation-tabs [aria-current] { border-bottom: 2px solid var(--gy-detail-accent); color: var(--gy-text-primary); font-weight: 700; }
button, select { padding: 6px 12px; margin-inline-start: 4px; border: 1px solid var(--gy-border-subtle); border-radius: 6px; background: var(--gy-surface); color: inherit; font: inherit; }
button:enabled { cursor: pointer; }
.panel, .metrics div { padding: 16px; border: 1px solid var(--gy-border-subtle); border-radius: 8px; background: var(--gy-surface); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 12px; }
.metrics dd { margin: 8px 0 0; font-size: 24px; font-variant-numeric: tabular-nums; }
.equity { margin-top: 14px; --return-curve-line: var(--gy-detail-accent); }
.records { display: grid; gap: 12px; }
.table-scroll { overflow: auto; max-height: 480px; }
table { width: 100%; text-align: left; border-collapse: collapse; margin-top: 12px; font-variant-numeric: tabular-nums; }
th, td { padding: 8px; border-bottom: 1px solid var(--gy-border-subtle); white-space: nowrap; }
.deployment { display: grid; grid-template-columns: minmax(70px, 110px) 1fr; gap: 10px; }
.deployment dd { margin: 0; overflow-wrap: anywhere; }
</style>
