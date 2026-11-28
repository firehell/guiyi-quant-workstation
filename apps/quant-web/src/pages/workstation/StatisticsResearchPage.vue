<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarketNavigation from '@/components/market/MarketNavigation.vue'
import request from '@/api/request'

type Kind = 'backtest' | 'case' | 'factor' | 'event' | 'fills' | 'panel' | 'event_test' | 'search'
type Run = { run_id: string; product: string; contract: string; strategy_id: string; frequency: string;
  qualification: string; formula_version: string; start: string; end: string }
type Task = { id: string; status: string; reason?: string; started_at?: string;
  request: { source: { kind: Kind; run_id?: string } }; result?: Analysis }
type Analysis = {
  source: Record<string, string>
  policy: Record<string, unknown>
  coverage: Record<string, unknown>
  performance?: { cumulative: number; annualized: number; max_drawdown: number; daily_win_rate: number;
    sessions: number; sharpe: number | null; sortino: number | null; calmar: number | null;
    monthly: Record<string, number>; drawdown_span: { trading_days: number; ongoing: boolean } }
  native?: Record<string, string>
  native_scope?: string
  trades?: Record<string, unknown>
  groups?: Array<{ group: string; closed: number; win_rate: string | null; net_closed_pnl: string }>
  factor_groups?: Record<string, { n: number; mean_label: number }>
  trade_path?: Record<string, unknown>
  factor?: Record<string, number>
  event?: Record<string, { n: number; mean_label: number | null }>
  unavailable?: Record<string, string>
  advanced?: { estimand: string; estimate: Estimate; months: Record<string, Estimate>; hac_lag: number;
    eligible_cross_sections?: number; excluded?: unknown; missing_member_counts?: unknown;
    accepted_events?: number; purged_overlapping_events?: number; excluded_unpaired_days?: number;
    quantiles?: Record<string, { mean_label: number; member_observations: number; trading_days: number }> }
  experiment_plan?: { delays: number[]; scored: boolean }
}
type Estimate = { n: number; mean: number | null; interval: number[] | null; p: number | null; p_bh?: number; reason?: string }
const foldFields = [
  ['train_warmup_start', '训练预热起点'], ['train_start', '训练起点'], ['train_end', '训练终点'],
  ['test_warmup_start', '测试预热起点'], ['test_start', '测试起点'], ['test_end', '测试终点'],
] as const
type Fold = Record<typeof foldFields[number][0], string>
function newFold(): Fold { return Object.fromEntries(foldFields.map(([key]) => [key, ''])) as Fold }
type Source = { kind: string; status: string }
const root = '/statistics-research'
const route = useRoute()
const router = useRouter()
const modes: Array<[Kind, string]> = [['backtest', '回测统计'], ['case', '交易案例'], ['fills', '账户与参考证据'], ['factor', '因子实验'], ['event', '突破事件'], ['panel', '同步横截面'], ['event_test', '事件稳健检验'], ['search', 'OOS 参数方案']]
const mode = ref<Kind>('backtest')
const sources = ref<Source[]>([])
const worker = ref(false)
const version = ref('')
const catalogError = ref('')
const taskError = ref('')
const listError = ref('')
const runs = ref<Run[]>([])
const runTotal = ref(0)
const runOffset = ref(0)
const productFilter = ref('')
const strategyFilter = ref('')
const frequencyFilter = ref('')
const recent = ref<Task[]>([])
const compareLeft = ref('')
const compareRight = ref('')
const comparisonError = ref('')
const comparison = ref<{ members: Array<Pick<Analysis, 'source' | 'coverage' | 'trades' | 'performance'> & { id: string }>;
  comparable: boolean; different_or_missing: string[] }>()
const comparableTasks = computed(() => recent.value.filter(task => task.status === 'SUCCEEDED' && task.request.source.kind === 'backtest'))
async function compare() {
  comparisonError.value = ''
  comparison.value = undefined
  try {
    comparison.value = await request.get<unknown, NonNullable<typeof comparison.value>>(root + '/comparison',
      { params: { left: compareLeft.value, right: compareRight.value } })
  } catch (error) { comparisonError.value = message(error) }
}
const active = ref<Task>()
const month = ref('')
const tradeGroup = ref('')
const sampleOffset = ref(0)
const sampleTotal = ref(0)
const sampleRows = ref<Record<string, unknown>[]>([])
const pending = ref('')
const runId = ref('')
const caseId = ref('')
const book = ref('SIMNOW')
const scope = ref('')
const evidenceDay = ref('')
const panelMembers = ref<string[]>([])
const eventMember = ref('')
const hacLag = ref(2)
const delayChoices = ref([0, 1, 2, 3])
const budget = ref(3)
const seed = ref(13)
const folds = ref<Fold[]>([newFold()])
const submittingExperiment = ref(false)
async function submitExperiment() {
  const id = active.value?.id
  if (!id || submittingExperiment.value) return
  submittingExperiment.value = true
  try {
    const result = await request.post<unknown, { experiment_id: string }>(root + '/tasks/' + id + '/submit-experiment')
    await router.push({ name: 'backtests', query: { view: 'validation', experiment: result.experiment_id } })
  } catch (error) { taskError.value = message(error) }
  finally { submittingExperiment.value = false }
}
const contract = ref('FU2603')
const product = ref('fu')
const since = ref('')
const through = ref('')
const frequency = ref('60m')
const feature = ref('trend_direction')
const result = computed(() => active.value?.result)
const performance = computed(() => result.value?.performance)
const summary = computed(() => performance.value ? [
  ['累计净收益', percent(performance.value.cumulative)],
  ['复合年化', percent(performance.value.annualized)],
  ['最大回撤幅度', percent(performance.value.max_drawdown)],
  ['日胜率', percent(performance.value.daily_win_rate)],
  ['Sharpe', format(performance.value.sharpe)],
  ['Sortino', format(performance.value.sortino)],
  ['Calmar', format(performance.value.calmar)],
  ['回撤持续期', performance.value.drawdown_span.trading_days + ' 个交易日' + (performance.value.drawdown_span.ongoing ? '，未恢复' : '')],
] : [])
const evidenceColumns: Record<Kind, Array<[string, string]>> = {
  backtest: [['trading_day', '交易日'], ['at', '结算时刻'], ['equity', '已对账权益'], ['native_equity', '原生权益'], ['settlement_price', '结算价']],
  fills: [['trading_day', '交易日'], ['occurred_at', '时刻'], ['native_id', '来源 ID'], ['action', '动作'],
    ['price', '价格'], ['quantity', '数量'], ['fee', '费用']],
  panel: [['member', '源研究 ID'], ['available_at', '同步时点'], ['feature', '特征'], ['label', '观察标签'], ['trading_day', '交易日']],
  event_test: [['at', '突破 Bar'], ['available_at', '确认检查时点'], ['confirmed', '是否确认'], ['label_available_at', '标签结束'], ['label', '观察标签']],
  search: [],
  case: [['trading_day', '交易日'], ['at', '执行时刻'], ['action', '动作'], ['native_id', '原生 ID'], ['price', '成交价'],
    ['quantity', '数量'], ['remaining', '剩余'], ['fees_to_date', '累计费用']],
  factor: [['at', '特征 Bar'], ['feature', '特征值'], ['label', '观察标签'], ['label_available_at', '标签结束']],
  event: [['at', '突破 Bar'], ['event', '方向'], ['anchor_at', '确认检查时点'], ['confirmed', '是否确认'],
    ['label', '方向调整后标签'], ['label_available_at', '标签结束']],
}
const columns = computed(() => tradeGroup.value ? [
  ['trade_id', '原生成交 ID'], ['entry_at', '入场'], ['exit_at', '离场'], ['quantity', '手数'],
  ['net_pnl', '净盈亏'], ['fees', '费用'],
] : evidenceColumns[(result.value?.source.kind ?? 'backtest') as Kind])
function percent(value: number | null) { return value === null ? '缺项' : (value * 100).toFixed(4) + '%' }
function format(value: number | null) { return value === null ? '缺项' : value.toFixed(4) }
function message(error: unknown) {
  return (error as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail?.code ?? '请求失败'
}
function show(value: unknown): string {
  return value === null || value === undefined ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)
}
async function loadSources() {
  try {
    const data = await request.get<unknown, { sources: Source[]; version: string; worker: boolean }>(root + '/sources')
    sources.value = data.sources
    version.value = data.version
    worker.value = data.worker
  } catch (error) { catalogError.value = message(error) }
}
async function loadRuns(offset = 0) {
  catalogError.value = ''
  try {
    const data = await request.get<unknown, { items: Run[]; total: number }>(root + '/backtests', { params: { offset, limit: 20, product: productFilter.value || undefined, strategy_id: strategyFilter.value || undefined,
      frequency: frequencyFilter.value || undefined } })
    runs.value = data.items
    runTotal.value = data.total
    runOffset.value = offset
  } catch (error) { runs.value = []; catalogError.value = message(error) }
}
async function loadTasks() {
  try { recent.value = (await request.get<unknown, { items: Task[] }>(root + '/tasks')).items; listError.value = '' }
  catch (error) { listError.value = message(error) }
}
let sampleSequence = 0
async function loadSamples(task: Task, offset = 0) {
  const sequence = ++sampleSequence
  try {
    const data = await request.get<unknown, { items: Record<string, unknown>[]; total: number }>(root + '/tasks/' + task.id + '/samples',
      { params: { offset, limit: 20, month: month.value || undefined, group: tradeGroup.value || undefined } })
    if (sequence !== sampleSequence) return
    sampleRows.value = data.items
    sampleTotal.value = data.total
    sampleOffset.value = offset
  } catch (error) { if (sequence === sampleSequence) taskError.value = message(error) }
}
async function chooseMonth(selected: string) {
  tradeGroup.value = ''
  month.value = selected
  sampleRows.value = []
  if (active.value?.status === 'SUCCEEDED') await loadSamples(active.value)
}
async function chooseGroup(group: string) {
  month.value = ''
  tradeGroup.value = group
  sampleRows.value = []
  if (active.value?.status === 'SUCCEEDED') await loadSamples(active.value)
}
watch(() => route.params.taskId, async (value) => {
  const id = typeof value === 'string' ? value : ''
  active.value = undefined
  sampleSequence++
  sampleRows.value = []
  month.value = ''
  tradeGroup.value = ''
  sampleTotal.value = 0
  taskError.value = ''
  if (!id) return
  try {
    const data = await request.get<unknown, Task>(root + '/tasks/' + encodeURIComponent(id))
    if (route.params.taskId !== id) return
    active.value = data
    if (data.status === 'SUCCEEDED') await loadSamples(data)
  } catch (error) { if (route.params.taskId === id) taskError.value = message(error) }
}, { immediate: true })
onMounted(() => { void loadSources(); void loadRuns(); void loadTasks() })
async function submit(rerun = false) {
  if (pending.value) return
  pending.value = crypto.randomUUID()
  const id = pending.value
  const previous = active.value
  taskError.value = ''
  const source = rerun && previous ? previous.request.source : mode.value === 'backtest'
    ? { kind: 'backtest', run_id: runId.value }
    : mode.value === 'case' ? { kind: 'case', case_id: caseId.value }
    : mode.value === 'panel' ? { kind: 'panel', members: panelMembers.value, hac_lag: hacLag.value }
    : mode.value === 'event_test' ? { kind: 'event_test', member: eventMember.value, hac_lag: hacLag.value }
    : mode.value === 'search' ? { kind: 'search', base_run_id: runId.value, choices: delayChoices.value, budget: budget.value, seed: seed.value, folds: folds.value }
    : mode.value === 'fills' ? { kind: 'fills', book: book.value, day: evidenceDay.value, scope: scope.value, contract: contract.value }
      : { kind: mode.value, product: product.value, contract: contract.value, since: since.value,
          through: through.value, frequency: frequency.value, feature: feature.value }
  try {
    await request.post(root + '/tasks', { id, source, rerun_of: rerun ? previous?.id : undefined }, { timeout: 48000 })
    await router.push({ name: 'statistics-research', params: { taskId: id } })
    await loadTasks()
  } catch (error) { taskError.value = message(error) }
  finally { pending.value = '' }
}
async function cancel() {
  if (!pending.value) return
  try { await request.post(root + '/tasks/' + pending.value + '/cancel'); await loadTasks() }
  catch (error) { taskError.value = message(error) }
}
</script>

<template>
  <div class="research">
    <MarketNavigation active-tab="research" />
    <main>
      <header>
        <div><RouterLink to="/research">研究</RouterLink><h1>统计与研究中心</h1></div>
        <span v-if="version">v{{ version }}</span>
      </header>
      <div class="sources" aria-label="来源状态">
        <span v-for="source in sources" :key="source.kind">{{ ({ backtest: '历史回测', case: '交易日志', factor: '因子', event: '事件', paper: 'Paper', simnow: 'SimNow', reference: '页面参考', advanced: '高级研究' } as Record<string, string>)[source.kind] }}
          <small>{{ ({ AVAILABLE: '可用', NOT_CONFIGURED: '未配置', EXACT_CASE_REQUIRED: '指定案例', EXACT_PUBLISHED_RESEARCH_REQUIRED: '选择已发布样本', EXACT_ACCOUNT_SCOPE_REQUIRED: '指定来源范围', EXACT_MARKET_WINDOW_REQUIRED: '指定窗口', VERIFIED_ACCOUNT_SETTLEMENT_REQUIRED: '缺已核验账户结算' } as Record<string, string>)[source.status] }}</small>
        </span>
      </div>
      <section>
        <div class="tabs">
          <button v-for="[kind, label] in modes" :key="kind" :aria-pressed="mode === kind" @click="mode = kind">{{ label }}</button>
        </div>
        <form v-if="mode === 'backtest' || mode === 'search'" class="controls" @submit.prevent="loadRuns()">
          <label>品种 <input v-model="productFilter" placeholder="全部品种"></label>
          <label>策略 ID <input v-model="strategyFilter" placeholder="全部策略"></label>
          <label>周期 <select v-model="frequencyFilter"><option value="">全部</option><option v-for="f in ['5m', '15m', '30m', '60m', '1d', '1w']" :key="f">{{ f }}</option></select></label>
          <button>筛选</button>
        </form>
        <div v-if="mode === 'backtest' || mode === 'search'" class="scroll">
          <p v-if="catalogError" role="status">{{ catalogError }}</p>
          <table v-if="runs.length">
            <thead><tr><th>合约</th><th>策略 / 周期</th><th>窗口</th><th>资格</th><th>原始 Run</th><th>选择</th></tr></thead>
            <tbody><tr v-for="run in runs" :key="run.run_id">
              <td>{{ run.contract }}</td><td>{{ run.strategy_id }} · {{ run.frequency }}<br><small>{{ run.formula_version }}</small></td><td>{{ run.start }} 至 {{ run.end }}</td>
              <td>{{ run.qualification }}</td><td><RouterLink :to="{ name: 'backtests', params: { runId: run.run_id } }">查看 Run</RouterLink></td>
              <td><button :aria-pressed="runId === run.run_id" @click="runId = run.run_id">选取</button></td>
            </tr></tbody>
          </table>
          <div v-if="runTotal > 20" class="controls">
            <button :disabled="runOffset === 0" @click="loadRuns(runOffset - 20)">上一页</button><span>共 {{ runTotal }} 个 Run</span>
            <button :disabled="runOffset + 20 >= runTotal" @click="loadRuns(runOffset + 20)">下一页</button>
          </div>
        </div>
        <form class="controls" @submit.prevent="submit()">
          <label v-if="mode === 'backtest'">已发布 Run <input v-model="runId" required></label>
          <label v-else-if="mode === 'case'">案例 ID <input v-model="caseId" required></label>
          <template v-else-if="mode === 'panel' || mode === 'event_test'">
            <label v-if="mode === 'panel'">已发布因子研究（3 至 8 项）
              <select v-model="panelMembers" required multiple>
                <option v-for="item in recent.filter(r => r.status === 'SUCCEEDED' && r.request.source.kind === 'factor')" :key="item.id" :value="item.id">{{ item.id }}</option>
              </select>
            </label>
            <label v-else>已发布突破研究
              <select v-model="eventMember" required><option value="">请选择</option>
                <option v-for="item in recent.filter(r => r.status === 'SUCCEEDED' && r.request.source.kind === 'event')" :key="item.id" :value="item.id">{{ item.id }}</option>
              </select>
            </label>
            <label>HAC 滞后 <input v-model.number="hacLag" type="number" min="0" max="8" required></label>
          </template>
          <template v-else-if="mode === 'search'">
            <label>基础已发布 Run <input v-model="runId" required></label>
            <label v-for="delay in [0, 1, 2, 3]" :key="delay"><input v-model="delayChoices" type="checkbox" :value="delay">延迟 {{ delay }} 分钟</label>
            <label>候选数 <input v-model.number="budget" type="number" min="2" max="4" required></label>
            <label>随机种子 <input v-model.number="seed" type="number" min="0" max="4294967295" required></label>
            <fieldset v-for="(fold, index) in folds" :key="index">
              <legend>训练 / 测试折 {{ index + 1 }}</legend>
              <label v-for="[field, title] in foldFields" :key="field">{{ title }} <input v-model="fold[field]" type="date" required></label>
              <button v-if="index > 0" type="button" @click="folds.splice(index, 1)">移除该折</button>
            </fieldset>
            <button v-if="folds.length < 8" type="button" @click="folds.push(newFold())">添加一折</button>
          </template>
          <template v-else-if="mode === 'fills'">
            <label>来源 <select v-model="book"><option value="SIMNOW">SimNow</option><option value="SUBING_PAPER">苏冰共享 Paper</option><option value="NEWOW_REFERENCE">牛哇页面参考</option></select></label>
            <label>来源范围 <input v-model="scope" required></label>
            <label>物理合约 <input v-model="contract" required></label>
            <label>交易日 <input v-model="evidenceDay" type="date" required></label>
          </template>
          <template v-else>
            <label>品种 <input v-model="product" required pattern="[a-z]{1,8}"></label>
            <label>物理合约 <input v-model="contract" required></label>
            <label>周期 <select v-model="frequency"><option v-for="f in ['5m', '15m', '30m', '60m']" :key="f">{{ f }}</option></select></label>
            <label>起始交易日 <input v-model="since" type="date" required></label>
            <label>结束交易日 <input v-model="through" type="date" required></label>
            <label v-if="mode === 'factor'">特征 <select v-model="feature">
              <option value="trend_direction">ATR 标准化斜率</option><option value="atr">ATR / 收盘价</option>
              <option value="volume_ratio">量比</option><option value="obv">OBV</option>
              <option value="ema10">收盘相对 EMA10</option><option value="ema21">收盘相对 EMA21</option>
              <option value="ema60">收盘相对 EMA60</option><option value="macd">MACD 柱 / 收盘价</option>
              <option value="stddev">波动标准差 / 收盘价</option>
            </select></label>
          </template>
          <button class="primary" :disabled="!!pending || (!worker && mode !== 'case' && mode !== 'fills')">{{ pending ? '计算中' : '运行分析' }}</button>
          <button v-if="pending" type="button" @click="cancel">取消任务</button>
        </form>
        <p v-if="taskError" role="alert">{{ taskError }}</p>
      </section>
      <section v-if="active">
        <h2>分析结果</h2>
        <p v-if="active.status !== 'SUCCEEDED'" role="status">{{ active.status }} {{ active.reason }}</p>
        <template v-if="result">
          <div class="controls">
            <span>{{ result.source.contract }} {{ result.source.qualification }} {{ result.source.frequency }}</span>
            <RouterLink v-if="result.source.run_id" :to="{ name: 'backtests', params: { runId: result.source.run_id } }">原始 Run 与逐笔回放</RouterLink>
            <RouterLink v-if="result.source.case_id" :to="{ name: 'trade-journal', params: { caseId: result.source.case_id } }">原始案例、计划版本与成交</RouterLink>
            <button :disabled="!!pending" @click="submit(true)">按同一配置重跑</button>
          </div>
          <p v-if="performance" class="muted">共 {{ performance.sessions }} 个评价交易日 · 年化周期 252 · 无风险利率 0</p>
          <div v-if="summary.length" class="metrics"><div v-for="[label, value] in summary" :key="label"><small>{{ label }}</small><strong>{{ value }}</strong></div></div>
          <div v-if="performance" class="controls">
            <button :aria-pressed="month === ''" @click="chooseMonth('')">全部结算</button>
            <button v-for="[key, value] in Object.entries(performance.monthly)" :key="key" :aria-pressed="month === key" @click="chooseMonth(key)">
              {{ key }} · {{ percent(value) }}
            </button>
          </div>
          <p v-if="result.trades">已平 {{ result.trades.closed }} 笔 · 盈利 {{ result.trades.wins }} 笔 · 净平仓盈亏 {{ result.trades.net_closed_pnl }} {{ result.source.currency }}</p>
          <div v-if="result.groups?.length" class="scroll">
            <h3>策略交易矩阵</h3>
            <p class="muted">按方向和北京时间时段归组 · 已平样本 · {{ result.source.cost_basis }} · 无冻结市场状态证据</p>
            <table><thead><tr><th>方向 / 时段</th><th>样本</th><th>胜率</th><th>净盈亏</th></tr></thead>
              <tbody><tr v-for="group in result.groups" :key="group.group">
                <td><button :aria-pressed="tradeGroup === group.group" @click="chooseGroup(group.group)">{{ group.group }}</button></td>
                <td>{{ group.closed }}</td><td>{{ percent(group.win_rate === null ? null : Number(group.win_rate)) }}</td><td>{{ group.net_closed_pnl }}</td>
              </tr></tbody>
            </table>
          </div>
          <template v-if="result.trade_path">
            <p>已核对归案成交 {{ result.coverage.reconciled_fills }} 笔 · 闭合交易 {{ show(result.trade_path.closed_trades) }} · 最终平仓日 {{ show(result.trade_path.close_trading_day) }}</p>
            <p>方向符合事前计划 {{ show(result.trade_path.plan_direction_matches) }}</p>
            <details><summary>持仓窗口的价格路径</summary><p>{{ show(result.trade_path.price_excursion) }}</p><p>{{ show(result.trade_path.unavailable) }}</p></details>
          </template>
          <p v-if="result.factor">样本 {{ result.factor.n }} · 时序 Spearman {{ format(result.factor.spearman) }} · 平均观察收益 {{ percent(result.factor.mean_label) }}</p>
          <div v-if="result.factor_groups" class="controls">
            <span v-for="[group, stats] in Object.entries(result.factor_groups)" :key="group">分位 {{ group }} · {{ stats.n }} 条 · {{ percent(stats.mean_label) }}</span>
          </div>
          <p v-if="result.event">确认组 {{ result.event.confirmed?.n }} · 对照组 {{ result.event.control?.n }} · 平均观察收益 {{ percent(result.event.confirmed?.mean_label ?? null) }} / {{ percent(result.event.control?.mean_label ?? null) }}</p>
          <p v-if="result.coverage.reason || Object.keys(result.unavailable ?? {}).length" role="status">证据缺项 {{ show(result.coverage.reason) }} {{ show(result.unavailable) }}</p>
          <section v-if="result.advanced">
            <h3>{{ result.source.kind === 'panel' ? '同步 Rank IC' : '去重后的事件差值' }}</h3>
            <p>有效配对交易日 {{ result.advanced.estimate.n }} · 均值 {{ show(result.advanced.estimate.mean) }} · HAC 95% 区间 {{ show(result.advanced.estimate.interval) }}</p>
            <p v-if="result.advanced.estimate.reason">推断缺项 {{ result.advanced.estimate.reason }}</p>
            <p v-if="result.advanced.excluded">排除 {{ show(result.advanced.excluded) }} · 缺少成员 {{ show(result.advanced.missing_member_counts) }}</p>
            <p v-else>保留事件 {{ result.advanced.accepted_events }} · 重叠剔除 {{ result.advanced.purged_overlapping_events }} · 无配对交易日 {{ result.advanced.excluded_unpaired_days }}</p>
            <div v-if="result.advanced.quantiles" class="controls" aria-label="同步截面分位收益">
              <span v-for="[bucket, value] in Object.entries(result.advanced.quantiles)" :key="bucket">
                分位 {{ bucket }} · {{ percent(value.mean_label) }} · {{ value.member_observations }} 个成员观测 / {{ value.trading_days }} 日
              </span>
            </div>
            <table v-if="Object.keys(result.advanced.months).length">
              <thead><tr><th>月份</th><th>交易日</th><th>均值</th><th>HAC 区间</th><th>BH 调整 p 值</th></tr></thead>
              <tbody><tr v-for="[key, value] in Object.entries(result.advanced.months)" :key="key"><td>{{ key }}</td><td>{{ value.n }}</td><td>{{ show(value.mean) }}</td><td>{{ show(value.interval) }}</td><td>{{ show(value.p_bh) }}</td></tr></tbody>
            </table>
          </section>
          <section v-if="result.experiment_plan">
            <h3>待运行的 OOS / Walk-forward 方案</h3>
            <p>候选延迟 {{ result.experiment_plan.delays.join('、') }} 分钟 · 计划 Run 上限 {{ result.policy.total_native_run_limit }}</p>
            <button :disabled="submittingExperiment" @click="submitExperiment">提交到回测中心实验</button>
          </section>
          <details><summary>样本覆盖与计算口径</summary><dl><template v-for="[key, value] in Object.entries({ ...result.policy, ...result.coverage, ...result.source })" :key="key"><dt>{{ key }}</dt><dd>{{ show(value) }}</dd></template></dl></details>
          <details v-if="result.native"><summary>Plus 原生摘要</summary><p>{{ result.native_scope }}</p><dl><template v-for="[key, value] in Object.entries(result.native)" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></template></dl></details>
          <div class="scroll">
            <h3>{{ tradeGroup ? '闭合交易证据' : result.source.kind === 'backtest' ? '日结算证据' : '样本证据' }}</h3>
            <p>共 {{ sampleTotal }} 条<span v-if="month"> · {{ month }}</span></p>
            <table v-if="sampleRows.length">
              <thead><tr><th v-for="[key, label] in columns" :key="key">{{ label }}</th></tr></thead>
              <tbody><tr v-for="(row, index) in sampleRows" :key="index"><td v-for="[key] in columns" :key="key">{{ show(row[key]) }}</td></tr></tbody>
            </table>
            <div v-if="sampleTotal > 20" class="controls">
              <button :disabled="!sampleOffset" @click="loadSamples(active, sampleOffset - 20)">上一页证据</button>
              <button :disabled="sampleOffset + 20 >= sampleTotal" @click="loadSamples(active, sampleOffset + 20)">下一页证据</button>
            </div>
          </div>
        </template>
      </section>
      <section v-if="comparableTasks.length >= 2">
        <h2>已发布 Run 对照</h2>
        <form class="controls" @submit.prevent="compare">
          <label>研究 A <select v-model="compareLeft" required><option value="">请选择</option>
            <option v-for="item in comparableTasks" :key="item.id" :value="item.id">{{ item.request.source.run_id?.slice(0, 8) }} · {{ item.started_at?.slice(0, 16).replace('T', ' ') }}</option></select></label>
          <label>研究 B <select v-model="compareRight" required><option value="">请选择</option>
            <option v-for="item in comparableTasks" :key="item.id" :value="item.id">{{ item.request.source.run_id?.slice(0, 8) }} · {{ item.started_at?.slice(0, 16).replace('T', ' ') }}</option></select></label>
          <button :disabled="compareLeft === compareRight">并列查看</button>
        </form>
        <p v-if="comparisonError" role="alert">{{ comparisonError }}</p>
        <div v-if="comparison" class="scroll">
          <p>{{ comparison.comparable ? '口径匹配' : '仅可并列查看 · 差异或缺项 ' + comparison.different_or_missing.join('、') }}</p>
          <table><thead><tr><th>研究</th><th>合约 / 周期</th><th>策略公式</th><th>资格</th><th>已平样本</th><th>净收益</th></tr></thead>
            <tbody><tr v-for="item in comparison.members" :key="item.id">
              <td><RouterLink :to="{ name: 'statistics-research', params: { taskId: item.id } }">查看证据</RouterLink></td>
              <td>{{ item.source.contract }} · {{ item.source.frequency }}</td><td>{{ item.source.formula_version }}</td>
              <td>{{ item.source.qualification }}</td><td>{{ item.trades?.closed }}</td><td>{{ percent(item.performance?.cumulative ?? null) }}</td>
            </tr></tbody>
          </table>
        </div>
      </section>
      <section>
        <h2>近期研究</h2>
        <p v-if="listError" role="status">{{ listError }}</p>
        <p v-else-if="!recent.length" class="muted">暂无研究任务</p>
        <div v-else class="history"><RouterLink v-for="item in recent" :key="item.id" :to="{ name: 'statistics-research', params: { taskId: item.id } }">
          {{ modes.find(([kind]) => kind === item.request.source.kind)?.[1] }} · {{ item.status }} · {{ item.started_at?.slice(0, 16).replace('T', ' ') }}
        </RouterLink></div>
      </section>
    </main>
  </div>
</template>

<style scoped>
main{max-width:1200px;margin:auto;padding:24px;display:grid;gap:16px}
header{display:flex;align-items:center;justify-content:space-between}
h1{margin:6px 0 0;font-size:clamp(24px,4vw,34px)} h2{margin:0 0 12px;font-size:19px}
.sources,.controls,.tabs{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.sources>span{border:1px solid #50617455;border-radius:6px;padding:5px 9px}.sources small,.muted{opacity:.72}
section{border:1px solid #50617455;border-radius:10px;padding:16px;min-width:0}
form,.controls,.scroll,details{margin:12px 0}.scroll{overflow:auto}
table{border-collapse:collapse;width:100%;text-align:left;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid #50617445;white-space:nowrap}
button,input,select{font:inherit;color:inherit;border:1px solid #50617477;border-radius:5px;padding:4px 8px;background:transparent}
button{cursor:pointer}button:disabled{opacity:.45;cursor:default}button[aria-pressed="true"]{border-color:#5089cb;background:#5089cb22}
.primary{background:#2363a6;color:white}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(123px,1fr));gap:8px}
.metrics>div{border:1px solid #50617455;border-radius:6px;padding:10px}
.metrics strong{display:block;font-size:17px;font-variant-numeric:tabular-nums}
dl{display:grid;grid-template-columns:minmax(90px,auto) minmax(0,1fr);gap:3px 9px}dd{margin:0;overflow-wrap:anywhere}
.history{display:grid;gap:7px}fieldset{display:flex;gap:8px;flex-wrap:wrap;border:1px solid #50617455}
@media(max-width:600px){main{padding:12px}section{padding:11px}input{max-width:180px}}
</style>
