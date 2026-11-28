<script setup lang="ts">
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NEWOW_FREQUENCIES, NEWOW_STRATEGIES } from '@/types/marketDetail'
import { workstationChartLink } from '@/utils/workstationRoutes'
import {
  readStrategies, readStrategyDetail, readStrategyProjection, readStrategyRuntime,
  type StrategyDefinition, type StrategyDetail, type StrategyDomain, type StrategyProjection, type VersionReference,
} from '@/api/strategyCenter'
import { formatBeijingInstant } from '@/utils/marketDisplay'

const domains = [
  { id: 'newow', label: '牛哇', result: '参考交易' },
  { id: 'htdy', label: '火天大有', result: '快期模拟' },
  { id: 'subing', label: '苏冰', result: '共享 Paper' },
] as const

const statuses: Record<string, string> = {
  AVAILABLE: '来源可读', BLOCKED: '受阻', DISABLED: '来源报告停用', UNKNOWN: '待核验',
  UNVERIFIED: '待核验', STALE: '状态过期', WAITING: '等待输入', UNAVAILABLE: '读取失败',
  REGISTERED: '已有登记', NOT_REGISTERED: '暂无登记', NOT_OBSERVED: '暂无观察',
  PUBLISHED: '已存档', HISTORICAL_RESULT: '历史审计结果', NOT_PUBLISHED: '暂无结果', REGISTERED_UNVERIFIED: '已登记 · 待核验',
  UNSUPPORTED: '范围不可用', SELECTION_REQUIRED: '请选择品种和周期',
}
const kinds: Record<string, string> = { BASE: '基础策略', COMPOSITE: '组合策略', DOMAIN_STRATEGY: '领域策略', PORTFOLIO: '投资组合' }
const versionKinds: Record<string, string> = {
  formula: '公式', profile: '参数 Profile', reference_model: '参考模型', fixed_one_lot_policy: '固定一手政策',
  account_policy: '账户政策', risk_policy: '风险政策', quote_policy: '报价政策', portfolio_policy: '组合政策',
}
const recordKinds: Record<string, string> = { signal: '观察信号', risk: '风险记录', order: '模拟委托', fill: '模拟成交' }

type Facts = Record<string, unknown>

const route = useRoute()
const items = shallowRef<StrategyDefinition[]>([])
const componentVersion = ref('')
const runtime = shallowRef<Partial<Record<StrategyDomain, StrategyProjection>>>({})
const error = ref(false)
const refreshing = ref(false)
const selectedId = computed(() => String(route.params.strategyId ?? ''))
const selected = computed(() => items.value.find(item => item.strategy_id === selectedId.value))
const detail = shallowRef<StrategyDetail>()
const detailError = ref(false)
const bindings = shallowRef<StrategyProjection>()
const evidence = shallowRef<StrategyProjection>()
const product = ref('')
const frequency = ref('')
const frequencies = computed(() => Object.keys(detail.value?.capability ?? {}))
const products = computed(() => detail.value?.capability?.[frequency.value] ?? [])
const currentRuntime = computed(() => selected.value && runtime.value[selected.value.domain])
const references = computed(() => [
  ...(detail.value?.references ?? []),
  ...(Array.isArray(bindings.value?.references) ? bindings.value.references as VersionReference[] : []),
])
const backtestQuery = computed(() => {
  function uniqueReference(kind: string) {
    const versions = new Set(references.value.filter(item => item.kind === kind).map(item => item.value))
    return versions.size === 1 ? versions.values().next().value : undefined
  }
  return {
    view: 'config', strategy: selected.value?.strategy_id,
    formula_version: uniqueReference('formula'), profile_id: uniqueReference('profile'),
  }
})
const selection = computed(() => selected.value?.domain === 'newow' && product.value && frequency.value
  ? { product: product.value, frequency: frequency.value } : undefined)
const selectedChart = computed(() => {
  const item = selected.value
  const period = NEWOW_FREQUENCIES.find(value => value === frequency.value)
  if (item?.domain !== 'newow' || !period || !product.value) return null
  const dual = item.owner_key === 'dual_fusion'
  const strategy = dual ? 'trend' : NEWOW_STRATEGIES.find(key => key === item.owner_key)
  if (!strategy) return null
  return workstationChartLink({ view: 'newow', seriesKind: 'actual_dominant', symbol: product.value, frequency: period,
    strategy, newowMode: dual ? 'dual' : undefined, newowSource: 'after-market' })
})
const lifecycle = computed(() => selected.value?.lifecycle === 'ACTIVE' ? '现役目录' : selected.value?.lifecycle)

const refreshEpoch = ref(0)
let directoryRequest: AbortController | undefined
let runtimeRequest: AbortController | undefined

async function refreshRuntime() {
  runtimeRequest?.abort()
  const controller = new AbortController()
  runtimeRequest = controller
  try {
    const value = await readStrategyRuntime(controller.signal)
    if (!controller.signal.aborted) runtime.value = value.domains
  } catch {
    if (!controller.signal.aborted) runtime.value = Object.fromEntries(domains.map(domain => [domain.id, failed()]))
  }
}

function refreshVisibleRuntime() {
  if (document.visibilityState === 'visible' && !refreshing.value) void refreshRuntime()
}

const runtimePoll = window.setInterval(refreshVisibleRuntime, 15_000)
document.addEventListener('visibilitychange', refreshVisibleRuntime)
async function refresh() {
  directoryRequest?.abort()
  const controller = new AbortController()
  directoryRequest = controller
  refreshing.value = true
  error.value = false
  runtime.value = {}
  refreshEpoch.value += 1
  const directory = readStrategies(controller.signal).then((value) => {
    if (controller.signal.aborted) return
    items.value = value.items
    componentVersion.value = value.version
  }, () => {
    if (!controller.signal.aborted) error.value = true
  })
  await Promise.all([directory, refreshRuntime()])
  if (!controller.signal.aborted) refreshing.value = false
}

watch([selected, refreshEpoch], async ([item], _, onCleanup) => {
  detail.value = undefined
  detailError.value = false
  product.value = ''
  frequency.value = ''
  if (!item) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const value = await readStrategyDetail(item.strategy_id, controller.signal)
    if (controller.signal.aborted) return
    detail.value = value
    if (item.domain === 'newow') frequency.value = frequencies.value.includes('60m') ? '60m' : frequencies.value[0] ?? ''
  } catch {
    if (!controller.signal.aborted) detailError.value = true
  }
})

watch(products, (options) => {
  if (!options.includes(product.value)) product.value = options[0] ?? ''
}, { flush: 'sync' })

watch([detail, selection], async ([metadata, params], _, onCleanup) => {
  bindings.value = undefined
  evidence.value = undefined
  if (!metadata || (metadata.strategy.domain === 'newow' && !params)) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  for (const resource of ['bindings', 'evidence'] as const) {
    const read = () => readStrategyProjection(metadata.strategy.strategy_id, resource, controller.signal, params)
      .catch(() => failed())
    let value = await read()
    for (const delay of [120, 280, 600]) {
      if (controller.signal.aborted || value.diagnostic !== 'SOURCE_BUSY') break
      await new Promise<void>(resolve => window.setTimeout(resolve, delay))
      if (controller.signal.aborted) return
      value = await read()
    }
    if (controller.signal.aborted) return
    if (resource === 'bindings') bindings.value = value
    else evidence.value = value
  }
})

onScopeDispose(() => {
  directoryRequest?.abort()
  runtimeRequest?.abort()
  window.clearInterval(runtimePoll)
  document.removeEventListener('visibilitychange', refreshVisibleRuntime)
})
void refresh()

function failed(): StrategyProjection {
  return { source: '策略中心 API', status: 'UNAVAILABLE', diagnostic: 'READ_FAILED' }
}
function statusOf(value?: StrategyProjection) { return value ? statuses[value.status] ?? value.status : '读取中' }
function asFacts(value: unknown): Facts {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Facts : {}
}
function rows(value: unknown): Facts[] { return Array.isArray(value) ? value.map(asFacts) : [] }
function text(value: unknown): string {
  if (value === true) return '是'
  if (value === false) return '否'
  if (Array.isArray(value)) return value.map(text).join(' / ') || '—'
  return typeof value === 'number' || typeof value === 'string' ? String(value) : '—'
}
function at(value: unknown) { return formatBeijingInstant(typeof value === 'string' ? value : null) }

const runtimeFacts = computed(() => {
  const value = currentRuntime.value
  if (!value) return []
  const authorization = asFacts(value.authorization)
  const watermark = asFacts(value.watermark)
  const sourceTimes = Object.entries(watermark)
    .filter(([, stamp]) => typeof stamp === 'string' && stamp.includes('T') && Number.isFinite(Date.parse(stamp)))
    .map(([key, stamp]) => `${key} ${at(stamp)}`)
  const watermarkDisplay = typeof value.watermark === 'string' ? at(value.watermark)
    : typeof watermark.trading_day === 'string' ? watermark.trading_day : sourceTimes
  return [
    ['领域状态', value.domain_status],
    ['部署版本', value.deployment ?? '未上报'],
    ['部署提交', value.commit],
    ['部署代次', value.generation ?? '未上报'],
    ['绑定授权', authorization.status],
    ['开仓开关', authorization.opening_enabled],
    ['交易范围', authorization.scope_status],
    ['可执行品种数', authorization.executable_products],
    ['Canonical 计算', asFacts(value.diagnostics).canonical_compute],
    ['心跳原始状态', value.heartbeat_status],
    ['最近心跳', value.heartbeat_at ? at(value.heartbeat_at) : '未上报'],
    ['数据水位', (Array.isArray(watermarkDisplay) ? watermarkDisplay.length > 0 : watermarkDisplay)
      ? watermarkDisplay : '待核验'],
    ['归档凭证', watermark.receipt],
    ['最近日志信号柱', value.latest_journal_signal_at ? at(value.latest_journal_signal_at) : null],
    ['Run', value.run_id],
    ['Journal 序号', value.sequence],
    ['原生读回', value.readback_status],
    ['读回时间', value.readback_at ? at(value.readback_at) : null],
  ].filter(([, fact]) => fact != null)
})
const sourceGaps = computed(() => rows(asFacts(currentRuntime.value?.diagnostics).missing_observations))
const newowFacts = computed(() => [
  { label: '策略动作', items: rows(evidence.value?.actions), id: 'signal_id', time: 'bar_end', state: 'action' },
  { label: '提示', items: rows(evidence.value?.hints), id: 'hint_id', time: 'bar_end', state: 'quantity_effect' },
])
</script>

<template>
  <div class="strategy-center">
    <main>
      <header class="heading">
        <div><h1>策略中心</h1><small v-if="componentVersion">v{{ componentVersion }}</small></div>
        <button type="button" :disabled="refreshing" @click="refresh">{{ refreshing ? '正在读取' : '刷新' }}</button>
      </header>
      <p v-if="error" role="alert">策略目录读取失败</p>
      <div class="workspace">
        <aside aria-label="策略目录">
          <section v-for="domain in domains" :key="domain.id" class="domain">
            <header><h2>{{ domain.label }}</h2><span>{{ statusOf(runtime[domain.id]) }}</span></header>
            <RouterLink v-for="item in items.filter(entry => entry.domain === domain.id)" :key="item.strategy_id"
              :to="{ name: 'strategies', params: { strategyId: item.strategy_id } }"
              :aria-current="selectedId === item.strategy_id ? 'page' : undefined">
              <strong>{{ item.name }}</strong><small>{{ kinds[item.kind] }} · {{ domain.result }}</small>
            </RouterLink>
          </section>
        </aside>

        <article v-if="selected" aria-label="策略详情">
          <header class="detail-heading">
            <div><h2>{{ selected.name }}</h2><p>{{ selected.description }}</p><code>{{ selected.strategy_id }}</code></div>
            <div class="strategy-links">
              <span>{{ lifecycle }}</span>
              <RouterLink v-if="selectedChart" :to="selectedChart">在看盘中查看 {{ product.toUpperCase() }} · {{ frequency }}</RouterLink>
              <RouterLink :to="{ name: 'backtests', query: backtestQuery }">查看回测资格与配置</RouterLink>
            </div>
          </header>
          <p v-if="detailError" role="alert">策略详情读取失败</p>
          <section v-else-if="detail">
            <h3>支持范围与版本</h3>
            <p class="source">{{ detail.source }} <code v-if="detail.capability_version">{{ detail.capability_version }}</code></p>
            <p v-if="detail.status">{{ statusOf(detail as StrategyProjection) }} · {{ detail.diagnostic }}</p>
            <p v-else>{{ frequencies.join(' / ') }}</p>
            <p v-if="selected.dependencies.length">融合来源 · {{ selected.dependencies.map(key => items.find(item => item.strategy_id === key)?.name ?? key).join(' + ') }}</p>
            <p v-if="selected.domain === 'htdy'">60m 完成信号 · 1m 执行准入 · 原始公式有重绘，历史信号用于回看观察</p>
            <p v-if="detail.policy">支持品种 · {{ text(detail.policy.products) }}</p>
            <p v-if="detail.policy">初始资金 {{ detail.policy.initial_cash }} · 每品种 {{ detail.policy.max_lots }} 手 · 单笔预算 {{ detail.policy.trade_loss_budget }} · 日亏预算 {{ detail.policy.daily_loss_budget }} · 保证金比例 {{ detail.policy.margin_fraction }}</p>
            <div v-if="selected.domain === 'newow' && frequencies.length" class="selection">
              <label>周期 <select v-model="frequency"><option v-for="period in frequencies" :key="period">{{ period }}</option></select></label>
              <label>品种 <select v-model="product"><option v-for="symbol in products" :key="symbol" :value="symbol">{{ symbol.toUpperCase() }}</option></select></label>
            </div>
            <dl v-if="references.length">
              <template v-for="item in references" :key="item.kind + item.value">
                <dt>{{ versionKinds[item.kind] ?? item.kind }}</dt><dd><code>{{ item.value }}</code><small>{{ item.source }}</small></dd>
              </template>
            </dl>
          </section>
          <p v-else>正在读取策略详情</p>

          <section>
            <h3>运行与授权</h3>
            <p>{{ statusOf(currentRuntime) }} <code v-if="currentRuntime?.diagnostic">{{ currentRuntime.diagnostic }}</code></p>
            <p v-if="currentRuntime" class="source">{{ currentRuntime.source }} · {{ at(currentRuntime.source_as_of) }}</p>
            <dl>
              <template v-for="[label, value] in runtimeFacts" :key="String(label)"><dt>{{ label }}</dt><dd>{{ text(value) }}</dd></template>
              <template v-if="selected.domain === 'htdy'"><dt>开仓权限</dt><dd>{{ text(asFacts(currentRuntime?.authorization).opening_enabled) }}</dd></template>
              <template v-if="selected.domain === 'subing'"><dt>自动下单</dt><dd>{{ text(asFacts(currentRuntime?.authorization).auto_order) }}</dd></template>
            </dl>
            <ul v-if="sourceGaps.length">
              <li v-for="(gap, index) in sourceGaps" :key="index">{{ gap.product }} {{ gap.frequency }} · 缺 {{ gap.count }} 根 · {{ at(gap.first_missing_at) }}</li>
            </ul>
          </section>

          <section v-if="detail?.capability">
            <h3>已登记绑定</h3>
            <p>{{ statusOf(bindings) }} <code v-if="bindings?.diagnostic">{{ bindings.diagnostic }}</code></p>
            <p v-if="bindings" class="source">{{ bindings.source }} · {{ at(bindings.source_as_of ?? bindings.read_at) }}</p>
            <template v-if="selected.domain === 'newow'">
              <p v-for="stream in [...(bindings?.historical ? [asFacts(bindings.historical)] : []), ...rows(bindings?.forward)]" :key="String(stream.stream_id)">
                {{ stream.recording_mode }} · {{ stream.health }} · <code>{{ stream.stream_id }}</code>
              </p>
            </template>
            <p v-if="selected.domain === 'htdy' && bindings?.scope">快期 Scope · {{ text(asFacts(bindings.scope).version) }} · {{ text(asFacts(bindings.scope).products) }}</p>
            <p v-if="selected.domain === 'subing' && bindings?.run_id">共享成员 · {{ text(bindings.products) }}</p>
          </section>

          <section v-if="detail?.capability">
            <h3>{{ selected.domain === 'newow' ? '参考结果' : selected.domain === 'htdy' ? '原生模拟账户与回报' : '模型账户与历史回放' }}</h3>
            <p>{{ statusOf(evidence) }} <code v-if="evidence?.diagnostic">{{ evidence.diagnostic }}</code></p>
            <p v-if="evidence" class="source">{{ evidence.source }} · {{ at(evidence.source_as_of) }}</p>
            <template v-if="selected.domain === 'newow'">
              <p v-if="evidence?.current_publication === 'NOT_PUBLISHED'">当前盘后凭证尚无已发布结果</p>
              <p v-if="evidence?.current_publication === 'UNAVAILABLE'">当前盘后结果待核验 <code>{{ evidence.current_diagnostic }}</code></p>
              <template v-if="evidence && ['PUBLISHED', 'HISTORICAL_RESULT'].includes(evidence.status)">
                <p>交易日 {{ text(evidence.action_trading_day) }} · 修订 <code>{{ asFacts(evidence.result).revision_id }}</code> · 序号 {{ asFacts(evidence.result).seq }}</p>
                <p v-if="asFacts(evidence.result).receipt">盘后凭证 <code>{{ asFacts(evidence.result).receipt }}</code></p>
                <div class="result-grid">
                  <div v-for="group in newowFacts" :key="group.label">
                    <h4>{{ group.label }}</h4>
                    <p v-if="!group.items.length">{{ evidence.presentation_status === 'not_materialized' ? '该窗口缺少已保存图表证据' : '该窗口暂无记录' }}</p>
                    <p v-for="(point, index) in group.items" :key="text(point[group.id]) + index">
                      {{ text(point[group.state] ?? point.kind) }} · {{ at(point[group.time]) }}<br>
                      <code>{{ text(point[group.id] ?? point.source_signal_id) }}</code>
                    </p>
                  </div>
                  <div><h4>最近参考交易</h4>
                    <small>截至 {{ at(evidence.trade_cutoff) }}</small>
                    <p v-if="!rows(evidence.reference_trades).length">暂无参考交易</p>
                    <p v-for="record in rows(evidence.reference_trades)" :key="String(record.reference_trade_id)">
                      {{ record.physical_contract }} · {{ record.status }} · 参考收益率 {{ text(record.reference_return) }}<br>
                      {{ at(record.entry_bar_end) }}<template v-if="record.exit_bar_end"> → {{ at(record.exit_bar_end) }}</template><br>
                      <code>{{ record.public_reference_trade_id }}</code>
                    </p>
                    <small v-if="evidence.more_trades">此处展示最近 8 笔</small>
                  </div>
                </div>
              </template>
              <RouterLink to="/research">牛哇盘后研究</RouterLink>
            </template>
            <template v-else-if="selected.domain === 'htdy'">
              <p v-if="evidence?.account">原生读回 {{ evidence.readback_status }} · 账户权益 {{ text(asFacts(evidence.metrics).equity) }} · 已用保证金 {{ text(asFacts(evidence.metrics).used_margin) }}</p>
              <div v-if="evidence?.records" class="result-grid">
                <div v-for="(label, kind) in recordKinds" :key="kind">
                  <h4>{{ label }}</h4>
                  <p v-if="!rows(asFacts(evidence.records)[kind]).length">快照暂无记录</p>
                  <p v-for="record in rows(asFacts(evidence.records)[kind])" :key="String(record.id)">
                    {{ record.contract }} · {{ record.label }} · {{ at(record.at) }}<br><code>{{ record.id }}</code>
                  </p>
                </div>
              </div>
              <RouterLink to="/market?tab=simulation">打开快期监控</RouterLink>
            </template>
            <template v-else>
              <template v-if="evidence?.run_id">
                <p>快照运行状态 {{ evidence.runtime_status }} · 组合权益 {{ text(asFacts(evidence.account).equity) }} · 保证金 {{ text(asFacts(evidence.account).margin) }} · 日内净损益 {{ text(evidence.day_net) }}</p>
                <p v-if="Array.isArray(asFacts(evidence.account).valuation_unproven) && (asFacts(evidence.account).valuation_unproven as unknown[]).length">估值待核验 · {{ text(asFacts(evidence.account).valuation_unproven) }}</p>
                <table>
                  <thead><tr><th scope="col">品种</th><th scope="col">合约与状态</th><th scope="col">最近决策</th><th scope="col">模型成交</th></tr></thead>
                  <tbody><tr v-for="row in rows(evidence.products)" :key="String(row.product)">
                    <th scope="row">{{ String(row.product).toUpperCase() }}</th>
                    <td><p v-for="contract in rows(row.contracts)" :key="String(contract.contract)">{{ contract.contract }} · {{ contract.status }} · {{ at(contract.valuation_at) }}</p><span v-if="!rows(row.contracts).length">暂无合约快照</span></td>
                    <td><p v-for="contract in rows(row.contracts)" :key="String(contract.contract)">{{ text(asFacts(contract.latest_decision).status ?? asFacts(contract.latest_decision).reason) }}</p></td>
                    <td><template v-for="contract in rows(row.contracts)" :key="String(contract.contract)"><p v-for="(fill, index) in rows(contract.fills)" :key="index">{{ contract.contract }} {{ fill.action }} · {{ fill.price }} · {{ at(fill.fill_at) }}</p></template></td>
                  </tr></tbody>
                </table>
              </template>
              <p v-if="evidence?.history">历史回放 · {{ statuses[String(asFacts(evidence.history).status)] ?? text(asFacts(evidence.history).status) }} <code v-if="asFacts(evidence.history).run_id">{{ asFacts(evidence.history).run_id }}</code></p>
              <div class="selection"><RouterLink to="/research/subing-decision">持续模型</RouterLink><RouterLink to="/research/subing-decision?mode=history">历史回放</RouterLink></div>
            </template>
          </section>
        </article>
        <section v-else-if="!selectedId && items.length" aria-label="策略一览" class="strategy-overview">
          <h2>策略一览</h2>
          <table><thead><tr><th>策略</th><th>目录身份</th><th>证据来源</th><th>领域状态</th></tr></thead><tbody>
            <tr v-for="item in items" :key="item.strategy_id"><th><RouterLink :to="{ name: 'strategies', params: { strategyId: item.strategy_id } }">{{ item.name }}</RouterLink></th>
              <td><code>{{ item.strategy_id }}</code></td><td>{{ domains.find(domain => domain.id === item.domain)?.result }}</td><td>{{ statusOf(runtime[item.domain]) }}</td></tr>
          </tbody></table>
        </section>
        <p v-else class="empty">{{ selectedId && items.length ? '策略不存在' : error ? '请刷新目录' : items.length ? '选择策略查看详情' : '正在读取策略目录' }}</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.strategy-overview { min-width: 0; overflow: auto; padding: 16px; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: 6px; }
.strategy-overview h2 { margin: 0 0 10px; }
@media(max-width: 760px) { .strategy-center .workspace { grid-template-columns: minmax(0,1fr); } }
.strategy-links { display: grid; gap: 7px; justify-items: end; }
.strategy-center { min-height: 100%; background: var(--gy-bg-app); }
main { max-width: 1550px; margin: auto; padding: 24px 32px; }
.heading, .detail-heading, .domain header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
h1 { display: inline-block; margin: 0 12px 0 0; font-size: 24px; }
h2, h3, h4 { margin: 0; }
.detail-heading h2 { font-size: 21px; }
h3 { font-size: 16px; }
h4 { font-size: 14px; }
p, ul { margin: 8px 0; }
small, .source, .empty, .heading small, .detail-heading span, .domain header span { color: var(--gy-text-secondary); }
.workspace { display: grid; grid-template-columns: 232px minmax(0, 1fr); align-items: start; gap: 16px; margin-top: 18px; }
aside { display: grid; gap: 12px; }
article { min-width: 0; display: grid; gap: 12px; }
.domain, article > section, .detail-heading, .empty { padding: 16px; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); }
.domain header { margin-bottom: 8px; }
.domain h2 { font-size: 15px; }
.domain header span { font-size: 12px; }
.domain a { display: block; padding: 8px; border-radius: var(--gy-radius-sm); color: inherit; text-decoration: none; }
.domain a small, dd small { display: block; }
.domain a:hover { background: var(--gy-bg-hover); }
.domain a[aria-current="page"] { background: var(--gy-detail-accent-soft); }
button, select { padding: 5px 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); color: inherit; font: inherit; }
button:not(:disabled) { cursor: pointer; }
button:focus-visible, select:focus-visible, a:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.selection { display: flex; align-items: center; gap: 16px; margin: 10px 0; }
dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 12px; margin: 10px 0 0; }
dt { color: var(--gy-text-secondary); }
dd { margin: 0; overflow-wrap: anywhere; }
code { overflow-wrap: anywhere; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: 12px; margin: 14px 0; }
.result-grid > div { padding: 10px; border: 1px solid var(--gy-border-subtle); border-radius: var(--gy-radius-sm); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px; text-align: left; border-bottom: 1px solid var(--gy-border-subtle); }
</style>
