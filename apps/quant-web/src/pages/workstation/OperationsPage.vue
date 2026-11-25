<script setup lang="ts">
import { computed } from 'vue'
import MarketNavigation from '@/components/market/MarketNavigation.vue'
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
const tqCurrent = computed(() => tqRead.value === 'ready' && tqAccount.value.verified)
const subingCurrent = computed(() => modelRead.value === 'ready' && subingAccount.value.verified)
</script>

<template>
  <div class="operations">
    <MarketNavigation active-tab="operations" />
    <main>
      <h1>运行台</h1>
      <div class="accounts">
        <section aria-labelledby="tq-heading">
          <header><h2 id="tq-heading">快期火天大有</h2><RouterLink to="/market?tab=simulation">快期详情</RouterLink></header>
          <p>{{ tqRead === 'error' ? '账户读取失败' : tqRead === 'loading' ? '正在读取' : observerLabel(tqOverview) }}</p>
          <dl>
            <div><dt>账户核验</dt><dd>{{ tqCurrent ? '已核验' : tqOverview?.readback_at ? '核验过期或未通过' : '暂无核验' }} · {{ formatBeijingInstant(tqOverview?.readback_at) }}</dd></div>
            <div><dt>账户权益</dt><dd>{{ monitorMoney(tqOverview?.metrics.equity) }}</dd></div>
            <div><dt>区间净收益</dt><dd>{{ monitorMoney(tqOverview?.metrics.net_profit) }}</dd></div>
          </dl>
        </section>
        <section aria-labelledby="subing-heading">
          <header><h2 id="subing-heading">苏冰独立量化</h2><RouterLink to="/research/subing-decision">持续模型</RouterLink></header>
          <p>{{ modelRead === 'error' ? '模型读取失败' : modelRead === 'loading' ? '正在读取' : modelState[model?.status ?? ''] ?? model?.status }}</p>
          <dl>
            <div><dt>模型观察</dt><dd>{{ formatBeijingInstant(model?.observed_at ?? model?.worker_at) }}<span v-if="modelRead === 'ready' && !model?.run_id"> · 尚无 run</span></dd></div>
            <div><dt>最近合约估值</dt><dd>{{ formatBeijingInstant(modelValuationAt) }}</dd></div>
            <div><dt>组合权益</dt><dd>{{ monitorMoney(model?.account.equity) }}</dd></div>
            <div><dt>日内净损益 {{ model?.trading_day }}</dt><dd>{{ monitorMoney(model?.day_net) }}</dd></div>
          </dl>
        </section>
      </div>

      <section class="activity" aria-labelledby="activity-heading">
        <h2 id="activity-heading">持仓与待处理</h2>
        <p class="source-notes">快期 · {{ tqCurrent ? (tqOverview?.positions.length ? '持仓已核验' : '空仓') : '当前持仓待核验' }} · {{ tqRecordsRead === 'error' ? '执行记录读取失败' : '最近执行记录，全部活动委托未核验' }}</p>
        <p class="source-notes">苏冰 · {{ subingCurrent
          ? (subingAccount.rows.some(row => row.positions.length) ? '持仓已读取' : '空仓') + ' · ' + (subingAccount.rows.some(row => row.actions.length) ? '有待处理动作' : '无模型待处理动作')
          : modelRead === 'ready' && !model?.run_id ? '尚无 run' : '当前持仓与待处理动作待核验' }}</p>
        <table v-if="rows.length">
          <thead><tr><th scope="col">账户来源</th><th scope="col">物理合约</th><th scope="col">持仓</th><th scope="col">待处理动作</th><th scope="col">更新时间</th><th scope="col">行情</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="`${row.source}:${row.contract}`">
              <td>{{ row.account }}<small v-if="row.source === 'htdy' ? !tqCurrent : !subingCurrent">最近快照 · 待核验</small></td>
              <th scope="row">{{ row.contract }}</th>
              <td>{{ row.positions.join(' / ') || ((row.source === 'htdy' ? tqCurrent : subingCurrent) ? '空仓' : '—') }}</td>
              <td><div v-for="(action, index) in row.actions" :key="index">{{ action.label }}<small v-if="action.at">{{ formatBeijingInstant(action.at) }}</small></div><span v-if="!row.actions.length">—</span></td>
              <td>{{ formatBeijingInstant(row.updatedAt) }}</td>
              <td><RouterLink :to="activityChartLink(row)" :aria-label="`看图 ${row.contract} ${row.account}`">看图</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>
  </div>
</template>

<style scoped>
.operations { min-height: 100%; background: var(--gy-bg-app); }
main { max-width: 1600px; margin: auto; padding: 24px 32px; }
h1 { margin: 0 0 16px; font-size: 24px; }
h2 { margin: 0; font-size: 16px; }
.accounts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
section { padding: 16px; background: var(--gy-bg-panel); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); }
section header { display: flex; justify-content: space-between; align-items: center; }
section p { margin: 8px 0; }
dl { display: flex; flex-wrap: wrap; gap: 12px 20px; margin: 12px 0 0; }
dt, .source-notes, small { color: var(--gy-text-secondary); font-size: 12px; }
dd { margin: 4px 0 0; font-variant-numeric: tabular-nums; }
.activity { margin-top: 16px; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--gy-border-subtle); }
thead { color: var(--gy-text-secondary); }
small { display: block; }
a { color: var(--gy-link, #2f5fd2); }
</style>
