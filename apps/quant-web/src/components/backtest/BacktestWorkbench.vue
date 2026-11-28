<script setup lang="ts">
import { computed, onMounted, onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import { diagnosticCode, readExperiments, readRuns, runInProgress, type Experiment, type Run, type RunFilters, type RunPage } from '@/api/backtestCenter'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { diagnosticLabel, metricValue, sampleLabels, statusLabel } from './backtestDisplay'

const filters = reactive<RunFilters>({ strategy_id: '', product: '', signal_frequency: '', start: '', end: '', status: '', sort: '' })
const applied = shallowRef({ ...filters })
const state = shallowRef<RunPage>()
const recent = shallowRef<Experiment[]>([])
const offset = ref(0)
const limit = 30
const loading = ref(true)
const failure = ref('')
const experimentError = ref('')
const refresh = ref(0)
const statuses = ['QUEUED', 'RUNNING', 'CANCELING', 'SUCCEEDED', 'FAILED', 'CANCELED'] as const
const name = (value: Run | string) => typeof value === 'string' ? value : value.run_id
const counts = computed(() => [
  { label: '任务总数', value: state.value ? Object.values(state.value.counts).reduce((sum, value) => sum + value, 0) : undefined },
  { label: '运行中', value: state.value && (['RUNNING', 'QUEUED', 'CANCELING'] as const).reduce((sum, status) => sum + (state.value?.counts?.[status] ?? 0), 0) },
  { label: '成功', value: state.value && (state.value.counts?.SUCCEEDED ?? 0) },
  { label: '失败', value: state.value && (state.value.counts?.FAILED ?? 0) },
])
const latest = computed(() => [
  { label: '最后一次尝试', run: state.value?.latest_attempt },
  { label: '最近一次成功', run: state.value?.latest_success },
])
const strategies = computed(() => [...new Set((state.value?.items ?? []).map(item => item.config.strategy_id))].slice(0, 5))
const experimentKinds = { comparison: '参数实验', oos: '样本外验证', walk_forward: 'Walk-forward' }

function apply() {
  offset.value = 0
  applied.value = { ...filters, product: filters.product.toUpperCase(), strategy_id: filters.strategy_id.trim() }
}

watch([applied, offset, refresh], async (_, __, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  loading.value = true
  failure.value = ''
  try {
    const result = await readRuns(applied.value, offset.value, limit, controller.signal)
    if (!controller.signal.aborted) state.value = result
  } catch (error) {
    if (!controller.signal.aborted) failure.value = diagnosticCode(error) ?? '任务列表读取失败'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

const recentController = new AbortController()
async function refreshExperiments() {
  try {
    const response = await readExperiments(recentController.signal)
    recent.value = response.items
    experimentError.value = ''
  } catch (error) {
    if (!recentController.signal.aborted) experimentError.value = diagnosticCode(error) ?? '实验列表读取失败'
  }
}

let timer: number | undefined
onMounted(() => {
  void refreshExperiments()
  timer = window.setInterval(() => {
    if (!loading.value && runInProgress(typeof state.value?.latest_attempt === 'object' ? state.value?.latest_attempt?.status : undefined)) refresh.value += 1
  }, 4000)
})
onScopeDispose(() => {
  recentController.abort()
  window.clearInterval(timer)
})
</script>

<template>
  <section aria-labelledby="workbench-heading">
    <div class="bt-panel-header"><h2 id="workbench-heading">历史任务</h2><button class="bt-button" :disabled="loading" @click="refresh += 1; refreshExperiments()">刷新</button></div>
    <dl class="bt-metrics" aria-label="任务计数">
      <div v-for="count in counts" :key="count.label"><dt>{{ count.label }}</dt><dd>{{ count.value ?? '—' }}</dd></div>
    </dl>
    <div class="bt-latest">
      <div v-for="item in latest" :key="item.label">
        <span>{{ item.label }}</span>
        <RouterLink v-if="item.run" :to="{ name: 'backtests', params: { runId: name(item.run) } }">{{ name(item.run) }}</RouterLink>
        <span v-else>—</span>
      </div>
    </div>
    <form class="bt-filters" @submit.prevent="apply">
      <label>策略 <input v-model="filters.strategy_id" placeholder="策略目录键" /></label>
      <label>品种 <input v-model="filters.product" maxlength="8" placeholder="FU" /></label>
      <label>信号周期 <select v-model="filters.signal_frequency"><option value="">全部</option><option v-for="value in ['5m','15m','30m','60m','1d','1w']" :key="value">{{ value }}</option></select></label>
      <label>评价开始 <input v-model="filters.start" type="date" /></label>
      <label>评价结束 <input v-model="filters.end" type="date" /></label>
      <label>状态 <select v-model="filters.status"><option value="">全部</option><option v-for="value in statuses" :key="value" :value="value">{{ statusLabel(value) }}</option></select></label>
      <label>排序 <select v-model="filters.sort"><option value="">最新提交</option><option value="net_return">净收益为正且有已平仓交易</option></select></label>
      <button class="bt-button" type="submit">筛选</button>
    </form>
    <p v-if="failure" class="bt-alert" role="alert">{{ diagnosticLabel(failure) }}</p>
    <div v-if="state?.items.length" class="bt-table-scroll" :aria-busy="loading">
      <table class="bt-table">
        <thead><tr><th>Run</th><th>状态</th><th>策略 / 合约</th><th>周期</th><th>评价区间</th><th>研究资格 / 样本</th><th>净累计收益</th><th>最大回撤</th><th>有效交易数</th><th>提交时间</th></tr></thead>
        <tbody><tr v-for="item in state.items" :key="item.run_id">
          <td><RouterLink class="bt-id" :to="{ name: 'backtests', params: { runId: item.run_id } }">{{ item.run_id }}</RouterLink></td>
          <td><span class="bt-status" :data-status="item.status">{{ statusLabel(item.status) }}</span></td>
          <td>{{ item.config.strategy_id }} <small>{{ item.config.contract }}</small></td>
          <td>{{ item.config.signal_frequency }}</td>
          <td class="bt-nowrap">{{ item.config.start }} 至 {{ item.config.end }}</td>
          <td>{{ statusLabel(item.qualification) }} <small>{{ sampleLabels[item.summary?.sample_type ?? item.config.sample_type ?? 'historical'] ?? '—' }}</small></td>
          <td>{{ metricValue('net_return', item.summary?.metrics?.net_return) }}</td>
          <td>{{ metricValue('max_drawdown', item.summary?.metrics?.max_drawdown) }}</td>
          <td>{{ metricValue('trade_count', item.summary?.metrics?.trade_count) }}</td>
          <td class="bt-nowrap">{{ formatBeijingInstant(item.created_at) }}</td>
        </tr></tbody>
      </table>
    </div>
    <p v-else-if="!failure" class="bt-note">{{ loading ? '正在读取历史任务' : '无匹配任务' }}</p>
    <div v-if="state && state.total > limit" class="bt-pager">
      <button class="bt-button" :disabled="offset === 0 || loading" @click="offset -= limit">上一页</button>
      <span>第 {{ Math.floor(offset / limit) + 1 }} 页 · {{ state.total }} 项</span>
      <button class="bt-button" :disabled="offset + limit >= state.total || loading" @click="offset += limit">下一页</button>
    </div>
  </section>

  <div class="bt-columns">
    <section aria-labelledby="recent-strategies">
      <h2 id="recent-strategies">近期策略</h2>
      <ul v-if="strategies.length" class="bt-list">
        <li v-for="strategy in strategies" :key="strategy"><RouterLink :to="{ name: 'backtests', query: { view: 'config', strategy } }">{{ strategy }}</RouterLink></li>
      </ul>
      <p v-else-if="state && !failure" class="bt-note">暂无近期策略</p>
    </section>
    <section aria-labelledby="recent-experiments">
      <h2 id="recent-experiments">近期实验与验证</h2>
      <p v-if="experimentError" class="bt-alert">{{ diagnosticLabel(experimentError) }}</p>
      <ul v-else-if="recent.length" class="bt-list">
        <li v-for="item in recent.slice(0, 5)" :key="item.experiment_id">
          <RouterLink :to="{ name: 'backtests', query: { view: item.kind === 'comparison' ? 'experiments' : 'validation', experiment: item.experiment_id } }">{{ experimentKinds[item.kind] }} · {{ item.experiment_id }}</RouterLink>
          <small>{{ statusLabel(item.status) }}</small>
        </li>
      </ul>
      <p v-else class="bt-note">暂无近期实验</p>
    </section>
  </div>
</template>
