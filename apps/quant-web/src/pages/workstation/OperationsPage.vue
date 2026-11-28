<script setup lang="ts">
import { computed, ref } from 'vue'
import { readWorkstationHealth } from '@/api/runtime'
import { componentRows, healthLabel, needsAttention } from '@/utils/workstationHealth'
import { useWorkstationRead } from '@/composables/useWorkstationRead'
import { useWorkstationAccounts } from '@/composables/useWorkstationAccounts'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { monitorMoney, observerLabel } from '@/utils/simulationPresentation'
import { activityChartLink } from '@/utils/workstationRoutes'

const { tq, subing, recentTqRecords, tqAccount, subingAccount, rows } = useWorkstationAccounts()
const tqOverview = tq.value
const tqRead = tq.status
const tqRecordsRead = recentTqRecords.status
const model = subing.value
const modelRead = subing.status
const modelState: Record<string, string> = {
  RUNNING: '运行中', SESSION_BREAK: '时段间休市', SESSION_COMPLETE: '本交易日已处理完毕',
  SESSION_CLOSED: '休市等待', STALE_OR_STOPPED: '运行核验已过期或已停止',
  INTERRUPTED: '观察中断', BLOCKED: '启动或运行受阻', NOT_STARTED: '尚未启动',
  WAITING_OBSERVATIONS: '等待完整行情原件', WAITING_EXECUTION_FACTS: '等待当日执行事实',
  WAITING_MARKET_METADATA: '等待交易日历或主力合约', WARMING_UP: '正在准备模型',
}
const modelValuationAt = computed(() => {
  const times = model.value?.products.flatMap(item => item.accounts.map(account => account.valuation_at)) ?? []
  return times.filter((at): at is string => !!at && Number.isFinite(Date.parse(at)))
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null
})
const sources = [{ id: 'all', label: '全部来源' }, { id: 'htdy', label: '快期' }, { id: 'subing', label: '苏冰' }] as const
const source = ref<(typeof sources)[number]['id']>('all')
const visibleRows = computed(() => rows.value.filter(row => source.value === 'all' || row.source === source.value))
const tqCurrent = computed(() => tqRead.value === 'ready' && tqAccount.value.verified)
const subingCurrent = computed(() => modelRead.value === 'ready' && subingAccount.value.verified)
const { value: health, state: healthState, refresh: refreshHealth } = useWorkstationRead(readWorkstationHealth)
const exceptions = computed(() => {
  const list: Array<{ title: string; detail: string; to: string }> = componentRows(health.value).filter(row => needsAttention(row.status))
    .map(row => ({ title: row.title, detail: [healthLabel(row.status), row.diagnostic].filter(Boolean).join(' · '), to: '/system#runtime' }))
  if (healthState.value === 'error') list.push({ title: '运行健康', detail: '读取失败', to: '/system#runtime' })
  if (tqRead.value !== 'loading' && !tqCurrent.value) list.push({ title: '快期模拟账户', detail: tqRead.value === 'error' ? '账户读取失败' : '最近快照待核验', to: '/market?tab=simulation' })
  if (modelRead.value !== 'loading' && !subingCurrent.value) list.push({ title: '苏冰共享 Paper', detail: modelRead.value === 'error' ? '模型读取失败' : modelState[model.value?.status ?? ''] ?? '尚无可核验运行', to: '/research/subing-decision' })
  return list
})
const checking = computed(() => [healthState.value, tqRead.value, modelRead.value].includes('loading'))
</script>

<template>
  <div class="operations">
    <main>
      <header class="ws-heading"><h1>运行总览</h1><div class="ws-actions"><RouterLink to="/">返回看盘</RouterLink><RouterLink to="/system">查看数据与系统</RouterLink></div></header>
      <div class="ws-metrics" aria-label="运行读回摘要">
        <div><small>运行服务</small><strong>{{ health ? healthLabel(health.status) : healthState === 'error' ? '读取失败' : '正在读取' }}</strong></div>
        <div><small>最近行情 Bar</small><strong>{{ formatBeijingInstant(health?.components.live_market?.last_bar_at) }}</strong></div>
        <div><small>盘后归档成功日</small><strong>{{ health?.components.after_market?.last_successful_trading_day ?? '—' }}</strong></div>
        <div><small>已核验模拟来源</small><strong>{{ Number(tqCurrent) + Number(subingCurrent) }} / 2</strong></div>
      </div>
      <section class="exceptions" aria-labelledby="exceptions-heading">
        <header><h2 id="exceptions-heading">需关注事项</h2><button class="ws-button" type="button" :disabled="healthState === 'loading'" @click="refreshHealth">刷新运行健康</button></header>
        <p v-if="checking" role="status">正在核对运行与账户来源…</p>
        <p v-if="!checking && !exceptions.length">本次运行与账户读回均未报告异常。</p>
        <ul v-if="exceptions.length"><li v-for="item in exceptions" :key="item.title"><RouterLink :to="item.to"><strong>{{ item.title }}</strong><span>{{ item.detail }}</span><span aria-hidden="true">→</span></RouterLink></li></ul>
      </section>
      <section class="accounts" aria-label="账户总览">
        <table>
          <thead><tr><th scope="col">账户来源</th><th scope="col">运行状态</th><th scope="col">核验与估值</th><th scope="col">权益</th><th scope="col">收益</th><th scope="col">详情</th></tr></thead>
          <tbody>
            <tr>
              <th scope="row">快期火天大有</th>
              <td>{{ tqRead === 'error' ? '账户读取失败' : tqRead === 'loading' ? '正在读取' : observerLabel(tqOverview) }}</td>
              <td>{{ tqCurrent ? '已核验' : tqOverview?.readback_at ? '核验过期或未通过' : '暂无核验' }} · {{ formatBeijingInstant(tqOverview?.readback_at) }}</td>
              <td>{{ monitorMoney(tqOverview?.metrics.equity) }}</td>
              <td>{{ monitorMoney(tqOverview?.metrics.net_profit) }}<small>区间净收益</small></td>
              <td><RouterLink to="/market?tab=simulation">快期详情</RouterLink></td>
            </tr>
            <tr>
              <th scope="row">苏冰独立量化</th>
              <td>{{ modelRead === 'error' ? '模型读取失败' : modelRead === 'loading' ? '正在读取' : modelState[model?.status ?? ''] ?? model?.status }}
                <small v-if="modelRead === 'ready' && !model?.run_id">尚无 run</small></td>
              <td>模型观察 {{ formatBeijingInstant(model?.observed_at ?? model?.worker_at) }}
                <small>最近合约估值 {{ formatBeijingInstant(modelValuationAt) }}</small></td>
              <td>{{ monitorMoney(model?.account.equity) }}<small>组合权益</small></td>
              <td>{{ monitorMoney(model?.day_net) }}<small>日内净损益 {{ model?.trading_day }}</small></td>
              <td><RouterLink to="/research/subing-decision">持续模型</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="activity" aria-labelledby="activity-heading">
        <header>
          <h2 id="activity-heading">持仓与待处理</h2>
          <div class="source-filter" role="group" aria-label="账户来源筛选">
            <button v-for="item in sources" :key="item.id" type="button" :aria-pressed="source === item.id" @click="source = item.id">{{ item.label }}</button>
          </div>
        </header>
        <p v-if="source !== 'subing'" class="source-notes">快期 · {{ tqCurrent ? (tqOverview?.positions.length ? '持仓已核验' : '空仓') : '当前持仓待核验' }} · {{ tqRecordsRead === 'error' ? '执行记录读取失败' : '最近执行记录，全部活动委托未核验' }}</p>
        <p v-if="source !== 'htdy'" class="source-notes">苏冰 · {{ subingCurrent
          ? (subingAccount.rows.some(row => row.positions.length) ? '持仓已读取' : '空仓') + ' · ' + (subingAccount.rows.some(row => row.actions.length) ? '有待处理动作' : '无模型待处理动作')
          : modelRead === 'ready' && !model?.run_id ? '尚无 run' : '当前持仓与待处理动作待核验' }}</p>
        <table v-if="visibleRows.length">
          <thead><tr><th scope="col">账户来源</th><th scope="col">物理合约</th><th scope="col">持仓</th><th scope="col">待处理动作</th><th scope="col">更新时间</th><th scope="col">行情</th></tr></thead>
          <tbody>
            <tr v-for="row in visibleRows" :key="`${row.source}:${row.contract}`">
              <td>{{ row.account }}<small v-if="row.source === 'htdy' ? !tqCurrent : !subingCurrent">最近快照 · 待核验</small></td>
              <th scope="row">{{ row.contract }}</th>
              <td>{{ row.positions.join(' / ') || ((row.source === 'htdy' ? tqCurrent : subingCurrent) ? '空仓' : '—') }}</td>
              <td><div v-for="(action, index) in row.actions" :key="index">{{ action.label }}<small v-if="action.at">{{ formatBeijingInstant(action.at) }}</small></div><span v-if="!row.actions.length">—</span></td>
              <td>{{ formatBeijingInstant(row.updatedAt) }}</td>
              <td><RouterLink :to="activityChartLink(row)" :aria-label="`看图 ${row.contract} ${row.account}`">看图</RouterLink></td>
            </tr>
          </tbody>
        </table>
        <details v-if="source !== 'htdy' && subingCurrent && subingAccount.idleRows.length" class="idle-positions">
          <summary>苏冰已核验空仓且无待处理动作（{{ subingAccount.idleRows.length }}）</summary>
          <ul>
            <li v-for="row in subingAccount.idleRows" :key="row.contract">
              <strong>{{ row.contract }}</strong> · {{ formatBeijingInstant(row.updatedAt) }}
              <RouterLink :to="activityChartLink(row)" :aria-label="`看图 ${row.contract} ${row.account}`">看图</RouterLink>
            </li>
          </ul>
        </details>
      </section>
    </main>
  </div>
</template>

<style scoped>
.operations { min-height: 100%; background: var(--gy-bg-app); }
main { max-width: 1600px; margin: auto; padding: 24px 32px; }
h1 { margin: 0 0 16px; font-size: 24px; }
h2 { margin: 0; font-size: 16px; }
.exceptions { margin: 12px 0; }
.exceptions ul { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 6px; margin: 10px 0 0; list-style: none; }
.exceptions li a { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-left: 2px solid #b8894f; background: var(--gy-bg-app); }
.exceptions li span { color: var(--gy-status-warning); font-size: 12px; overflow-wrap: anywhere; }
.exceptions li span:last-child { margin-left: auto; }
.accounts, .activity { overflow-x: auto; }
.accounts table { margin-top: 0; }
section { padding: 16px; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); }
section header { display: flex; justify-content: space-between; align-items: center; }
section p { margin: 8px 0; }
.source-notes, small { color: var(--gy-text-secondary); font-size: 12px; }
.source-filter { display: flex; gap: 6px; }
.source-filter button { padding: 5px 10px; border: 1px solid var(--gy-border); border-radius: 5px; background: var(--gy-bg-panel); color: inherit; font: inherit; cursor: pointer; }
.source-filter button[aria-pressed=true] { background: var(--gy-detail-accent-soft); border-color: var(--gy-detail-accent); }
.activity { margin-top: 16px; }
.idle-positions { margin-top: 12px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--gy-border-subtle); }
thead { color: var(--gy-text-secondary); }
small { display: block; }
a { color: var(--gy-link, #2f5fd2); }
</style>
