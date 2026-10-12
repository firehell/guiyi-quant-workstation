<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageShell from '@/components/common/PageShell.vue'
import { getNewSubingPage, getNewSubingProfiles, getNewSubingRun, getNewSubingRuns } from '@/api/newSubingResearch'
import type { NewSubingMetadata, NewSubingPage, NewSubingProfiles, NewSubingRunDetail } from '@/types/newSubingResearch'
import { decisionMatches, equityPoints, metricText, runStateText, selectionToken } from '@/utils/newSubingResearch'

const products = ['AL', 'RB', 'TA'] as const
const scenarios = ['baseline', 'double_commission', 'double_slippage'] as const
const selectedProduct = ref<(typeof products)[number]>('AL')
const selectedScenario = ref<string>('baseline')
const runs = ref<NewSubingMetadata[]>([])
const profiles = ref<NewSubingProfiles | null>(null)
const detail = ref<NewSubingRunDetail | null>(null)
const pages = ref<Record<'decisions' | 'trades' | 'equity', NewSubingPage | null>>({ decisions: null, trades: null, equity: null })
const pageKind = ref<'decisions' | 'trades' | 'equity'>('decisions')
const actionFilter = ref('ALL')
const query = ref('')
const error = ref<string | null>(null)
const loading = ref(false)
const pageLoading = ref(false)
let generation = 0

const available = computed(() => runs.value.filter(run => run.product === selectedProduct.value && run.scenario === selectedScenario.value))
const latest = computed(() => available.value.at(-1) ?? null)
const ruleProfile = computed(() => profiles.value?.profiles.find(profile => profile.product === selectedProduct.value) ?? null)
const visibleItems = computed(() => {
  const items = pages.value[pageKind.value]?.items ?? []
  return pageKind.value === 'decisions' ? items.filter(item => decisionMatches(item, actionFilter.value, query.value)) : items
})
const curve = computed(() => equityPoints(pages.value.equity?.items ?? []))

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
  error.value = null
  if (!run) { loading.value = false; return }
  loading.value = true
  try {
    const [newDetail, decisions, trades, equity] = await Promise.all([
      getNewSubingRun(run.run_id), getNewSubingPage(run.run_id, 'decisions'),
      getNewSubingPage(run.run_id, 'trades'), getNewSubingPage(run.run_id, 'equity'),
    ])
    if (token !== selectionToken(latest.value?.run_id ?? '', generation)) return
    detail.value = newDetail
    pages.value = { decisions, trades, equity }
  } catch {
    if (current === generation) error.value = '该冻结运行无法核验或读取。'
  } finally {
    if (current === generation) loading.value = false
  }
}

async function nextPage() {
  const runId = detail.value?.metadata.run_id
  const kind = pageKind.value
  const cursor = pages.value[kind]?.next_cursor
  if (!runId || !cursor || pageLoading.value) return
  const token = selectionToken(runId, generation)
  pageLoading.value = true
  try {
    const next = await getNewSubingPage(runId, kind, cursor)
    if (token !== selectionToken(detail.value?.metadata.run_id ?? '', generation) || kind !== pageKind.value) return
    pages.value = { ...pages.value, [kind]: next }
  } catch {
    if (token === selectionToken(detail.value?.metadata.run_id ?? '', generation)) error.value = '下一页读取失败。'
  } finally {
    if (token === selectionToken(detail.value?.metadata.run_id ?? '', generation)) pageLoading.value = false
  }
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '未提供'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

onMounted(loadCatalog)
</script>

<template>
  <PageShell title="新苏冰策略 · 历史研究" subtitle="固定参数顺势波段 V1 · 冻结结果只读" :error="error" :loading="loading" @retry="loadCatalog">
    <template #badges>
      <span class="badge">historical_replay</span><span class="badge">auto_order=false</span><span class="badge">案例一致性待验</span><span class="badge">独立 OOS 未证明</span>
    </template>
    <div class="research-page">
      <section class="card intro">
        <h3>规则与来源</h3>
        <p>日线定方向，15m 确认，5m 决策；满足基础约束、五项至少三票及新触发后建立 setup，连续三根 5m 保持后确认。完成 1m 收盘用于退出检测，模型成交只在后续可交易 1m 开盘。</p>
        <p>规则来源：用户提供的苏冰《交易从此开始》Notion 笔记原文；MA21、三票、统一净仓及执行细节为归一补充或用户选择。原案例逐案一致性尚未验证。页面收益仅为模型历史回放，不代表苏冰本人收益、Paper、Shadow 或实盘。</p>
        <p class="sources">笔记原文：<a href="https://app.notion.com/p/3705b8452a1a80509c01fd074770af4b" target="_blank" rel="noopener noreferrer">交易系统</a> · <a href="https://app.notion.com/p/3715b8452a1a8041a21aea76318a18ec" target="_blank" rel="noopener noreferrer">不同周期</a> · <a href="https://app.notion.com/p/3715b8452a1a8045b1b7c378482ec5bb" target="_blank" rel="noopener noreferrer">周期选择</a> · <a href="https://app.notion.com/p/3715b8452a1a806bb63df413405c30e3" target="_blank" rel="noopener noreferrer">原则</a></p>
        <details v-if="ruleProfile"><summary>查看 {{ selectedProduct }} 固定 Profile 原始规则</summary><pre>{{ JSON.stringify(ruleProfile.rules, null, 2) }}</pre></details>
        <p v-else class="muted">Profile 规则暂不可读取。</p>
      </section>
      <section class="card">
        <div class="chooser"><label>品种 <select v-model="selectedProduct" @change="selectRun"><option v-for="product in products" :key="product">{{ product }}</option></select></label><label>成本场景 <select v-model="selectedScenario" @change="selectRun"><option v-for="scenario in scenarios" :key="scenario">{{ scenario }}</option></select></label></div>
        <p v-if="!latest" class="empty">该品种与场景尚无冻结运行结果；不可评价收益与交易。</p>
        <template v-else-if="detail">
          <div class="run-head"><strong>{{ selectedProduct }} · {{ runStateText(detail.metadata.status) }}</strong><span class="muted">{{ detail.metadata.requested_since }} — {{ detail.metadata.requested_through }}</span></div>
          <div class="metrics"><div><small>模型账户收益</small><strong>{{ metricText(detail.summary, 'account_return_pct', '%') }}</strong></div><div><small>期末权益</small><strong>{{ metricText(detail.summary, 'final_equity') }}</strong></div><div><small>已平模型交易</small><strong>{{ metricText(detail.summary, 'closed_trades') }}</strong></div><div><small>最大回撤</small><strong>{{ metricText(detail.summary, 'max_drawdown_pct', '%') }}</strong></div></div>
          <p v-if="detail.metadata.status !== 'COMPLETED'" class="notice">{{ runStateText(detail.metadata.status) }}：该结果不可用于收益判断。请查看诊断缺口。</p>
          <details><summary>身份、输入与执行事实</summary><dl><dt>run_id</dt><dd>{{ detail.metadata.run_id }}</dd><dt>代码 SHA</dt><dd>{{ detail.metadata.code_revision }}</dd><dt>公式 / Profile</dt><dd>{{ detail.metadata.formula_version }} / {{ detail.metadata.profile_id }}</dd><dt>风险 / 执行</dt><dd>{{ detail.metadata.risk_profile_version }} / {{ detail.metadata.execution_profile_version }}</dd><dt>行情输入 hash</dt><dd>{{ detail.metadata.input_snapshot_hash ?? '未证明' }}</dd><dt>执行事实 hash</dt><dd>{{ detail.metadata.execution_facts_hash ?? '未证明' }}</dd><dt>OOS</dt><dd>{{ detail.metadata.oos_status }}</dd><dt>案例</dt><dd>{{ detail.metadata.case_parity }}</dd></dl></details>
          <details><summary>诊断与拒绝背景</summary><pre>{{ JSON.stringify(detail.diagnostics, null, 2) }}</pre></details>
        </template>
      </section>
      <section v-if="detail" class="card">
        <h3>模型过程</h3>
        <div class="tabs"><button v-for="kind in (['decisions', 'trades', 'equity'] as const)" :key="kind" :class="{ active: pageKind === kind }" @click="pageKind = kind">{{ { decisions: '决策 / 拒绝', trades: '模型交易', equity: '权益曲线' }[kind] }}</button></div>
        <div v-if="pageKind === 'decisions'" class="filters"><label>动作 <select v-model="actionFilter"><option>ALL</option><option>BUILD</option><option>ADD</option><option>REDUCE</option><option>CLEAR</option><option>REJECT</option></select></label><label>本页搜索 <input v-model="query" placeholder="原因或 facts" /></label></div>
        <div v-if="pageKind === 'equity' && curve" class="curve" aria-label="本页模型权益曲线"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline :points="curve" /></svg></div>
        <p v-if="!visibleItems.length" class="empty">{{ detail.metadata.status === 'COMPLETED' ? '本页没有匹配记录。' : '证据不足，记录不可评价。' }}</p>
        <div v-else class="table-wrap"><table><thead><tr><th v-for="field in (pageKind === 'decisions' ? ['at', 'action', 'side', 'reason', 'target_qty', 'facts'] : pageKind === 'trades' ? ['entry_at', 'exit_at', 'side', 'net_pnl', 'status'] : ['at', 'equity', 'cash', 'qty', 'physical_contract'])" :key="field">{{ field }}</th></tr></thead><tbody><tr v-for="(item, index) in visibleItems" :key="index"><td v-for="field in (pageKind === 'decisions' ? ['at', 'action', 'side', 'reason', 'target_qty', 'facts'] : pageKind === 'trades' ? ['entry_at', 'exit_at', 'side', 'net_pnl', 'status'] : ['at', 'equity', 'cash', 'qty', 'physical_contract'])" :key="field">{{ formatCell(item[field]) }}</td></tr></tbody></table></div>
        <button v-if="pages[pageKind]?.next_cursor" class="more" :disabled="pageLoading" @click="nextPage">{{ pageLoading ? '读取中…' : '下一页' }}</button>
        <p class="muted">每页最多 50 条。筛选和曲线只作用于当前页；切换品种或场景时重新读取。</p>
      </section>
    </div>
  </PageShell>
</template>

<style scoped>
.research-page{display:grid;gap:18px;max-width:1440px;margin:auto}.card{background:var(--gy-bg-surface,#fff);border:1px solid var(--gy-border,#e2e8f0);border-radius:12px;padding:20px;box-shadow:0 3px 12px rgba(18,39,64,.04)}h3{margin:0 0 12px;font-size:17px}p{line-height:1.65}.muted,small{color:var(--gy-text-muted,#64748b)}.badge{font-size:12px;color:#475569;background:#eef3f8;border-radius:6px;padding:4px 8px}.chooser,.filters,.tabs,.run-head{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.run-head{justify-content:space-between;margin:20px 0 12px}.chooser label,.filters label{display:flex;align-items:center;gap:6px}select,input,button{font:inherit;border:1px solid #cbd5e1;border-radius:6px;padding:6px 9px;background:#fff;color:#17324d}button{cursor:pointer}.tabs{margin:10px 0}.tabs .active{background:#17608f;color:white;border-color:#17608f}.filters{margin-bottom:10px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metrics>div{display:grid;gap:4px;background:#f6f9fc;padding:12px;border-radius:8px}.metrics strong{font-size:18px}.notice{border-left:3px solid #d99320;background:#fff8e9;padding:10px}.empty{color:#64748b;padding:20px 0}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;vertical-align:top;padding:9px;border-bottom:1px solid #e5ebf0;max-width:360px;overflow-wrap:anywhere}th{background:#f6f9fc}.more{margin-top:12px}.curve{height:180px;background:#f7fafc;margin:12px 0}.curve svg{width:100%;height:100%}.curve polyline{fill:none;stroke:#17608f;stroke-width:1.5;vector-effect:non-scaling-stroke}details{margin-top:12px}summary{cursor:pointer;color:#17608f}pre{max-height:300px;overflow:auto;background:#f7fafc;padding:12px;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:140px 1fr;gap:6px 10px;font-size:13px}dd{margin:0;overflow-wrap:anywhere}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
