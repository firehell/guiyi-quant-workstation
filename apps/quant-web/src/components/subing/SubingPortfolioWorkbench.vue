<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SubingReplayChart from './SubingReplayChart.vue'
import { label } from './labels'

const props = defineProps<{ mode: 'status' | 'history' }>()
const names: Record<string, string> = {
  jm: '焦煤', lc: '碳酸锂', rb: '螺纹钢', sa: '纯碱', fg: '玻璃', ma: '甲醇',
  ec: '集运欧线', v: 'PVC', pr: '瓶片', ta: 'PTA', ur: '尿素', sh: '烧碱',
  sc: '原油', cj: '红枣', oi: '菜油', i: '铁矿石',
}
const states: Record<string, string> = {
  NOT_STARTED: '组合尚未启动', NOT_REGISTERED: '暂无已登记组合回放',
  STALE_OR_STOPPED: '已停止或状态过期', INTERRUPTED: '观察中断',
  RUNNING: '运行中', SESSION_COMPLETE: '本交易日已处理完毕', SESSION_CLOSED: '休市等待',
  WARMING_UP: '正在准备模型', WAITING_MARKET_METADATA: '等待交易日历或主力合约',
  WAITING_OBSERVATIONS: '等待完整行情原件', WAITING_EXECUTION_FACTS: '等待当日执行事实',
  BLOCKED: '启动或运行受阻',
  HISTORICAL_RESULT: '历史回放 · 窗口结果', OPEN: '持仓', PENDING: '待执行', COMPLETED: '空仓',
}
type Row = Record<string, any>
const snapshot = ref<Row | null>(null)
const selected = ref('jm')
const loading = ref(false)
const error = ref(false)
const tab = ref('decisions')
const rows = computed(() => Object.entries(names).map(([code, name]) => ({
  code, name, ...snapshot.value?.products?.find((row: Row) => row.product === code),
})))
const current = computed(() => rows.value.find(row => row.code === selected.value)!)
const accounts = computed<Row[]>(() => current.value.accounts ?? [])
const account = computed(() => accounts.value[0])
const combined = computed(() => snapshot.value?.account)
const dayNet = computed(() => snapshot.value?.day_net)
const pending = computed(() => snapshot.value?.products?.flatMap((row: Row) => row.accounts)
  .filter((row: Row) => row.pending).length)
const holds = computed(() => snapshot.value?.products?.flatMap((row: Row) => row.accounts)
  .filter((row: Row) => row.summary?.open_quantity > 0).length)
const decision = computed(() => account.value?.latest_decision ?? account.value?.decisions_with_actions?.at(-1))
const records = computed(() => {
  if (tab.value === 'ledger') {
    return Object.entries(combined.value?.daily ?? {}).reverse()
      .map(([day, row]) => ({ at: day, action: '组合账目', detail: `权益 ${money((row as Row).equity)}` }))
  }
  return accounts.value.flatMap(row => {
    if (tab.value === 'fills') return (row.fills ?? []).map((f: Row) => ({
      at: f.fill_at, action: label(f.action), detail: `${row.contract} · ${money(f.price)} · 费用 ${money(f.fee)}`,
    }))
    if (tab.value === 'positions') return [
      ...(row.open_layers ?? []).map((l: Row) => ({
        at: l.at, action: label(l.side), detail: `${row.contract} · 1手 · 成本 ${money(l.price)}`,
      })),
      ...(row.pending ? [{ at: row.pending.at, action: label(row.pending.kind), detail: row.contract }] : []),
      ...(combined.value?.pending_exit_contracts?.includes(row.contract)
        ? [{ at: row.valuation_at, action: '待退出', detail: row.contract }] : []),
    ]
    return (row.decisions_with_actions ?? []).map((d: Row) => ({
      at: d.at, action: label(d.demand), detail: `${row.contract} · ${label(d.reason)}`,
    }))
  }).sort((a, b) => String(b.at).localeCompare(String(a.at)))
})
const money = (value: unknown) => value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
const stamp = (value?: string) => value ? value.length === 10 ? value :
  new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'
const chart = computed(() => snapshot.value?.charts?.[selected.value] ?? [])
function rowStatus(row: Row) {
  const position = row.accounts?.find((entry: Row) => entry.summary?.open_quantity > 0)
  if (position) {
    const side = position.open_layers?.[0]?.side
    return side === 'LONG' ? '多头持仓' : side === 'SHORT' ? '空头持仓' : '持仓'
  }
  return states[row.accounts?.[0]?.status] ?? states[snapshot.value?.status] ?? (row.enabled ? '待观察' : '待登记')
}
const tabs = [['decisions', '决策历史'], ['fills', '模型成交'], ['positions', '持仓与义务'], ['ledger', '组合账目']]

let refresh: (index?: number) => void
const playing = ref(false)
watch(() => props.mode, (mode, _, onCleanup) => {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  snapshot.value = null
  async function load(index?: number) {
    if (loading.value || controller.signal.aborted) return
    clearTimeout(timer)
    loading.value = true
    try {
      const response = await fetch(`/api/v1/subing-portfolio/${mode}${index == null ? '' : `?index=${index}`}`, { signal: controller.signal })
      if (!response.ok) throw new Error('portfolio request failed')
      const result = await response.json()
      if (!controller.signal.aborted) {
        snapshot.value = result
        error.value = false
      }
    } catch {
      if (!controller.signal.aborted) error.value = true
    } finally {
      if (!controller.signal.aborted) {
        loading.value = false
        if (mode === 'status') timer = setTimeout(load, 10000)
        else {
          const current = snapshot.value
          if (playing.value && !error.value && current && current.index + 1 < current.length) {
            timer = setTimeout(() => { if (playing.value) void load(current.index + 1) }, 350)
          } else playing.value = false
        }
      }
    }
  }
  refresh = (index?: number) => void load(index)
  onCleanup(() => { controller.abort(); clearTimeout(timer); loading.value = false; playing.value = false })
  error.value = false
  refresh()
}, { immediate: true })
</script>

<template>
  <div class="portfolio">
    <header class="heading">
      <h1>苏冰决策 <small>16品种共享模型账户</small></h1>
      <button type="button" :disabled="loading" @click="refresh(snapshot?.index)">刷新</button>
    </header>
    <p class="model-context">{{ mode === 'status' ? '持续观察' : '历史回放' }} · 同一16品种共享资金与风险模型 · 自动下单关闭</p>
    <p v-if="snapshot?.run_id" class="model-context">{{ mode === 'status' ? '持续运行' : '历史结果' }}身份：{{ snapshot.run_id }}</p>
    <p v-if="error" class="notice" role="alert">读取失败。{{ snapshot ? '正在显示最后一次读取的快照。' : '暂无可用快照。' }}</p>
    <section class="panel overview" aria-label="共享账户摘要">
      <div>组合权益<strong>{{ money(combined?.equity) }}</strong></div>
      <div>日内净损益<strong>{{ money(dayNet) }}</strong></div>
      <div>保证金 / 日亏预算<strong>{{ money(combined?.margin) }} / {{ money(combined?.policy?.daily_loss_budget) }}</strong></div>
      <div>持仓品种 / 未决动作<strong>{{ combined?.policy ? holds : '—' }} / {{ combined?.policy ? pending : '—' }}</strong></div>
      <div>{{ states[snapshot?.status] ?? (loading ? '读取中' : '运行状态') }}<strong>{{ stamp(snapshot?.observed_at ?? snapshot?.worker_at) }}</strong></div>
    </section>
    <p v-if="snapshot?.worker_code" class="notice" role="status">{{ snapshot.worker_code }}</p>
    <p v-if="snapshot?.next_open" class="model-context">最早检查执行事实时间 {{ stamp(snapshot.next_open) }}</p>
    <p v-if="combined?.valuation_unproven?.length" class="notice">待核对估值：{{ combined.valuation_unproven.join('、') }}</p>
    <p v-if="snapshot?.window">历史窗口 {{ snapshot.window.join(' — ') }} · {{ snapshot.length ? '当前回放时刻快照' : '组合窗口结果' }}；历史结果与持续账户独立记账。</p>
    <div v-if="mode === 'history' && snapshot?.length" class="panel playback">
      <button type="button" :disabled="loading || snapshot.index === 0" @click="playing = false; refresh(snapshot.index - 1)">上一步</button>
      <button type="button" :disabled="!playing && (loading || snapshot.index + 1 === snapshot.length)" @click="playing = !playing; if (playing) refresh(snapshot.index + 1)">{{ playing ? '暂停' : '播放' }}</button>
      <button type="button" :disabled="loading || snapshot.index + 1 === snapshot.length" @click="playing = false; refresh(snapshot.index + 1)">下一步</button>
      <input type="range" aria-label="回放时刻" min="0" :max="snapshot.length - 1" :value="snapshot.index" :disabled="loading" @change="playing = false; refresh(Number(($event.target as HTMLInputElement).value))">
      <span>{{ stamp(snapshot.observed_at) }}</span>
    </div>
    <div class="workspace">
      <aside class="panel products" aria-label="品种列表">
        <h2>品种 <small>16 个</small></h2>
        <button v-for="row in rows" :key="row.code" type="button" :aria-pressed="row.code === selected" @click="selected = row.code">
          <b>{{ row.name }}</b><small>{{ row.code.toUpperCase() }}</small>
          <span>{{ rowStatus(row) }}</span>
        </button>
      </aside>
      <div class="detail">
        <section class="panel">
          <header class="decision">
            <h2>当前决策 <small>{{ current.name }} {{ account?.contract ?? selected.toUpperCase() }}</small></h2>
            <span>主需求 <b>{{ decision?.demand ? label(decision.demand) : '—' }}</b></span>
            <span>下一等待条件 <b>{{ decision?.next_wait ? label(decision.next_wait) : '—' }}</b></span>
            <span>持仓 <b>{{ account?.summary?.open_quantity ?? '—' }}</b> · 未决 <b>{{ account?.pending ? label(account.pending.kind) : '—' }}</b></span>
          </header>
          <details>
            <summary>展开完整依据</summary>
            <p>{{ decision?.reason ? label(decision.reason) : '暂无对应决策依据。' }}</p>
            <p v-if="decision?.supporting_reasons?.length">支持 {{ decision.supporting_reasons.map(label).join('、') }}</p>
            <p v-if="decision?.blocking_reasons?.length">阻止 {{ decision.blocking_reasons.map(label).join('、') }}</p>
            <p v-if="decision?.condition_gaps?.length">条件缺口 {{ decision.condition_gaps.map(label).join('、') }}</p>
            <p v-if="decision?.at">决策时间 {{ stamp(decision.at) }}</p>
            <p v-for="item in (snapshot?.coverage ?? []).filter((row: Row) => row.product === selected)" :key="item.contract">{{ item.contract }} · {{ item.status }}</p>
          </details>
        </section>
        <section class="panel chart" aria-label="行情与结构">
          <h2>行情与结构 <small>30分钟 · 已完成 Bar</small></h2>
          <SubingReplayChart v-if="chart.length" :key="selected" :rows="chart" :stop="account?.decision_state?.initial_stop ?? null" :target="account?.decision_state?.profit_target ?? null" />
          <div v-else class="chart-empty">{{ snapshot?.status === 'NOT_STARTED' ? '组合尚未启动，暂无行情快照' : '暂无已登记图表' }}</div>
        </section>
        <section class="panel records">
          <nav aria-label="组合记录">
            <button v-for="[id, title] in tabs" :key="id" type="button" :aria-pressed="tab === id" @click="tab = id">{{ title }}</button>
          </nav>
          <table v-if="records.length">
            <thead><tr><th>时间</th><th>动作</th><th>说明</th></tr></thead>
            <tbody><tr v-for="(record, index) in records.slice(0, 100)" :key="index"><td>{{ stamp(record.at) }}</td><td>{{ record.action }}</td><td>{{ record.detail }}</td></tr></tbody>
          </table>
          <p v-else>暂无记录。</p>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.portfolio { padding-top: 12px; }
.heading, .decision, .playback, nav { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.heading h1 { margin: 0 auto 0 0; font-size: 24px; }
.panel { padding: 14px; margin: 12px 0; border: 1px solid #ebedf0; border-radius: 8px; background: white; }
.overview { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.overview strong { display: block; margin-top: 6px; font-size: 16px; }
.workspace { display: grid; grid-template-columns: minmax(175px, 218px) minmax(0, 1fr); gap: 12px; align-items: start; }
.products { display: grid; gap: 4px; }
button { border: 1px solid #ebedf0; border-radius: 6px; background: white; padding: 6px 10px; color: inherit; cursor: pointer; }
button[aria-pressed=true] { border-color: #ff6b2c; background: #fff4ee; color: #a64113; }
.products button { display: grid; grid-template-columns: 1fr 28px 50px; gap: 4px; text-align: left; align-items: center; }
.model-context { color: #667085; font-size: 12px; overflow-wrap: anywhere; }
small, details, .chart-empty { color: #667085; font-size: 12px; }
h2 { margin: 0 0 8px; font-size: 16px; }
.decision h2 { margin: 0; }
details { margin-top: 8px; }
summary { cursor: pointer; }
.chart-empty { min-height: clamp(280px, 36vh, 520px); display: grid; place-items: center; background: repeating-linear-gradient(#fff 0 37px, #eef0f3 38px 39px); }
.notice { padding: 8px; color: #93451c; background: #fff4ee; }
.records { overflow: auto; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; text-align: left; }
td, th { padding: 8px; border-bottom: 1px solid #ebedf0; }
@media (max-width: 780px) {
  .workspace { grid-template-columns: minmax(0, 1fr); }
  .overview { grid-template-columns: repeat(2, 1fr); }
  .products { grid-template-columns: repeat(auto-fit, minmax(144px, 1fr)); }
  .products h2 { grid-column: 1 / -1; }
}
</style>
