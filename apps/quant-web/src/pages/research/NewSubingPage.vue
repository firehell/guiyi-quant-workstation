<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import PerformancePanel from '@/components/performance/PerformancePanel.vue'
import ReturnCurveSvg from '@/components/charts/ReturnCurveSvg.vue'
import { returnCurveLayout } from '@/utils/returnCurveLayout'
import PageShell from '@/components/common/PageShell.vue'
import { getNewSubingEquityCurve, getNewSubingPage, getNewSubingProfiles, getNewSubingRun, getNewSubingRuns } from '@/api/newSubingResearch'
import type { NewSubingEquityCurve, NewSubingMetadata, NewSubingPage, NewSubingProfiles, NewSubingRunDetail } from '@/types/newSubingResearch'
import { appendResearchPage, normalizeResearchVisit, decisionMatches, researchCurvePoints, matchingProfile, matchingRun, metricText, runStateText, selectionToken } from '@/utils/newSubingResearch'

const visitKey = 'guiyi.research.new-subing.visit.v1'
function storedVisit() {
  try { return normalizeResearchVisit(JSON.parse(sessionStorage.getItem(visitKey) ?? 'null')) } catch { return normalizeResearchVisit(null) }
}
const initialVisit = storedVisit()
const products = ['AL', 'RB', 'TA'] as const
const scenarios = ['baseline', 'double_commission', 'double_slippage'] as const
const versions = ['new_subing_v2', 'new_subing_v1'] as const
const selectedVersion = ref<(typeof versions)[number]>(initialVisit.version)
const selectedCapital = ref(initialVisit.capital)
const selectedProduct = ref<(typeof products)[number]>(initialVisit.product)
const selectedScenario = ref<string>(initialVisit.scenario)
const runs = ref<NewSubingMetadata[]>([])
const profiles = ref<NewSubingProfiles | null>(null)
const detail = ref<NewSubingRunDetail | null>(null)
const pages = ref<Record<'decisions' | 'trades' | 'equity', NewSubingPage | null>>({ decisions: null, trades: null, equity: null })
const pageKind = ref<'decisions' | 'trades' | 'equity'>(initialVisit.kind)
const actionFilter = ref(initialVisit.action)
const query = ref(initialVisit.query)
const error = ref<string | null>(null)
const loading = ref(false)
const pageLoading = ref(false)
const curveData = ref<NewSubingEquityCurve | null>(null)
const curveError = ref<string | null>(null)
const curveLoading = ref(false)
const selectedCurvePoint = ref(0)
const pageError = ref<string | null>(null)
let generation = 0
let mounted = true

const available = computed(() => runs.value.filter(run => matchingRun(run, selectedVersion.value, selectedCapital.value, selectedProduct.value, selectedScenario.value)))
const latest = computed(() => available.value.at(-1) ?? null)
const ruleProfile = computed(() => profiles.value?.profiles.find(profile => matchingProfile(profile, selectedVersion.value, selectedCapital.value, selectedProduct.value)) ?? null)
const visibleItems = computed(() => {
  const items = pages.value[pageKind.value]?.items ?? []
  return pageKind.value === 'decisions' ? items.filter(item => decisionMatches(item, actionFilter.value, query.value)) : items
})
const curve = computed(() => returnCurveLayout(researchCurvePoints(curveData.value?.items ?? []), { headroom: 1.05, areaBaseline: 'bottom', valueUnit: 'currency' }))
const pointReadout = computed(() => curve.value.points[selectedCurvePoint.value] ?? null)
const fields = computed(() => pageKind.value === 'decisions' ? ['at', 'action', 'side', 'reason', 'target_qty', 'facts'] : pageKind.value === 'trades' ? ['entry_at', 'exit_at', 'side', 'net_pnl', 'status'] : ['at', 'equity', 'cash', 'qty', 'physical_contract'])
const fieldLabels: Record<string, string> = { at: '记录时间', action: '模型动作', side: '方向', reason: '原因', target_qty: '目标手数', facts: '事实依据', entry_at: '模型入场时间', exit_at: '模型退出时间', net_pnl: '模型净损益', status: '状态', equity: '模型权益', cash: '现金', qty: '净仓手数', physical_contract: '物理合约' }
const actionLabels: Record<string, string> = { ALL: '全部动作', SETUP: '候选准备', ADD_SETUP: '加仓准备', SETUP_INVALIDATED: '候选失效', OPEN: '模型建仓', ADD: '模型加仓', REDUCE: '模型减仓', REDUCE_SKIPPED: '模型减仓跳过', CLEAR: '模型清仓', CANCEL: '取消候选', REJECT: '拒绝', INTERRUPTED: '中断', LONG: '多头', SHORT: '空头', FLAT: '空仓', CLOSED: '已平', COMPLETED: '历史回放完成' }
const scenarioLabels: Record<string, string> = { baseline: '基准成本', double_commission: '双倍手续费', double_slippage: '双倍滑点' }
function inspectCurve(event: MouseEvent) {
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  const x = (event.clientX - rect.left) / rect.width * 712
  let nearest = 0
  curve.value.points.forEach((point, index) => { if (Math.abs(point.x - x) < Math.abs((curve.value.points[nearest]?.x ?? 0) - x)) nearest = index })
  selectedCurvePoint.value = nearest
}

async function loadCatalog() {
  const current = ++generation
  loading.value = true
  error.value = null
  try {
    const [profileResult, runResult] = await Promise.all([getNewSubingProfiles(), getNewSubingRuns()])
    if (current !== generation) return
    profiles.value = profileResult
    runs.value = runResult.runs
    await selectRun()
  } catch {
    if (current === generation) error.value = '冻结研究资料读取失败，请检查本地结果包。'
  } finally {
    if (current === generation) loading.value = false
  }
}

async function selectRun() {
  const current = ++generation
  const run = latest.value
  const token = selectionToken(run?.run_id ?? '', current)
  detail.value = null
  pages.value = { decisions: null, trades: null, equity: null }
  pageLoading.value = false
  curveData.value = null
  curveError.value = null
  pageError.value = null
  curveLoading.value = false
  selectedCurvePoint.value = 0
  error.value = null
  if (!run) { loading.value = false; return }
  loading.value = true
  try {
    const [newDetail, decisions, trades, equity] = await Promise.all([
      getNewSubingRun(run.run_id), getNewSubingPage(run.run_id, 'decisions'),
      getNewSubingPage(run.run_id, 'trades'), getNewSubingPage(run.run_id, 'equity'),
    ])
    if (token !== selectionToken(latest.value?.run_id ?? '', generation)) return
    if ([decisions, trades, equity].some(page => page.run_id !== run.run_id || page.sha256 !== decisions.sha256)) throw new Error('研究结果身份不一致')
    detail.value = newDetail
    pages.value = { decisions, trades, equity }
    curveLoading.value = true
    try {
      const fullCurve = await getNewSubingEquityCurve(run.run_id, decisions.sha256)
      if (token !== selectionToken(latest.value?.run_id ?? '', generation)) return
      if (fullCurve.run_id !== run.run_id || fullCurve.sha256 !== decisions.sha256) throw new Error('研究结果身份不一致')
      curveData.value = fullCurve
    } catch {
      if (current === generation) curveError.value = '完整权益曲线无法核验或读取；下方冻结摘要及明细不受影响。'
    } finally {
      if (current === generation) curveLoading.value = false
    }
  } catch {
    if (current === generation) error.value = '该冻结运行无法核验或读取。'
  } finally {
    if (current === generation) loading.value = false
  }
}

function selectVersion() {
  if (selectedVersion.value === 'new_subing_v1') selectedCapital.value = '100000'
  void selectRun()
}

async function nextPage() {
  const runId = detail.value?.metadata.run_id
  const kind = pageKind.value
  const cursor = pages.value[kind]?.next_cursor
  if (!runId || !cursor || pageLoading.value) return
  const token = selectionToken(runId, generation)
  pageLoading.value = true
  pageError.value = null
  try {
    const next = await getNewSubingPage(runId, kind, cursor)
    if (token !== selectionToken(detail.value?.metadata.run_id ?? '', generation)) return
    pages.value = { ...pages.value, [kind]: appendResearchPage(pages.value[kind]!, next) }
  } catch {
    if (token === selectionToken(detail.value?.metadata.run_id ?? '', generation)) pageError.value = '更多记录读取失败，已加载记录保留。'
  } finally {
    if (token === selectionToken(detail.value?.metadata.run_id ?? '', generation)) pageLoading.value = false
  }
}

function formatCell(value: unknown, field?: string): string {
  if (['action', 'side', 'status'].includes(field ?? '') && typeof value === 'string') return actionLabels[value] ?? value
  if (value === null || value === undefined) return '未提供'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function saveVisit() {
  try { sessionStorage.setItem(visitKey, JSON.stringify({ version: selectedVersion.value, capital: selectedCapital.value, product: selectedProduct.value, scenario: selectedScenario.value, kind: pageKind.value, action: actionFilter.value, query: query.value, scroll: window.scrollY })) } catch { /* optional visit preferences */ }
}
function resetVisit() {
  selectedVersion.value = 'new_subing_v2'; selectedCapital.value = '100000'; selectedProduct.value = 'AL'; selectedScenario.value = 'baseline'
  pageKind.value = 'decisions'; actionFilter.value = 'ALL'; query.value = ''
  void selectRun()
  window.scrollTo(0, 0)
  saveVisit()
}
watch([selectedVersion, selectedCapital, selectedProduct, selectedScenario, pageKind, actionFilter, query], saveVisit)
onBeforeUnmount(() => { saveVisit(); mounted = false; generation++ })
onMounted(async () => { await loadCatalog(); await nextTick(); if (mounted && typeof window !== 'undefined') window.scrollTo(0, initialVisit.scroll) })
</script>

<template>
  <PageShell title="新苏冰策略 · 历史研究" subtitle="V1 / V2 冻结结果只读" :error="error" :loading="loading" @retry="loadCatalog">
    <template #badges>
      <span class="badge">历史回放</span><span class="badge">自动交易关闭</span><span class="badge">案例一致性待验</span><span class="badge">独立 OOS 未证明</span>
    </template>
    <div class="research-page">
      <section class="card intro">
        <h3>规则与来源</h3>
        <p v-if="selectedVersion === 'new_subing_v2'">V2 按交易阶段记录试探、突破确认、回调和趋势；5m 切入、15m 确认，1m 完成事实用于硬止损，模型成交只在严格后续可交易 1m 开盘。10 万元为主结果；100 万元仅供方法诊断，不是主结果。</p>
        <p v-else>V1：日线定方向，15m 确认，5m 决策；满足基础约束、五项至少三票及新触发后建立 setup，连续三根 5m 保持后确认。完成 1m 收盘用于退出检测，模型成交只在后续可交易 1m 开盘。</p>
        <p>规则来源：用户提供的苏冰《交易从此开始》Notion 笔记原文；MA21、三票、统一净仓及执行细节为归一补充或用户选择。原案例逐案一致性尚未验证。页面收益仅为模型历史回放，不代表苏冰本人收益、Paper、Shadow 或实盘。</p>
        <p v-if="selectedVersion === 'new_subing_v2'" class="notice">来源口径：原文披露顺势、阶段与风控思想；本页精确阈值、事件仲裁和分层账户是归一量化 V2 映射。阶段记录与拒绝原因以本次冻结运行的诊断为准。</p>
        <p class="sources">笔记原文：<a href="https://app.notion.com/p/3705b8452a1a80509c01fd074770af4b" target="_blank" rel="noopener noreferrer">交易系统</a> · <a href="https://app.notion.com/p/3715b8452a1a8041a21aea76318a18ec" target="_blank" rel="noopener noreferrer">不同周期</a> · <a href="https://app.notion.com/p/3715b8452a1a8045b1b7c378482ec5bb" target="_blank" rel="noopener noreferrer">周期选择</a> · <a href="https://app.notion.com/p/3715b8452a1a806bb63df413405c30e3" target="_blank" rel="noopener noreferrer">原则</a></p>
        <details v-if="ruleProfile"><summary>查看 {{ selectedProduct }} {{ selectedCapital }} 元 Profile 原始规则</summary><pre>{{ JSON.stringify(ruleProfile.rules, null, 2) }}</pre></details>
        <p v-else class="muted">Profile 规则暂不可读取。</p>
      </section>
      <section class="card">
        <div class="chooser"><label>版本 <select v-model="selectedVersion" @change="selectVersion"><option v-for="version in versions" :key="version" :value="version">{{ version === 'new_subing_v2' ? 'V2 阶段修正' : 'V1 对照' }}</option></select></label><label>本金 <select v-model="selectedCapital" @change="selectRun"><option value="100000">10 万元 · 主结果</option><option v-if="selectedVersion === 'new_subing_v2'" value="1000000">100 万元 · 方法诊断</option></select></label><label>品种 <select v-model="selectedProduct" @change="selectRun"><option v-for="product in products" :key="product">{{ product }}</option></select></label><label>成本场景 <select v-model="selectedScenario" @change="selectRun"><option v-for="scenario in scenarios" :key="scenario">{{ scenarioLabels[scenario] }}</option></select></label><button @click="resetVisit">重置本页</button></div>
        <p v-if="!latest && !error" class="empty">该版本、本金、品种与成本场景尚无冻结运行结果；不可评价收益与交易。</p>
        <template v-else-if="detail">
          <div class="run-head"><strong>{{ selectedProduct }} · {{ selectedVersion === 'new_subing_v2' ? 'V2' : 'V1' }} · {{ selectedCapital }} 元 · {{ runStateText(detail.metadata.status) }}</strong><span class="muted">{{ detail.metadata.requested_since }} — {{ detail.metadata.requested_through }}</span></div>
          <p v-if="selectedVersion === 'new_subing_v2' && selectedCapital === '1000000'" class="notice">100 万元为方法诊断，非 10 万元主结果。</p>
          <PerformancePanel title="模型账户收益与权益" kind="模型账户" :since="detail.metadata.requested_since" :through="detail.metadata.requested_through" :version="detail.metadata.account_model_version ?? 'new_subing_account_v1'" :coverage="runStateText(detail.metadata.status)" :cutoff="String(curveData?.items.at(-1)?.at ?? '')" description="完整冻结研究窗口；模型净收益包含该运行成本，摘要不随明细加载或曲线抽样改变。" :loading="curveLoading" :error="curveError">
          <template #metrics><div class="metrics"><div><small>模型账户收益</small><strong>{{ metricText(detail.summary, 'account_return_pct', '%') }}</strong></div><div><small>期末权益</small><strong>{{ metricText(detail.summary, 'final_equity') }}</strong></div><div><small>已平模型交易</small><strong>{{ metricText(detail.summary, 'closed_trades') }}</strong></div><div><small>模型账户回撤</small><strong>{{ metricText(detail.summary, 'max_drawdown_pct', '%') }}</strong></div></div></template>
          <ReturnCurveSvg :plot="curve" label="完整冻结窗口模型权益曲线，单位元" @mousemove="inspectCurve" @click="inspectCurve" />
          <p v-if="curveData?.sampled" class="muted">完整 {{ curveData.total }} 条权益记录，绘图抽样 {{ curveData.items.length }} 个原始点；保留端点、极值与中断边界，不插值。</p>
          <p v-else-if="curveData" class="muted">完整 {{ curveData.total }} 条权益记录，不受明细分页影响。</p>
          <p v-if="!curveLoading && !curveError && !curve.points.length" class="empty">冻结结果未提供可绘制的完整权益记录。</p>
          <div v-if="pointReadout" class="curve-readout"><label>权益记录 <input v-model.number="selectedCurvePoint" type="range" min="0" :max="curve.points.length - 1" aria-label="选择权益记录" /></label><span>{{ pointReadout.at }} · {{ pointReadout.value }} 元</span></div>
          </PerformancePanel>
          <p v-if="detail.metadata.status !== 'COMPLETED'" class="notice">{{ runStateText(detail.metadata.status) }}：该结果不可用于收益判断。请查看诊断缺口。</p>
          <details><summary>身份、输入与执行事实</summary><dl><dt>run_id</dt><dd>{{ detail.metadata.run_id }}</dd><dt>代码 SHA</dt><dd>{{ detail.metadata.code_revision }}</dd><dt>公式 / Profile</dt><dd>{{ detail.metadata.formula_version }} / {{ detail.metadata.profile_id }}</dd><dt>风险 / 执行</dt><dd>{{ detail.metadata.risk_profile_version }} / {{ detail.metadata.execution_profile_version }}</dd><dt>账户模型</dt><dd>{{ detail.metadata.account_model_version ?? 'V1 旧账户模型' }}</dd><dt>行情输入 hash</dt><dd>{{ detail.metadata.input_snapshot_hash ?? '未证明' }}</dd><dt>执行事实 hash</dt><dd>{{ detail.metadata.execution_facts_hash ?? '未证明' }}</dd><dt>OOS</dt><dd>{{ detail.metadata.oos_status }}</dd><dt>案例</dt><dd>{{ detail.metadata.case_parity }}</dd></dl></details>
          <details v-if="selectedVersion === 'new_subing_v2'"><summary>阶段与层级记录</summary><pre>{{ JSON.stringify({ stages: detail.diagnostics.stages ?? detail.diagnostics.stage_summary ?? '未提供', layers: detail.diagnostics.layers ?? detail.diagnostics.layer_summary ?? '未提供' }, null, 2) }}</pre></details>
          <details><summary>诊断与拒绝背景</summary><pre>{{ JSON.stringify(detail.diagnostics, null, 2) }}</pre></details>
        </template>
      </section>
      <section v-if="detail" class="card">
        <h3>模型过程</h3>
        <div class="tabs"><button v-for="kind in (['decisions', 'trades', 'equity'] as const)" :key="kind" :class="{ active: pageKind === kind }" @click="pageKind = kind">{{ { decisions: '决策 / 拒绝', trades: '模型交易', equity: '权益明细' }[kind] }}</button></div>
        <div v-if="pageKind === 'decisions'" class="filters"><label>动作 <select v-model="actionFilter"><option v-for="action in ['ALL', 'SETUP', 'ADD_SETUP', 'SETUP_INVALIDATED', 'OPEN', 'ADD', 'REDUCE', 'REDUCE_SKIPPED', 'CLEAR', 'CANCEL', 'REJECT', 'INTERRUPTED']" :key="action" :value="action">{{ actionLabels[action] }}</option></select></label><label>已加载记录搜索 <input v-model="query" placeholder="原因或事实依据" /></label></div>
        <p v-if="!visibleItems.length" class="empty">{{ detail.metadata.status === 'COMPLETED' ? '已加载记录中没有匹配项。' : '证据不足，记录不可评价。' }}</p>
        <div v-else class="table-wrap"><table><thead><tr><th v-for="field in fields" :key="field">{{ fieldLabels[field] ?? field }}</th></tr></thead><tbody><tr v-for="(item, index) in visibleItems" :key="index"><td v-for="field in fields" :key="field"><details v-if="field === 'facts'"><summary>查看事实</summary><pre>{{ formatCell(item[field]) }}</pre></details><span v-else>{{ formatCell(item[field], field) }}</span></td></tr></tbody></table></div>
        <button v-if="pages[pageKind]?.next_cursor" class="more" :disabled="pageLoading" @click="nextPage">{{ pageLoading ? '读取中…' : '加载更多' }}</button>
        <p v-if="pageError" role="alert" class="notice">{{ pageError }}</p>
        <p class="muted">已加载 {{ pages[pageKind]?.items.length ?? 0 }} 条{{ pages[pageKind]?.next_cursor ? '，仍有更多记录' : '，已读取全部记录' }}。每次加载最多 50 条；筛选仅作用于已加载记录，完整权益曲线独立读取。</p>
      </section>
    </div>
  </PageShell>
</template>

<style scoped>
.research-page{display:grid;gap:18px;max-width:1440px;margin:auto}.card{background:var(--gy-bg-surface,var(--gy-bg-panel));border:1px solid var(--gy-border,#e2e8f0);border-radius:12px;padding:20px;box-shadow:0 3px 12px rgba(18,39,64,.04)}h3{margin:0 0 12px;font-size:17px}p{line-height:1.65}.muted,small{color:var(--gy-text-muted,#64748b)}.badge{font-size:12px;color:#475569;background:#eef3f8;border-radius:6px;padding:4px 8px}.chooser,.filters,.tabs,.run-head{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.run-head{justify-content:space-between;margin:20px 0 12px}.chooser label,.filters label{display:flex;align-items:center;gap:6px}select,input,button{font:inherit;border:1px solid var(--gy-border,#e2e8f0);border-radius:6px;padding:6px 9px;background:var(--gy-bg-panel);color:var(--gy-text-primary,#303133)}button{cursor:pointer}.tabs{margin:10px 0}.tabs .active{background:var(--gy-primary,#ff8a00);color:white;border-color:var(--gy-primary,#ff8a00)}.filters{margin-bottom:10px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metrics>div{display:grid;min-width:0;gap:4px;background:var(--gy-bg-muted,#f7f8fa);padding:12px;border-radius:8px}.metrics strong{font-size:18px;overflow-wrap:anywhere}.notice{border-left:3px solid #d99320;background:#fff8e9;padding:10px}.empty{color:#64748b;padding:20px 0}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid #e5ebf0;max-width:360px;overflow-wrap:anywhere}th{background:var(--gy-bg-muted,#f7f8fa)}.more{margin-top:12px}.curve-readout{display:flex;gap:12px;align-items:center;flex-wrap:wrap}details{margin-top:12px}summary{cursor:pointer;color:var(--gy-primary,#ff8a00)}pre{max-height:300px;overflow:auto;background:var(--gy-bg-muted,#f7f8fa);padding:12px;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:140px 1fr;gap:6px 10px;font-size:13px}dd{margin:0;overflow-wrap:anywhere}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
