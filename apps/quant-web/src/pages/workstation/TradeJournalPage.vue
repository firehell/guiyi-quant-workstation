<script setup lang="ts">
import { computed, onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  readCase, readEvidence, readJournal, writeJournal,
  type AssessmentKey, type Detail, type Direction, type EvidenceList, type FilterSource,
  type Period, type Plan, type PlanFields, type Rating, type Source, type SummaryFields,
  type TimelineRow, type Workspace,
} from '@/api/tradeJournal'
import LinkedObservationNotes from './LinkedObservationNotes.vue'
import JournalObservations from './JournalObservations.vue'
import { formatBeijingInstant } from '@/utils/marketDisplay'

const sources: Record<FilterSource, string> = {
  MANUAL: '人工记录', SIMNOW: 'SimNow 原生仿真', SUBING_PAPER: '苏冰共享 Paper',
  TQKQ_HISTORY: '快期 TQKQ 历史', NEWOW_REFERENCE: '牛哇参考交易', RQALPHA_BACKTEST: 'RQAlpha Plus 回测',
}
const evidenceSources = (Object.keys(sources) as FilterSource[]).filter((key): key is Source => key !== 'MANUAL')
const sourceStatuses: Record<string, string> = {
  AVAILABLE: '证据可读', NOT_CONFIGURED: '来源未配置', VERIFIED_EMPTY: '已核验无记录',
  NO_EVIDENCE: '该交易日缺少可核验证据', UNAVAILABLE: '来源读取失败',
  SCOPE_REQUIRED: '请选择来源身份后查询', CONTRACT_REQUIRED: '需要物理合约',
}
const actions: Record<string, string> = {
  OPEN: '开仓', ADD: '加仓', REDUCE: '减仓', STOP: '止损', TAKE_PROFIT: '止盈', CLOSE: '平仓', NOTE: '备注',
  CLOSETODAY: '平今', CLOSEYESTERDAY: '平昨', CLOSED: '已结束', ROLLOVER_INTERRUPTED: '换月中断',
  DATA_CONFLICT: '数据冲突', BUY: '买入', SELL: '卖出', ENTER: '开仓', EXIT: '退出',
}
const dimensions: [AssessmentKey, string][] = [
  ['market', '行情判断'], ['entry', '入场质量'], ['management', '持仓管理'], ['exit', '止盈止损'], ['execution', '执行与心理'],
]
const ratings: Record<Rating, string> = {
  UNASSESSED: '未评估', MET: '符合计划', PARTLY_MET: '部分符合', MISSED: '偏离计划', NOT_APPLICABLE: '不适用',
}
const planFields = [
  ['market', '行情判断'], ['entry', '入场条件'], ['stop', '失效与止损'],
  ['target', '目标'], ['sizing', '仓位与加减仓'], ['scenarios', '情景预案'],
] as const
const summaryFields = [
  ['environment', '市场环境'], ['observations', '观察与做得好的事'], ['missed', '错过的机会'],
  ['execution', '执行偏差与反复问题'], ['next_action', '下一步行动'],
] as const
const frequencies = ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
const route = useRoute()
const router = useRouter()
const today = new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10)
const caseId = computed(() => typeof route.params.caseId === 'string' ? route.params.caseId : undefined)
const dayQuery = typeof route.query.day === 'string' ? route.query.day : ''
const selectedDay = ref(/^\d{4}-\d{2}-\d{2}$/.test(dayQuery) && Number.isFinite(Date.parse(dayQuery)) ? dayQuery : today)
const period = ref<Period>('day')
const anchor = computed(() => {
  if (!selectedDay.value || period.value === 'day') return selectedDay.value
  const day = new Date(selectedDay.value + 'T00:00:00Z')
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7)
  return day.toISOString().slice(0, 10)
})
const version = ref('')
const product = ref('')
const tag = ref('')
const filterSource = ref<FilterSource | ''>('')
const workspace = shallowRef<Workspace>()
const detail = shallowRef<Detail>()
const offset = ref(0)
const loading = ref(false)
const detailLoading = ref(false)
const saving = ref(false)
const overviewError = ref('')
const detailError = ref('')
const formError = ref('')
const notification = ref('')
let listRequest: AbortController | undefined
let caseRequest: AbortController | undefined
let sourceRequest: AbortController | undefined

const planEditor = ref<{ id: string; version: number; day: string; product: string; content: PlanFields }>()
const sourceChart = ref('')
const caseEditor = ref<{ id: string; day: string; title: string; contract: string; direction: Direction; plan: string }>()
const summary = reactive<SummaryFields>({ environment: '', observations: '', missed: '', execution: '', next_action: '', case_ids: [] })
const summaryVersion = ref(0)
const caseForm = reactive({ title: '', closed: false, takeaway: '', next_action: '' })
const assessments = reactive(Object.fromEntries(dimensions.map(([key]) => [key, {
  rating: 'UNASSESSED' as Rating, tags: '', note: '',
}])) as Record<AssessmentKey, { rating: Rating; tags: string; note: string }>)
const manual = reactive({ kind: 'NOTE', day: today, at: '', note: '', price: '', quantity: '' })
const manualId = ref('')
const removal = ref<{ row: TimelineRow; reason: string }>()
const history = ref(false)
const evidenceSearch = reactive({ source: 'SIMNOW' as Source, scope: '', day: today, nativeId: '', manualId: '' })
const evidence = shallowRef<EvidenceList>()
const sourceQueryIdentity = ref('')
const evidenceError = ref('')
const evidenceLoading = ref(false)
const selectedEvidence = ref<string[]>([])
const operationKeys = new Map<string, string>()
const evidenceEvents = new Map<string, string>()

const timeline = computed(() => detail.value?.timeline.filter(row => row.kind !== 'COMPARISON' && (history.value || !row.removed_at)) ?? [])
const comparisons = computed(() => detail.value?.timeline.filter(row => row.kind === 'COMPARISON' && (history.value || !row.removed_at)) ?? [])
const manualCandidates = computed(() => timeline.value.filter(row => row.manual && row.kind !== 'NOTE' &&
  !row.removed_at && row.trading_day === evidenceSearch.day && !timeline.value.some(link => !link.removed_at && link.replaces_manual === row.id)))
const isExecutionSource = computed(() => !['NEWOW_REFERENCE', 'RQALPHA_BACKTEST'].includes(evidenceSearch.source))
const casePlans = computed(() => workspace.value?.plans.filter(plan => plan.trading_day === caseEditor.value?.day) ?? [])
const caseNames = reactive<Record<string, string>>({})

function message(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: { code?: string; msg?: string } | { msg?: string }[] } } })
    ?.response?.data?.detail
  const code = Array.isArray(detail) ? detail[0]?.msg : detail?.code
  const messages: Record<string, string> = {
    JOURNAL_CASE_VERSION_CONFLICT: '案例已在其他窗口更新，请重新打开后再保存。',
    JOURNAL_PLAN_VERSION_CONFLICT: '计划已在其他窗口更新，请重新打开后再保存。',
    JOURNAL_SUMMARY_VERSION_CONFLICT: '复盘已在其他窗口更新，请刷新后再保存。',
    JOURNAL_FILL_SCOPE_CONFLICT: '成交的合约、方向或交易日与案例不一致。',
    JOURNAL_FILL_ACCOUNT_CONFLICT: '一个案例只能关联同一来源和账户的执行成交。',
    JOURNAL_EVIDENCE_ALREADY_LINKED: '这条证据已有有效关联。',
    JOURNAL_SOURCE_UNAVAILABLE: '来源暂时不可读，稍后可重试。',
    JOURNAL_EVIDENCE_NOT_FOUND: '找不到这条来源证据。',
    JOURNAL_STORAGE_UNAVAILABLE: '交易复盘存储暂时不可用，请检查应用迁移和数据库连接。',
    JOURNAL_PLAN_SCOPE_CONFLICT: '计划日期或品种与案例不一致。',
    JOURNAL_SUMMARY_CASE_OUTSIDE_PERIOD: '引用案例须在当前复盘周期内。',
    JOURNAL_EVENT_BEFORE_CASE: '事件交易日早于案例起始交易日。',
    JOURNAL_MANUAL_LINK_CONFLICT: '人工操作与成交的交易日或开平类别不一致。',
    JOURNAL_MANUAL_HAS_EVIDENCE: '请先撤销这条人工记录对应的来源关联。',
  }
  return code ? (messages[code] ?? code) : '保存或读取失败，请重试。'
}

function resetSummary(value?: Workspace['summary']) {
  summaryVersion.value = value?.version ?? 0
  Object.assign(summary, value?.content ?? { environment: '', observations: '', missed: '', execution: '', next_action: '', case_ids: [] })
}

async function loadWorkspace(preserve = false) {
  listRequest?.abort()
  if (!anchor.value) return
  const controller = new AbortController()
  listRequest = controller
  loading.value = true
  overviewError.value = ''
  try {
    const response = await readJournal({
      anchor: anchor.value, period: period.value, product: product.value.trim().toUpperCase() || undefined,
      tag: tag.value.trim() || undefined, source: filterSource.value || undefined, offset: offset.value,
    }, controller.signal)
    if (controller.signal.aborted) return
    workspace.value = response
    version.value = response.component_version
    for (const row of response.cases) caseNames[row.id] = row.title
    if (!preserve) resetSummary(response.summary)
  } catch (error) {
    if (!controller.signal.aborted) overviewError.value = message(error)
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

function resetCaseForm(value: Detail) {
  caseForm.title = value.case.title
  caseForm.closed = value.case.closed
  caseForm.takeaway = value.case.review?.takeaway ?? ''
  caseForm.next_action = value.case.review?.next_action ?? ''
  for (const [key] of dimensions) {
    const existing = value.case.review?.dimensions[key]
    assessments[key] = { rating: existing?.rating ?? 'UNASSESSED', tags: existing?.tags.join('、') ?? '', note: existing?.note ?? '' }
  }
}

async function loadDetail(preserve = false) {
  caseRequest?.abort()
  const id = caseId.value
  if (!id) return
  const controller = new AbortController()
  caseRequest = controller
  detailLoading.value = true
  detailError.value = ''
  try {
    const response = await readCase(id, controller.signal)
    if (controller.signal.aborted) return
    if (preserve && detail.value?.case.version !== response.case.version) {
      detailError.value = '案例已在其他窗口更新，请重新打开后再编辑。'
      return
    }
    detail.value = response
    version.value = response.component_version
    if (!preserve) {
      resetCaseForm(response)
      manual.day = evidenceSearch.day = response.case.trading_day
    }
  } catch (error) {
    if (!controller.signal.aborted) detailError.value = message(error)
  } finally {
    if (!controller.signal.aborted) detailLoading.value = false
  }
}

watch([selectedDay, period], () => {
  offset.value = 0
  planEditor.value = caseEditor.value = undefined
  void loadWorkspace()
}, { immediate: true })
watch(caseId, () => {
  detail.value = undefined
  detailError.value = formError.value = notification.value = ''
  history.value = false
  manualId.value = ''
  Object.assign(manual, { kind: 'NOTE', day: today, at: '', note: '', price: '', quantity: '' })
  evidence.value = removal.value = undefined
  evidenceSearch.scope = evidenceSearch.nativeId = evidenceSearch.manualId = ''
  selectedEvidence.value = []
  sourceRequest?.abort()
  sourceQueryIdentity.value = ''
  void loadDetail()
}, { immediate: true })

function toCase(id: string) {
  void router.push({ name: 'trade-journal', params: { caseId: id }, query: { day: selectedDay.value } })
}

function filters() {
  offset.value = 0
  void loadWorkspace(true)
}

function pageBy(delta: number) {
  offset.value = Math.max(0, offset.value + delta)
  void loadWorkspace(true)
}

async function commit(path: string, body: object) {
  const command = JSON.stringify([path, body])
  const key = operationKeys.get(command) ?? crypto.randomUUID()
  operationKeys.set(command, key)
  const result = await writeJournal(path, body, key)
  operationKeys.delete(command)
  return result
}

async function save(work: () => Promise<void>, done: string) {
  if (saving.value) return
  saving.value = true
  formError.value = notification.value = ''
  try {
    await work()
    notification.value = done
  } catch (error) {
    formError.value = message(error)
  } finally {
    saving.value = false
  }
}

function editPlan(plan?: Plan) {
  caseEditor.value = undefined
  planEditor.value = {
    id: plan?.id ?? crypto.randomUUID(), version: plan?.version ?? 0, day: plan?.trading_day ?? selectedDay.value,
    product: plan?.product ?? '', content: plan ? { ...plan.content, frequencies: [...plan.content.frequencies] } : {
      title: '', direction: 'WATCH', frequencies: [], market: '', entry: '', stop: '', target: '', sizing: '', scenarios: '',
    },
  }
}

watch(() => route.fullPath, () => {
  const { compose, product, frequency, day } = route.query
  if (caseId.value || compose !== 'plan' || typeof product !== 'string' || !/^[A-Za-z]{1,3}$/.test(product)
    || typeof frequency !== 'string' || !frequencies.includes(frequency) || typeof day !== 'string'
    || !/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(Date.parse(day))) return
  selectedDay.value = day
  editPlan()
  planEditor.value!.product = product.toUpperCase()
  planEditor.value!.content.frequencies = [frequency]
  const origin = window.history.state?.sourceChart
  if (typeof origin === 'string' && origin.startsWith('/market/chart?')) sourceChart.value = origin
  void router.replace({ name: 'trade-journal', query: { day } })
}, { immediate: true })

function savePlan() {
  const plan = planEditor.value
  if (!plan) return
  void save(async () => {
    await commit('/plans/' + plan.id, {
      expected_version: plan.version, trading_day: plan.day, product: plan.product.trim().toUpperCase() || null, ...plan.content,
    })
    planEditor.value = undefined
    await loadWorkspace(true)
  }, '计划已保存')
}

function createCase(plan?: Plan) {
  planEditor.value = undefined
  caseEditor.value = {
    id: crypto.randomUUID(), day: plan?.trading_day ?? selectedDay.value, title: '', contract: '',
    direction: plan?.content.direction === 'SHORT' ? 'SHORT' : 'LONG', plan: plan ? plan.id + ':' + plan.version : '',
  }
}

function saveCase() {
  const row = caseEditor.value
  if (!row) return
  const [plan, planVersion] = row.plan.split(':')
  const contract = row.contract.trim().toUpperCase()
  void save(async () => {
    await commit('/cases/' + row.id + '/create', {
      trading_day: row.day, title: row.title, contract, product: contract.replace(/[0-9]+$/, ''),
      direction: row.direction, plan_id: plan || null, plan_version: planVersion ? Number(planVersion) : null,
    })
    caseEditor.value = undefined
    await loadWorkspace(true)
    toCase(row.id)
  }, '案例已建立')
}

function saveCaseReview() {
  const row = detail.value?.case
  if (!row) return
  const evaluated = Object.fromEntries(dimensions.map(([key]) => [key, {
    rating: assessments[key].rating,
    tags: [...new Set(assessments[key].tags.split(/[、，,]/).map(value => value.trim()).filter(Boolean))],
    note: assessments[key].note,
  }]))
  void save(async () => {
    await commit('/cases/' + row.id, {
      expected_version: row.version, title: caseForm.title, closed: caseForm.closed, review: {
        dimensions: evaluated, takeaway: caseForm.takeaway, next_action: caseForm.next_action,
      },
    })
    await Promise.all([loadDetail(), loadWorkspace(true)])
  }, '案例复盘已保存')
}

function saveManual() {
  if (!caseId.value) return
  manualId.value ||= crypto.randomUUID()
  const id = caseId.value
  void save(async () => {
    await commit('/cases/' + id + '/events/' + manualId.value, {
      kind: manual.kind, trading_day: manual.day, occurred_at: manual.at + ':00+08:00', note: manual.note,
      price: manual.kind !== 'NOTE' && manual.price ? String(manual.price) : null,
      quantity: manual.kind !== 'NOTE' && manual.quantity ? Number(manual.quantity) : null,
    })
    manualId.value = ''
    manual.note = manual.price = manual.quantity = ''
    await loadDetail(true)
  }, '时间线已更新')
}

const currentSourceQuery = computed(() => JSON.stringify([caseId.value, evidenceSearch.source, evidenceSearch.scope,
  evidenceSearch.day, evidenceSearch.nativeId]))
const visibleEvidence = computed(() => sourceQueryIdentity.value === currentSourceQuery.value ? evidence.value : undefined)
const eligibleEvidence = computed(() => visibleEvidence.value?.items.filter(row => !isExecutionSource.value ||
  detail.value?.case.contract === row.contract && detail.value.case.direction === row.direction) ?? [])

async function searchEvidence() {
  sourceRequest?.abort()
  const controller = new AbortController()
  sourceRequest = controller
  const query = currentSourceQuery.value
  evidenceLoading.value = true
  evidenceError.value = ''
  selectedEvidence.value = []
  try {
    const found = await readEvidence({
      source: evidenceSearch.source, trading_day: evidenceSearch.day, scope: evidenceSearch.scope.trim() || undefined,
      contract: detail.value?.case.contract, native_id: evidenceSearch.nativeId.trim() || undefined,
    }, controller.signal)
    if (controller.signal.aborted || query !== currentSourceQuery.value) return
    evidence.value = found
    if (found.scope && !evidenceSearch.scope) evidenceSearch.scope = found.scope
    sourceQueryIdentity.value = currentSourceQuery.value
  } catch (error) {
    if (!controller.signal.aborted) evidenceError.value = message(error)
  } finally {
    if (!controller.signal.aborted) evidenceLoading.value = false
  }
}

function linkEvidence() {
  const id = caseId.value
  const result = visibleEvidence.value
  if (!id || !result?.scope) return
  const sourcesToAdd = [...selectedEvidence.value]
  const scope = result.scope
  const source = evidenceSearch.source
  const day = evidenceSearch.day
  const manualRef = isExecutionSource.value && sourcesToAdd.length === 1 ? evidenceSearch.manualId || null : null
  void save(async () => {
    try {
      for (const nativeId of sourcesToAdd) {
        const identity = JSON.stringify([id, source, scope, day, nativeId, manualRef])
        const linkId = evidenceEvents.get(identity) ?? crypto.randomUUID()
        evidenceEvents.set(identity, linkId)
        await commit('/cases/' + id + '/links/' + linkId, {
          source, scope, native_id: nativeId, trading_day: day, replaces_manual: manualRef,
        })
        evidenceEvents.delete(identity)
        selectedEvidence.value = selectedEvidence.value.filter(value => value !== nativeId)
      }
      evidenceSearch.manualId = ''
    } finally {
      await Promise.all([loadDetail(true), loadWorkspace(true)])
    }
  }, '来源证据已关联')
}

function removeEvent() {
  const item = removal.value
  const id = caseId.value
  if (!id || !item) return
  void save(async () => {
    await commit('/cases/' + id + '/events/' + item.row.id + '/removal', { reason: item.reason })
    removal.value = undefined
    await Promise.all([loadDetail(true), loadWorkspace(true)])
  }, '已撤销关联或记录')
}

function saveSummary() {
  void save(async () => {
    const body = { ...summary, expected_version: summaryVersion.value }
    const saved = await commit('/summaries/' + period.value + '/' + anchor.value, body)
    summaryVersion.value = saved.version ?? summaryVersion.value
    await loadWorkspace(true)
  }, '周期复盘已保存')
}

function setSummaryCase(id: string, checked: boolean) {
  summary.case_ids = checked ? [...new Set([...summary.case_ids, id])] : summary.case_ids.filter(value => value !== id)
}

function replacement(row: TimelineRow) {
  return timeline.value.find(link => !link.removed_at && link.replaces_manual === row.id)
}

onScopeDispose(() => {
  listRequest?.abort()
  caseRequest?.abort()
  sourceRequest?.abort()
})
</script>

<template>
  <main class="journal">
    <header class="heading">
      <div>
        <RouterLink v-if="caseId" class="back" :to="{ name: 'trade-journal', query: { day: selectedDay } }">← 交易复盘</RouterLink>
        <h1>{{ detail?.case.title ?? '交易日志与复盘中心' }}</h1>
        <RouterLink v-if="sourceChart" class="back" :to="sourceChart">返回原看盘视窗</RouterLink>
        <div v-if="detail" class="case-meta">
          <span>{{ detail.case.contract }}</span><span>{{ detail.case.direction === 'LONG' ? '多头' : '空头' }}</span>
          <RouterLink :to="{ name: 'statistics-research', query: { mode: 'case', case: detail.case.id } }">案例统计与研究</RouterLink>
          <span>{{ detail.case.trading_day }}</span><span>{{ detail.case.closed ? '已结案' : '进行中' }}</span>
        </div>
      </div>
      <small v-if="version" class="version">v{{ version }}</small>
    </header>

    <p v-if="notification" class="notice" role="status">{{ notification }}</p>
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>

    <template v-if="!caseId">
      <section class="toolbar" aria-label="复盘周期">
        <div class="segments">
          <button type="button" :aria-pressed="period === 'day'" @click="period = 'day'">交易日</button>
          <button type="button" :aria-pressed="period === 'week'" @click="period = 'week'">交易周</button>
        </div>
        <label class="inline">选择日期<input v-model="selectedDay" type="date"></label>
        <span v-if="period === 'week' && anchor" class="quiet">周起始 {{ anchor }}</span>
        <div class="toolbar-actions">
          <button type="button" :disabled="!selectedDay || saving" @click="editPlan()">新建计划</button>
          <button type="button" class="primary" :disabled="!selectedDay || saving" @click="createCase()">新建案例</button>
        </div>
      </section>

      <JournalObservations :anchor="anchor" :period="period" />

      <p v-if="overviewError" class="error" role="alert">{{ overviewError }} <button type="button" @click="loadWorkspace()">重试</button></p>
      <p v-if="loading && !workspace" class="quiet" role="status">正在读取交易复盘…</p>

      <form v-if="planEditor" class="panel editor" @submit.prevent="savePlan">
        <h2>{{ planEditor.version ? '修订交易计划' : '新建交易计划' }}</h2>
        <div class="grid compact">
          <label>计划标题<input v-model="planEditor.content.title" required maxlength="160"></label>
          <label>交易日<input v-model="planEditor.day" type="date" required :disabled="!!planEditor.version"></label>
          <label>品种<input v-model="planEditor.product" placeholder="留空为每日总计划" pattern="[a-zA-Z]{1,3}" :disabled="!!planEditor.version"></label>
          <label>方向<select v-model="planEditor.content.direction"><option value="WATCH">观望</option><option value="LONG">看多</option><option value="SHORT">看空</option></select></label>
        </div>
        <fieldset class="checks"><legend>观察周期</legend>
          <label v-for="freq in frequencies" :key="freq"><input v-model="planEditor.content.frequencies" type="checkbox" :value="freq">{{ freq }}</label>
        </fieldset>
        <div class="grid">
          <label v-for="[key, label] in planFields" :key="key">{{ label }}<textarea v-model="planEditor.content[key]" maxlength="8000" rows="2" /></label>
        </div>
        <div class="buttons"><button type="submit" class="primary" :disabled="saving">保存计划</button><button type="button" @click="planEditor = undefined">取消</button></div>
      </form>

      <form v-if="caseEditor" class="panel editor" @submit.prevent="saveCase">
        <h2>新建交易案例</h2>
        <div class="grid compact">
          <label>案例标题<input v-model="caseEditor.title" maxlength="160" required></label>
          <label>交易日<input v-model="caseEditor.day" type="date" required></label>
          <label>物理合约<input v-model="caseEditor.contract" required pattern="[a-zA-Z]{1,3}[0-9]{1,2}(0[1-9]|1[0-2])" placeholder="如 RB2701"></label>
          <label>持仓方向<select v-model="caseEditor.direction"><option value="LONG">多头</option><option value="SHORT">空头</option></select></label>
          <label>关联计划<select v-model="caseEditor.plan"><option value="">计划外交易</option><option v-for="plan in casePlans" :key="plan.id" :value="plan.id + ':' + plan.version">{{ plan.content.title }} · 第 {{ plan.version }} 版</option></select></label>
        </div>
        <div class="buttons"><button type="submit" class="primary" :disabled="saving">建立案例</button><button type="button" @click="caseEditor = undefined">取消</button></div>
      </form>

      <div v-if="workspace" class="overview">
        <section class="panel">
          <h2>交易计划</h2>
          <p v-if="!workspace.plans.length" class="quiet">该周期还没有交易计划。</p>
          <article v-for="plan in workspace.plans" :key="plan.id" class="plan-row">
            <div class="quiet">{{ plan.trading_day }} · {{ plan.product ?? '每日总计划' }} · 第 {{ plan.version }} 版</div>
            <h3>{{ plan.content.title }}</h3>
            <LinkedObservationNotes kind="plan" :target-id="plan.id" :version="plan.version" />
            <p v-if="plan.content.entry">{{ plan.content.entry }}</p>
            <div class="buttons"><button type="button" @click="editPlan(plan)">查看或编辑</button><button type="button" @click="createCase(plan)">从计划建案例</button></div>
          </article>
        </section>
        <section class="panel">
          <h2>交易案例</h2>
          <form class="filter" @submit.prevent="filters">
            <label>品种<input v-model="product" placeholder="全部" pattern="[a-zA-Z]{1,3}"></label>
            <label>来源<select v-model="filterSource"><option value="">全部</option><option v-for="(label, key) in sources" :key="key" :value="key">{{ label }}</option></select></label>
            <label>标签<input v-model="tag" maxlength="40" placeholder="全部"></label>
            <button type="submit">筛选</button>
          </form>
          <p v-if="!workspace.cases.length" class="quiet">没有符合条件的案例。</p>
          <table v-else>
            <thead><tr><th>案例</th><th>合约</th><th>进度</th><th>标签</th></tr></thead>
            <tbody><tr v-for="row in workspace.cases" :key="row.id">
              <td><RouterLink :to="{ name: 'trade-journal', params: { caseId: row.id }, query: { day: selectedDay } }">{{ row.title }}</RouterLink><small>{{ row.trading_day }}</small></td>
              <td>{{ row.contract }} {{ row.direction === 'LONG' ? '多' : '空' }}</td>
              <td>{{ row.reviewed ? '已复盘' : row.closed ? '待复盘' : '进行中' }}</td>
              <td>{{ row.tags.join('、') || '—' }}</td>
            </tr></tbody>
          </table>
          <div v-if="offset || workspace.next_offset !== null" class="buttons">
            <button type="button" :disabled="!offset || loading" @click="pageBy(-50)">上一页</button>
            <button type="button" :disabled="workspace.next_offset === null || loading" @click="pageBy(50)">下一页</button>
          </div>
        </section>
      </div>

      <form v-if="workspace" class="panel editor" @submit.prevent="saveSummary">
        <h2>{{ period === 'day' ? '日复盘' : '周复盘' }}</h2>
        <div class="grid"><label v-for="[key, label] in summaryFields" :key="key">{{ label }}<textarea v-model="summary[key]" maxlength="8000" rows="2" /></label></div>
        <fieldset v-if="workspace.cases.length || summary.case_ids.length" class="checks"><legend>引用案例</legend>
          <label v-for="row in workspace.cases" :key="row.id">
            <input type="checkbox" :checked="summary.case_ids.includes(row.id)" @change="setSummaryCase(row.id, ($event.target as HTMLInputElement).checked)">
            {{ row.title }}
          </label>
          <span v-for="id in summary.case_ids.filter(id => !workspace?.cases.some(row => row.id === id))" :key="id" class="reference">
            <RouterLink :to="{ name: 'trade-journal', params: { caseId: id }, query: { day: selectedDay } }">{{ caseNames[id] ?? '查看已关联案例' }}</RouterLink>
            <button type="button" @click="setSummaryCase(id, false)">取消引用</button>
          </span>
        </fieldset>
        <button type="submit" class="primary" :disabled="saving || loading || !!overviewError">保存{{ period === 'day' ? '日' : '周' }}复盘</button>
      </form>
    </template>

    <template v-else>
      <p v-if="detailError" class="error" role="alert">{{ detailError }} <button type="button" @click="loadDetail()">重新读取</button></p>
      <p v-if="detailLoading && !detail" class="quiet" role="status">正在读取案例…</p>
      <template v-if="detail">
        <LinkedObservationNotes kind="case" :target-id="detail.case.id" />
        <div class="overview">
          <section class="panel">
            <h2>事前计划</h2>
            <template v-if="detail.plan">
              <h3>{{ detail.plan.content.title }}</h3>
              <LinkedObservationNotes kind="plan" :target-id="detail.plan.id" :version="detail.plan.version" />
              <p class="quiet">第 {{ detail.plan.version }} 版 · {{ detail.plan.content.frequencies.join(' / ') || '未填写观察周期' }}</p>
              <dl><template v-for="[key, label] in planFields" :key="key">
                <template v-if="detail.plan.content[key]"><dt>{{ label }}</dt><dd>{{ detail.plan.content[key] }}</dd></template>
              </template></dl>
            </template>
            <p v-else class="quiet">计划外交易。</p>
          </section>

          <section class="panel">
            <div class="section-heading"><h2>执行时间线</h2><label class="inline"><input v-model="history" type="checkbox">显示更正记录</label></div>
            <p v-if="!timeline.length" class="quiet">还没有操作记录。</p>
            <ol v-else class="timeline">
              <li v-for="row in timeline" :key="row.id" :class="{ revoked: row.removed_at }">
                <div class="section-heading">
                  <strong>{{ (row.evidence && (actions[row.evidence.action] ?? row.evidence.action)) || (actions[row.kind] ?? '关联成交') }}</strong>
                  <span class="quiet">{{ row.source ? sources[row.source] : sources.MANUAL }}</span>
                </div>
                <p class="quiet">{{ formatBeijingInstant(row.occurred_at) }} · 交易日 {{ row.trading_day }}<br>录入 {{ formatBeijingInstant(row.recorded_at) }}</p>
                <p v-if="row.manual?.note">{{ row.manual.note }}</p>
                <p v-if="replacement(row)" class="quiet">成交见关联的来源记录。</p>
                <p v-else-if="row.manual && (row.manual.price || row.manual.quantity)">记录价 {{ row.manual.price ?? '未填写' }} · {{ row.manual.quantity ?? '—' }} 手</p>
                <p v-if="row.evidence" class="quiet">{{ row.scope }} · {{ row.native_id }}</p>
                <p v-if="row.evidence">成交价 {{ row.evidence.price ?? '未提供' }} · {{ row.evidence.quantity ?? '—' }} 手 · 手续费 {{ row.evidence.fee ?? '未提供' }}<template v-if="row.evidence.gross_realized != null"> · 毛实现盈亏 {{ row.evidence.gross_realized }}</template></p>
                <p v-else-if="row.evidence_status" class="quiet">{{ sourceStatuses[row.evidence_status] ?? row.evidence_status }} · {{ row.native_id }}</p>
                <p v-if="row.removed_at" class="quiet">已撤销 {{ formatBeijingInstant(row.removed_at) }} · {{ row.removal_reason }}</p>
                <button v-else-if="!replacement(row)" class="quiet-button" type="button" @click="removal = { row, reason: '' }">撤销记录</button>
              </li>
            </ol>
          </section>
        </div>

        <section v-if="comparisons.length" class="panel">
          <h2>研究对照</h2>
          <article v-for="row in comparisons" :key="row.id" class="plan-row" :class="{ revoked: row.removed_at }">
            <strong>{{ row.source ? sources[row.source] : '' }}</strong>
            <p class="quiet">{{ row.scope }} · {{ row.native_id }}</p>
            <p v-if="row.evidence">{{ row.evidence.contract }} · 入场价 {{ row.evidence.price ?? '未提供' }} · 退出价 {{ row.evidence.exit_price ?? '未提供' }}
              <template v-if="row.source === 'NEWOW_REFERENCE'"> · 页面参考收益 {{ row.evidence.reference_return ?? '未提供' }}</template>
              <template v-else> · 回测净盈亏 {{ row.evidence.net_pnl ?? '未提供' }}</template>
            </p>
            <p v-else class="quiet">{{ row.removed_at ? '已撤销 · ' + row.removal_reason : sourceStatuses[row.evidence_status ?? 'NO_EVIDENCE'] }}</p>
            <button v-if="!row.removed_at" type="button" @click="removal = { row, reason: '' }">撤销关联</button>
          </article>
        </section>

        <form v-if="removal" class="panel editor" @submit.prevent="removeEvent">
          <h2>撤销记录或关联</h2>
          <label>更正原因<input v-model="removal.reason" required maxlength="160"></label>
          <div class="buttons"><button type="submit" :disabled="saving">确认撤销</button><button type="button" @click="removal = undefined">取消</button></div>
        </form>

        <div class="overview">
          <form class="panel editor" @submit.prevent="saveManual">
            <h2>添加人工记录</h2>
            <div class="grid compact">
              <label>操作<select v-model="manual.kind"><option v-for="key in ['NOTE', 'OPEN', 'ADD', 'REDUCE', 'STOP', 'TAKE_PROFIT', 'CLOSE']" :key="key" :value="key">{{ actions[key] }}</option></select></label>
              <label>交易日<input v-model="manual.day" type="date" required></label>
              <label>发生时间（北京时间）<input v-model="manual.at" type="datetime-local" required></label>
              <template v-if="manual.kind !== 'NOTE'">
                <label>记录价<input v-model="manual.price" inputmode="decimal" pattern="[0-9]+([.][0-9]{1,8})?"></label>
                <label>手数<input v-model="manual.quantity" type="number" min="1" max="1000000"></label>
              </template>
            </div>
            <label>备注<textarea v-model="manual.note" maxlength="8000" rows="2" :required="manual.kind === 'NOTE'" /></label>
            <button type="submit" class="primary" :disabled="saving">添加到时间线</button>
          </form>

          <section class="panel">
            <h2>关联来源证据</h2>
            <form class="editor" @submit.prevent="searchEvidence">
              <div class="grid compact">
                <label>证据来源<select v-model="evidenceSearch.source" @change="evidenceSearch.scope = evidenceSearch.nativeId = evidenceSearch.manualId = ''">
                  <option v-for="key in evidenceSources" :key="key" :value="key">{{ sources[key] }}</option>
                </select></label>
                <label>证据交易日<input v-model="evidenceSearch.day" type="date" required></label>
                <label v-if="evidenceSearch.source !== 'TQKQ_HISTORY'">
                  {{ evidenceSearch.source === 'SIMNOW' ? '账户' : evidenceSearch.source === 'NEWOW_REFERENCE' ? '参考流 ID' : 'Run ID' }}
                  <input v-model="evidenceSearch.scope" maxlength="256" list="journal-source-scopes"
                    :placeholder="evidenceSearch.source === 'SUBING_PAPER' ? '留空查当前持续 Paper' : '留空查询可选来源'">
                  <datalist id="journal-source-scopes"><option v-for="scope in evidence?.scopes ?? []" :key="scope" :value="scope" :label="evidence?.scope_labels[scope]" /></datalist>
                </label>
                <label>成交或参考交易 ID<input v-model="evidenceSearch.nativeId" maxlength="256" placeholder="可选"></label>
              </div>
              <button type="submit" :disabled="evidenceLoading || saving">查询证据</button>
            </form>
            <p v-if="evidenceError" class="error" role="alert">{{ evidenceError }}</p>
            <p v-if="visibleEvidence && visibleEvidence.status !== 'AVAILABLE'" class="quiet">{{ sourceStatuses[visibleEvidence.status] }}</p>
            <div v-if="visibleEvidence?.scope == null && visibleEvidence?.scopes.length" class="buttons">
              <button v-for="scope in visibleEvidence.scopes.slice(0, 8)" :key="scope" type="button" :title="scope" @click="evidenceSearch.scope = scope; searchEvidence()">{{ visibleEvidence.scope_labels[scope] ?? scope }}</button>
            </div>
            <p v-if="visibleEvidence?.status === 'AVAILABLE' && !eligibleEvidence.length" class="quiet">没有与本案例合约及方向匹配的成交。</p>
            <div v-if="eligibleEvidence.length" class="evidence-list">
              <label v-for="row in eligibleEvidence" :key="row.native_id" class="evidence-choice">
                <input v-model="selectedEvidence" type="checkbox" :value="row.native_id"
                  :disabled="saving || detail.timeline.some(event => !event.removed_at && event.source === evidenceSearch.source && event.scope === visibleEvidence?.scope && event.native_id === row.native_id)">
                <span>{{ row.contract }} · {{ formatBeijingInstant(row.occurred_at) }} · {{ actions[row.action] ?? row.action }} · {{ row.price ?? '未提供' }}<small>{{ row.native_id }}</small></span>
              </label>
              <p v-if="visibleEvidence?.has_more" class="quiet">结果已达上限，可按精确 ID 查询。</p>
              <label v-if="selectedEvidence.length === 1 && isExecutionSource && manualCandidates.length">对应人工操作
                <select v-model="evidenceSearch.manualId">
                  <option value="">独立添加</option><option v-for="row in manualCandidates" :key="row.id" :value="row.id">{{ actions[row.kind] }} · {{ formatBeijingInstant(row.occurred_at) }}</option>
                </select>
              </label>
              <button type="button" class="primary" :disabled="!selectedEvidence.length || saving" @click="linkEvidence">关联选中证据</button>
            </div>
          </section>
        </div>

        <form class="panel editor" @submit.prevent="saveCaseReview">
          <h2>案例复盘</h2>
          <div class="grid compact">
            <label>案例标题<input v-model="caseForm.title" required maxlength="160"></label>
            <label class="inline finish"><input v-model="caseForm.closed" type="checkbox">标记为已结案</label>
          </div>
          <div class="review-grid">
            <fieldset v-for="[key, label] in dimensions" :key="key">
              <legend>{{ label }}</legend>
              <label>自评<select v-model="assessments[key].rating"><option v-for="(text, value) in ratings" :key="value" :value="value">{{ text }}</option></select></label>
              <label>标签<input v-model="assessments[key].tags" maxlength="480" placeholder="多个标签用逗号分隔"></label>
              <label>观察与反思<textarea v-model="assessments[key].note" maxlength="8000" rows="2" /></label>
            </fieldset>
          </div>
          <div class="grid">
            <label>案例结论<textarea v-model="caseForm.takeaway" maxlength="8000" rows="2" /></label>
            <label>下次可执行的改进<textarea v-model="caseForm.next_action" maxlength="8000" rows="2" /></label>
          </div>
          <button type="submit" class="primary" :disabled="saving || detailLoading">保存案例复盘</button>
        </form>
      </template>
    </template>
  </main>
</template>

<style scoped>
.journal { --ink: var(--gy-text-primary); --subtle: var(--gy-text-secondary); --line: var(--gy-border); --accent: var(--gy-link); min-height: 100%; background: var(--gy-bg-app); color: var(--ink); padding: 0 32px 40px; font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif; }
.heading { display: flex; justify-content: space-between; align-items: flex-end; padding: 27px 0 18px; border-bottom: 1px solid var(--line); margin-bottom: 18px; }
h1 { font-size: 30px; letter-spacing: -0.025em; line-height: 1.25; margin: 0; }
h2 { font-size: 17px; margin: 0 0 12px; }
h3 { font-size: 15px; margin: 6px 0; }
p { margin: 7px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.version, .case-meta, .quiet { font-size: 13px; color: var(--subtle); }
.case-meta { display: flex; gap: 14px; margin-top: 8px; }
.back { display: block; padding-bottom: 8px; font-size: 13px; }
a { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
.toolbar, .buttons, .section-heading, .inline, .checks, .reference { display: flex; align-items: center; gap: 9px; }
.toolbar { gap: 16px; margin: 0 0 18px; }
.toolbar-actions { display: flex; gap: 8px; margin-left: auto; }
.section-heading { justify-content: space-between; gap: 14px; }
.section-heading h2 { margin: 0; }
.segments { display: flex; gap: 3px; padding: 3px; border: 1px solid var(--line); border-radius: 7px; background: var(--gy-bg-panel); }
.segments button { border-color: transparent; }
.segments [aria-pressed="true"] { color: var(--accent); background: var(--gy-detail-accent-soft); }
.overview { display: grid; grid-template-columns: minmax(260px, 0.86fr) minmax(440px, 1.4fr); gap: 16px; }
.panel { margin: 0 0 16px; min-width: 0; padding: 19px; border: 1px solid var(--line); border-radius: 9px; background: var(--gy-bg-panel); }
.plan-row { border-top: 1px solid var(--line); padding: 10px 0; }
.plan-row:last-child { padding-bottom: 0; }
.plan-row p { margin-bottom: 9px; }
.filter, .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.filter { grid-template-columns: repeat(3, minmax(0, 1fr)) auto; align-items: end; margin-bottom: 14px; }
.compact { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.editor { display: grid; gap: 13px; }
.editor h2 { margin-bottom: 0; }
.editor > button { justify-self: start; }
label { display: grid; gap: 5px; font-size: 13px; color: var(--subtle); min-width: 0; }
label.inline { display: flex; }
label.finish { align-self: end; margin-bottom: 8px; }
input, textarea, select, button { font: inherit; color: inherit; }
input:not([type="checkbox"]), textarea, select { width: 100%; box-sizing: border-box; min-height: 34px; background: var(--gy-bg-panel); border: 1px solid var(--gy-border-strong); border-radius: 5px; padding: 6px 8px; color: var(--ink); }
textarea { resize: vertical; }
input:focus-visible, textarea:focus-visible, select:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
button { width: fit-content; padding: 6px 11px; min-height: 33px; border: 1px solid var(--gy-border-strong); border-radius: 5px; background: var(--gy-bg-panel); cursor: pointer; color: var(--ink); }
button:hover:not(:disabled) { background: var(--gy-bg-hover); }
button:disabled { cursor: default; opacity: 0.5; }
button.primary { border-color: var(--accent); background: var(--accent); color: var(--gy-bg-app); }
button.primary:hover:not(:disabled) { background: var(--gy-accent); }
.quiet-button { color: var(--subtle); background: transparent; }
.notice, .error { padding: 8px 12px; border-radius: 5px; }
.notice { background: var(--gy-bg-elevated); color: var(--gy-status-ok); }
.error { background: var(--gy-bg-elevated); color: var(--gy-status-error); }
.checks { flex-wrap: wrap; padding: 6px 9px 8px; }
.checks label, .evidence-choice { display: flex; gap: 6px; align-items: center; }
fieldset { margin: 0; min-width: 0; border: 1px solid var(--line); border-radius: 6px; }
legend { padding: 0 4px; font-size: 13px; color: var(--ink); }
table { width: 100%; text-align: left; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 6px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
th { color: var(--subtle); font-weight: 500; }
td small, .evidence-choice small { display: block; color: var(--subtle); overflow-wrap: anywhere; }
dl { margin: 0; }
dt { margin-top: 9px; font-size: 13px; color: var(--subtle); }
dd { margin: 3px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.timeline { list-style: none; padding: 0; margin: 12px 0 0; }
.timeline li { border-left: 2px solid var(--gy-accent); padding: 6px 0 9px 13px; margin: 0 0 8px; }
.revoked { opacity: 0.7; }
.review-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 8px; }
.review-grid fieldset { display: grid; gap: 8px; padding: 9px; }
.evidence-list { display: grid; gap: 8px; margin-top: 12px; }
.evidence-choice { align-items: flex-start; padding: 6px 0; border-bottom: 1px solid var(--line); }
</style>
