<script setup lang="ts">
import { computed, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import request from '@/api/request'
import { readWorkstationHealth } from '@/api/runtime'
import { getMarketProductDirectory } from '@/api/market'
import { readStrategies } from '@/api/strategyCenter'
import { useWorkstationRead } from '@/composables/useWorkstationRead'
import { componentRows, healthLabel, needsAttention } from '@/utils/workstationHealth'
import { workstationUiVersion } from '@/utils/workstationNavigation'
import { formatBeijingInstant } from '@/utils/marketDisplay'

const { value: health, state: healthState, refresh: refreshHealth } = useWorkstationRead(readWorkstationHealth)
const { value: api, state: apiState, refresh: refreshApi } = useWorkstationRead(signal =>
  request.get<unknown, { version: string; status: string; preview?: boolean }>('/api/health', { signal }))
const { value: directory, state: directoryState, refresh: refreshDirectory } = useWorkstationRead(getMarketProductDirectory)
const { value: strategies, state: strategyState, refresh: refreshStrategies } = useWorkstationRead(readStrategies)
const rows = computed(() => componentRows(health.value))
const live = computed(() => health.value?.components.live_market)
const archive = computed(() => health.value?.components.after_market)
const audit = computed(() => health.value?.components.weekly_audit)
const coverage = computed(() => Object.entries(live.value?.coverage ?? {}).sort(([a], [b]) => a.localeCompare(b)))
const appVersion = import.meta.env.VITE_APP_VERSION
const route = useRoute()
watch([() => route.hash, healthState], async ([hash]) => {
  if (!['#versions', '#quality', '#runtime'].includes(hash)) return
  await nextTick()
  document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' })
}, { immediate: true })
function refresh() {
  void refreshHealth()
  void refreshApi()
  void refreshDirectory()
  void refreshStrategies()
}
function sourceState(state: string) { return state === 'error' ? '读取失败' : state === 'loading' ? '正在读取' : '暂无读回' }
</script>

<template>
  <main class="ws-system">
    <header class="ws-heading">
      <h1>数据与系统</h1>
      <div class="ws-actions"><span v-if="health" class="ws-subtle">快照 {{ formatBeijingInstant(health.generated_at) }}</span><button class="ws-button" type="button" @click="refresh">刷新读回</button></div>
    </header>
    <div class="ws-metrics" aria-label="系统摘要">
      <div><small>运行健康</small><strong :class="health && needsAttention(health.status) ? 'ws-attention' : ''">{{ health ? healthLabel(health.status) : sourceState(healthState) }}</strong></div>
      <div><small>品种目录</small><strong>{{ directory ? directory.items.length + ' 个品种' : sourceState(directoryState) }}</strong></div>
      <div><small>已订阅 / 运行范围</small><strong>{{ live?.subscribed_count ?? '—' }} / {{ live?.operational_count ?? '—' }}</strong></div>
      <div><small>最近归档成功交易日</small><strong>{{ archive?.last_successful_trading_day ?? '—' }}</strong></div>
    </div>
    <div class="system-grid">
      <section id="runtime" class="ws-panel">
        <h2>服务与后台任务</h2>
        <p v-if="!health" :role="healthState === 'error' ? 'alert' : 'status'">Runtime 健康{{ sourceState(healthState) }}</p>
        <table v-else><thead><tr><th>组件</th><th>状态</th><th>诊断</th></tr></thead><tbody>
          <tr v-for="row in rows" :key="row.key"><th scope="row">{{ row.title }}</th>
            <td :class="{ 'ws-attention': needsAttention(row.status), 'ws-good': row.status === 'ok' }">{{ healthLabel(row.status) }}</td>
            <td><code>{{ row.diagnostic ?? '—' }}</code></td></tr>
        </tbody></table>
      </section>
      <section id="quality" class="ws-panel">
        <h2>行情与数据质量</h2>
        <dl><dt>盘中覆盖</dt><dd>{{ healthLabel(live?.coverage_state) }}</dd>
          <dt>最后行情 Bar</dt><dd>{{ formatBeijingInstant(live?.last_bar_at) }}</dd>
          <dt>行情心跳</dt><dd>{{ formatBeijingInstant(live?.last_heartbeat_at) }}</dd>
          <dt>盘后归档</dt><dd>{{ healthLabel(archive?.run_state) }} · 应归档 {{ archive?.expected_trading_day ?? '—' }}</dd>
          <dt>最近一次归档</dt><dd>{{ archive?.last_run?.trading_day ?? '—' }} · {{ healthLabel(archive?.last_run?.status) }}</dd>
          <dt>全历史审计</dt><dd>{{ healthLabel(audit?.status) }} · 截至 {{ audit?.through ?? '—' }}</dd>
          <dt>审计问题数</dt><dd>{{ audit?.finding_count ?? '—' }}</dd>
        </dl>
        <details v-if="coverage.length"><summary>按品种查看覆盖（{{ coverage.length }}）</summary>
          <div class="system-scroll"><table><thead><tr><th>品种</th><th>状态</th><th>首个缺失 Bar</th></tr></thead><tbody>
            <tr v-for="[product, fact] in coverage" :key="product"><th>{{ product.toUpperCase() }}</th>
              <td>{{ healthLabel(fact.state) }}</td><td>{{ formatBeijingInstant(fact.first_missing_bar_end) }}</td></tr>
          </tbody></table></div>
        </details>
      </section>
      <section id="versions" class="ws-panel system-wide">
        <h2>组件与运行版本</h2>
        <table><thead><tr><th>组件</th><th>版本</th><th>来源</th></tr></thead><tbody>
          <tr><th scope="row">工作站界面</th><td><code>{{ workstationUiVersion }}</code></td><td>当前前端构建</td></tr>
          <tr><th scope="row">工作站应用</th><td><code>{{ appVersion || '未注入版本' }}</code></td><td>前端构建版本</td></tr>
          <tr><th scope="row">Quant API</th><td><code>{{ api?.version || sourceState(apiState) }}</code></td><td>{{ api?.preview ? '隔离预览 API 存活探针' : 'API 存活探针' }}</td></tr>
          <tr><th scope="row">策略中心</th><td><code>{{ strategies?.version || sourceState(strategyState) }}</code></td><td><RouterLink to="/strategies">策略目录</RouterLink></td></tr>
        </tbody></table>
        <details v-if="health?.runtime_identity"><summary>服务部署身份 · {{ healthLabel(health.runtime_identity.status) }}</summary>
          <div class="system-scroll"><table><thead><tr><th>服务</th><th>身份核验</th><th>Tag</th><th>Commit</th><th>代次</th></tr></thead>
            <tbody><tr v-for="(identity, name) in health.runtime_identity.services" :key="name"><th>{{ name }}</th><td>{{ healthLabel(identity.status) }}</td>
              <td>{{ identity.runtime_tag ?? '—' }}</td><td><code>{{ identity.runtime_commit ?? '—' }}</code></td><td>{{ identity.runtime_generation ?? '—' }}</td></tr></tbody>
          </table></div>
        </details><p v-else class="ws-subtle">服务部署身份暂无读回。</p>
      </section>
    </div>
  </main>
</template>

<style scoped>
.system-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.system-wide { grid-column: 1 / -1; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
td, th { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--gy-border-subtle); overflow-wrap: anywhere; }
thead th, dt { color: var(--gy-text-muted); font-size: 12px; }
tbody th { font-weight: 500; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 9px 16px; margin: 5px 0 14px; }
dd { margin: 0; font-variant-numeric: tabular-nums; }
details, .system-wide p { margin-top: 10px; }
summary { cursor: pointer; color: var(--gy-link); }
.system-scroll { max-height: 320px; overflow: auto; }
@media(max-width: 840px) { .system-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
