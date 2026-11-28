<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  diagnosticCode, readExperiment, readExperimentEvidence, readExperiments, readTemplates, runInProgress, submitExperiment,
  type EvidenceFields, type Experiment, type ExperimentAxis, type ExperimentConfig, type ExperimentKind, type FoldConfig,
  type SelectionMetric, type Template,
} from '@/api/backtestCenter'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { displayValue, metricLabels, metricValue, statusLabel } from './backtestDisplay'

const props = defineProps<{ validation: boolean }>()
const route = useRoute()
const router = useRouter()
const current = shallowRef<Experiment>()
const list = shallowRef<Experiment[]>([])
const templates = shallowRef<Template[]>([])
const chosen = ref<string[]>([])
const axes = ref<ExperimentAxis[]>([])
const metric = ref<SelectionMetric>('net_return')
const validationKind = ref<ExperimentKind>('oos')
const kind = computed<ExperimentKind>(() => props.validation ? validationKind.value : 'comparison')
const selected = computed(() => typeof route.query.experiment === 'string' ? route.query.experiment : '')
const refresh = ref(0)
const pending = ref(false)
const loading = ref(true)
const error = ref('')
const listError = ref('')
const formError = ref('')
const evidenceError = ref('')
const evidence = shallowRef<EvidenceFields>()
let latestSubmit: { body: string; key: string } | undefined
const axisOptions: Array<{ id: ExperimentAxis; label: string }> = [
  { id: 'parameters', label: '执行参数' }, { id: 'strategy', label: '策略' }, { id: 'product', label: '品种与合约' },
  { id: 'frequency', label: '信号周期' }, { id: 'commission', label: '手续费' }, { id: 'slippage', label: '滑点' },
]
const experimentKinds: Record<ExperimentKind, string> = { comparison: '参数实验', oos: '样本外验证', walk_forward: 'Walk-forward' }
const dateFields: Array<[keyof FoldConfig, string]> = [
  ['train_warmup_start', '训练预热'], ['train_start', '训练开始'], ['train_end', '训练结束'],
  ['test_warmup_start', '测试预热'], ['test_start', '测试开始'], ['test_end', '测试结束'],
]
const newFold = (): FoldConfig => ({ train_warmup_start: '', train_start: '', train_end: '', test_warmup_start: '', test_start: '', test_end: '' })
const folds = ref<FoldConfig[]>([newFold()])
const selectedRuns = computed(() => chosen.value.flatMap(id => templates.value.filter(item => item.template_id === id)))
const rows = computed(() => list.value.filter(item => props.validation ? item.kind !== 'comparison' : item.kind === 'comparison'))
const inProgress = computed(() => runInProgress(current.value?.status) || current.value?.status === 'PENDING')
const alive = new AbortController()

watch(validationKind, (value) => {
  if (value === 'oos') folds.value = folds.value.slice(0, 1)
  if (value === 'walk_forward' && folds.value.length === 1) folds.value.push(newFold())
})

async function refreshList() {
  try {
    const result = await readExperiments(alive.signal)
    list.value = result.items
    listError.value = ''
  } catch (reason) {
    if (!alive.signal.aborted) listError.value = diagnosticCode(reason) ?? '实验历史读取失败'
  }
}

watch([selected, refresh], async ([id], [last], onCleanup) => {
  if (id !== last) current.value = undefined
  evidence.value = undefined
  error.value = ''
  evidenceError.value = ''
  if (!id) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const value = await readExperiment(id, controller.signal)
    if (controller.signal.aborted) return
    current.value = value
    if (value.evidence) evidence.value = value.evidence
    if (props.validation && !inProgress.value && !value.evidence) {
      try {
        const record = await readExperimentEvidence(id, controller.signal)
        if (!controller.signal.aborted) evidence.value = record
      } catch (reason) {
        if (!controller.signal.aborted) evidenceError.value = diagnosticCode(reason) ?? '证据暂不可读'
      }
    }
  } catch (reason) {
    if (!controller.signal.aborted) error.value = diagnosticCode(reason) ?? '实验明细读取失败'
  }
}, { immediate: true })

let timer: number | undefined
onMounted(async () => {
  timer = window.setInterval(() => {
    if (inProgress.value) refresh.value += 1
  }, 4000)
  void refreshList()
  try {
    const result = await readTemplates(alive.signal)
    templates.value = result.items
  } catch (reason) {
    if (!alive.signal.aborted) formError.value = diagnosticCode(reason) ?? '配置模板读取失败'
  } finally {
    loading.value = false
  }
})
onScopeDispose(() => {
  alive.abort()
  window.clearInterval(timer)
})

async function submit() {
  if (pending.value) return
  formError.value = ''
  const configs = selectedRuns.value.map(row => row.config)
  if (configs.length < 2 || configs.length > 12 || !axes.value.length) {
    formError.value = '请选择 2 至 12 个已保存配置及至少一个比较维度。'
    return
  }
  const definition: Omit<ExperimentConfig, 'request_key'> = {
    kind: kind.value, axes: [...axes.value], configs, metric: metric.value,
    folds: props.validation ? folds.value.map(row => ({ ...row })) : undefined,
  }
  if (props.validation && (
    configs.length * folds.value.length + folds.value.length > 48
    || folds.value.some((fold, index) => {
      const previous = folds.value[index - 1]
      return !(fold.train_warmup_start < fold.train_start && fold.train_start <= fold.train_end
        && fold.train_end < fold.test_start && fold.test_start <= fold.test_end && fold.test_warmup_start < fold.test_start)
        || Boolean(previous && (previous.test_end >= fold.test_start || previous.train_end >= fold.train_end))
    })
  )) {
    formError.value = '核对训练与测试的先后顺序、折间测试区间与 48 个成员 Run 的上限。'
    return
  }
  const body = JSON.stringify(definition)
  if (latestSubmit?.body !== body) latestSubmit = { body, key: crypto.randomUUID() }
  pending.value = true
  try {
    const result = await submitExperiment({ ...definition, request_key: latestSubmit.key })
    latestSubmit = undefined
    if (!alive.signal.aborted) {
      await router.push({ name: 'backtests', query: { view: props.validation ? 'validation' : 'experiments', experiment: result.experiment_id } })
      void refreshList()
    }
  } catch (reason) {
    if (!alive.signal.aborted) formError.value = diagnosticCode(reason) ?? '实验提交未确认。再次提交相同定义将沿用原请求。'
  } finally {
    pending.value = false
  }
}

function values(raw: unknown) {
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, string | number | null> : {}
}

function json(value: unknown) {
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <div class="bt-columns bt-experiments">
    <section aria-labelledby="experiment-form-heading">
      <h2 id="experiment-form-heading">{{ props.validation ? '提交样本外验证' : '提交参数实验' }}</h2>
      <p v-if="loading" class="bt-note">正在读取已保存配置</p>
      <form class="bt-form" @submit.prevent="submit">
        <label v-if="props.validation">验证方式
          <select v-model="validationKind"><option value="oos">单次样本外验证</option><option value="walk_forward">Walk-forward</option></select>
        </label>
        <label>排序与选参
          <select v-model="metric"><option value="net_return">最高净累计收益</option><option value="max_drawdown">最小最大回撤</option></select>
        </label>
        <fieldset class="bt-form-wide bt-checks">
          <legend>实验维度</legend>
          <label v-for="axis in axisOptions" :key="axis.id"><input v-model="axes" type="checkbox" :value="axis.id" />{{ axis.label }}</label>
        </fieldset>
        <fieldset class="bt-form-wide">
          <legend>成员配置</legend>
          <p v-if="!loading && templates.length < 2" class="bt-note">先在配置页保存至少两个回测模板。 <RouterLink :to="{ name: 'backtests', query: { view: 'config' } }">配置回测</RouterLink></p>
          <ul v-if="templates.length" class="bt-list bt-template-list">
            <li v-for="item in templates" :key="item.template_id">
              <label><input v-model="chosen" type="checkbox" :value="item.template_id" />{{ item.name }}</label>
              <small>{{ item.config.strategy_id }} · {{ item.config.contract }} · {{ item.config.signal_frequency }} · {{ item.config.start }} 至 {{ item.config.end }}</small>
              <small>资金 {{ item.config.initial_capital }} · 手续费倍率 {{ item.config.commission_multiplier ?? '默认' }} · 滑点 {{ item.config.slippage_ticks ?? 0 }} 跳 · 执行延迟 {{ item.config.parameters?.execution_delay_minutes ?? 0 }} 分钟</small>
            </li>
          </ul>
        </fieldset>
        <template v-if="props.validation">
          <p class="bt-form-wide bt-note">训练只使用折截止时已知的结算和费用。每折测试独立运行，期初状态与边界政策在报告中读回。</p>
          <fieldset v-for="(fold, index) in folds" :key="index" class="bt-form-wide bt-form">
            <legend>第 {{ index + 1 }} 折</legend>
            <label v-for="[field, label] in dateFields" :key="field">{{ label }} <input v-model="fold[field]" type="date" required /></label>
            <button v-if="folds.length > 2" class="bt-button" type="button" @click="folds.splice(index, 1)">移除此折</button>
          </fieldset>
          <button v-if="kind === 'walk_forward' && folds.length < 8" class="bt-button" type="button" @click="folds.push(newFold())">添加一折</button>
        </template>
        <p v-if="formError" class="bt-alert bt-form-wide" role="alert">{{ formError }}</p>
        <div class="bt-form-wide"><button class="bt-button bt-primary" :disabled="pending || loading || selectedRuns.length < 2" type="submit">{{ pending ? '正在提交' : '冻结定义并提交' }}</button></div>
      </form>
    </section>
    <section aria-labelledby="experiment-history-heading">
      <div class="bt-panel-header"><h2 id="experiment-history-heading">{{ props.validation ? '验证记录' : '实验记录' }}</h2><button class="bt-button" @click="refresh += 1; refreshList()">刷新</button></div>
      <p v-if="error || listError" class="bt-alert" role="alert">{{ error || listError }}</p>
      <ul v-if="rows.length" class="bt-list">
        <li v-for="item in rows" :key="item.experiment_id">
          <RouterLink :to="{ name: 'backtests', query: { view: props.validation ? 'validation' : 'experiments', experiment: item.experiment_id } }" :aria-current="selected === item.experiment_id ? 'true' : undefined">
            {{ experimentKinds[item.kind] }} · <code>{{ item.experiment_id }}</code>
          </RouterLink>
          <small>{{ statusLabel(item.status) }} · {{ formatBeijingInstant(item.created_at) }}</small>
        </li>
      </ul>
      <p v-else-if="!listError" class="bt-note">暂无记录</p>
    </section>
  </div>

  <section v-if="current" aria-labelledby="experiment-details-heading">
    <div class="bt-panel-header">
      <h2 id="experiment-details-heading">{{ experimentKinds[current.kind] }}结果</h2><span class="bt-status" :data-status="current.status">{{ statusLabel(current.status) }}</span>
    </div>
    <p class="bt-id">{{ current.experiment_id }}</p>
    <p v-if="current.comparison" class="bt-note">{{ current.comparison.comparable ? '同口径比较' : '条件不同或证据不足，按成员并列展示' }}</p>
    <p v-if="Array.isArray(current.comparison?.ranked_member_ids) && current.comparison.ranked_member_ids.length" class="bt-note">
      按 {{ metricLabels[displayValue(current.comparison?.metric)] ?? displayValue(current.comparison?.metric) }} 排序 · {{ current.comparison.ranked_member_ids.join(' → ') }}
    </p>
    <details v-if="current.comparison" class="bt-evidence"><summary>比较条件与失败成员</summary><pre>{{ json(current.comparison) }}</pre></details>
    <div v-if="current.members?.length" class="bt-table-scroll">
      <table class="bt-table">
        <thead><tr><th>成员 / Run</th><th>阶段</th><th>合约 / 周期</th><th>执行延迟</th><th>评价区间</th><th>状态</th><th>净累计收益</th><th>最大回撤</th><th>交易数</th></tr></thead>
        <tbody><tr v-for="member in current.members" :key="member.member_id">
          <td>
            <RouterLink v-if="member.run_id" :to="{ name: 'backtests', params: { runId: member.run_id } }">{{ member.member_id }}</RouterLink>
            <span v-else>{{ member.member_id }}</span>
          </td>
          <td>{{ statusLabel(member.phase) }} <small v-if="member.fold != null">折 {{ member.fold }}</small></td>
          <td>{{ member.research_config.contract }} / {{ member.research_config.signal_frequency }}</td>
          <td>{{ member.research_config.parameters?.execution_delay_minutes ?? 0 }} 分钟</td>
          <td>{{ member.research_config.start }} 至 {{ member.research_config.end }}</td>
          <td>{{ statusLabel(member.status) }} <small v-if="member.diagnostic">{{ member.diagnostic }}</small></td>
          <td>{{ metricValue('net_return', member.metrics?.net_return) }}</td>
          <td>{{ metricValue('max_drawdown', member.metrics?.max_drawdown) }}</td>
          <td>{{ metricValue('trade_count', member.metrics?.trade_count) }}</td>
        </tr></tbody>
      </table>
    </div>
    <div v-if="current.folds?.length" class="bt-table-scroll">
      <table class="bt-table">
        <thead><tr><th>折</th><th>训练截止</th><th>选中成员</th><th>测试成员</th><th>边界政策</th><th>测试期初</th><th>证据状态</th></tr></thead>
        <tbody><tr v-for="fold in current.folds" :key="fold.fold">
          <td>{{ fold.fold }}</td><td>{{ formatBeijingInstant(fold.selection_cutoff) }}</td>
          <td>{{ fold.selected_member_id ?? '—' }}</td><td>{{ fold.test_member_id ?? '—' }}</td>
          <td>{{ displayValue(fold.boundary_policy) }}</td><td>{{ displayValue(fold.test_initial_position) }} · {{ displayValue(fold.test_initial_equity) }}</td>
          <td>{{ statusLabel(fold.status) }} <small v-if="fold.diagnostic">{{ fold.diagnostic }}</small></td>
        </tr></tbody>
      </table>
    </div>
    <details v-if="current.definition" class="bt-evidence"><summary>冻结的比较条件、训练窗口和选择规则</summary><pre>{{ json(current.definition) }}</pre></details>
    <p v-if="evidenceError" class="bt-note" role="status">{{ evidenceError }}</p>
    <template v-if="evidence">
      <h3>样本外证据 · {{ statusLabel(displayValue(evidence.status)) }}</h3>
      <dl class="bt-metrics" v-if="evidence.metrics">
        <div v-for="(value, key) in values(evidence.metrics)" :key="key"><dt>{{ metricLabels[key] ?? key }}</dt><dd>{{ metricValue(key, value) }}</dd></div>
      </dl>
      <details class="bt-evidence"><summary>证据标识、成员、缺失折与合并口径</summary><pre>{{ json(evidence) }}</pre></details>
    </template>
  </section>
</template>
