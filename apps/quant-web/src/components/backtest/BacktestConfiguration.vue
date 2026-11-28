<script setup lang="ts">
import { computed, onMounted, onScopeDispose, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { diagnosticCode, readEligibility, readTemplates, saveTemplate, submitRun, type Eligibility, type RunConfig, type Template } from '@/api/backtestCenter'
import { diagnosticLabel, safeLocalLink, statusLabel } from './backtestDisplay'
import { pendingRunRequest } from './backtestSubmission'

const route = useRoute()
const router = useRouter()
const items = shallowRef<Eligibility[]>([])
const templates = shallowRef<Template[]>([])
const loading = ref(true)
const eligibilityError = ref('')
const templateError = ref('')
const error = ref('')
const message = ref('')
const saving = ref(false)
const submitting = ref(false)
const activeTemplate = ref('')
const templateName = ref('')
const delayOptions = [0, 1, 2, 3]
const executionDelay = ref(0)
const initial = (): RunConfig => ({
  strategy_id: 'newow_trend', product: 'FU', contract: '', signal_frequency: '5m', warmup_start: '',
  start: '', end: '', initial_capital: '100000', commission_multiplier: '1', slippage_ticks: 0,
})
const fields = reactive(initial())
const selected = computed(() => items.value.find(item => item.strategy_id === fields.strategy_id
  && (!item.product || item.product.toUpperCase() === fields.product.toUpperCase())
  && (!item.signal_frequency || item.signal_frequency === fields.signal_frequency)))
const versionMismatch = computed(() => Boolean(
  selected.value?.formula_version && fields.formula_version && selected.value.formula_version !== fields.formula_version
  || selected.value?.profile_id && fields.profile_id && selected.value.profile_id !== fields.profile_id,
))
const permitted = computed(() => !versionMismatch.value && selected.value !== undefined && ['TRIAL', 'QUALIFIED', 'READY', 'ELIGIBLE', 'AVAILABLE'].includes(selected.value.status))
const linkLabels: Record<string, string> = { history: '独立历史回放', paper: '共享 Paper' }
const strategyOptions = computed(() => [...new Map(items.value.map(item => [item.strategy_id, item.label]))])

function selectStrategy(id: string) {
  const option = items.value.find(item => item.strategy_id === id)
  fields.strategy_id = id
  fields.formula_version = option?.formula_version ?? undefined
  fields.profile_id = option?.profile_id ?? undefined
  if (option?.product) fields.product = option.product.toUpperCase()
  if (option?.signal_frequency) fields.signal_frequency = option.signal_frequency
}

function applyRouteChoice() {
  const id = route.query.strategy
  if (typeof id === 'string') selectStrategy(id)
  if (typeof route.query.formula_version === 'string') fields.formula_version = route.query.formula_version
  if (typeof route.query.profile_id === 'string') fields.profile_id = route.query.profile_id
}

watch(() => [route.query.strategy, route.query.formula_version, route.query.profile_id], applyRouteChoice, { immediate: true })

const controller = new AbortController()
onMounted(async () => {
  const eligibility = readEligibility(controller.signal).then((value) => {
    if (controller.signal.aborted) return
    items.value = value.items
    if (!items.value.some(item => item.strategy_id === fields.strategy_id)) fields.strategy_id = items.value[0]?.strategy_id ?? fields.strategy_id
    selectStrategy(fields.strategy_id)
    if (items.value.some(item => item.strategy_id === route.query.strategy)) applyRouteChoice()
  }, (reason) => {
    if (!controller.signal.aborted) eligibilityError.value = diagnosticCode(reason) ?? '接入资格读取失败'
  }).finally(() => { if (!controller.signal.aborted) loading.value = false })
  const saved = readTemplates(controller.signal).then((value) => {
    if (!controller.signal.aborted) templates.value = value.items
  }, (reason) => {
    if (!controller.signal.aborted) templateError.value = diagnosticCode(reason) ?? '模板读取失败'
  })
  await Promise.all([eligibility, saved])
})
onScopeDispose(() => controller.abort())

function loadTemplate() {
  const template = templates.value.find(item => item.template_id === activeTemplate.value)
  if (!template) {
    Object.assign(fields, initial(), { formula_version: undefined, profile_id: undefined, parameters: undefined })
    selectStrategy(typeof route.query.strategy === 'string' ? route.query.strategy : fields.strategy_id)
    templateName.value = ''
    executionDelay.value = 0
    return
  }
  Object.assign(fields, initial(), { formula_version: undefined, profile_id: undefined, parameters: undefined }, template.config)
  activeTemplate.value = template.template_id
  templateName.value = template.name
  executionDelay.value = Number(template.config.parameters?.execution_delay_minutes ?? 0)
  error.value = ''
  message.value = ''
}

function effectiveConfiguration(): RunConfig | undefined {
  error.value = ''
  const contract = fields.contract.trim().toUpperCase()
  const product = fields.product.trim().toUpperCase()
  if (!/^[A-Z]{1,8}$/.test(product) || !new RegExp('^' + product + '[0-9]{3,4}$').test(contract)) {
    error.value = '物理合约须属于所填品种，例如 FU2603。'
    return
  }
  if (!fields.warmup_start || !fields.start || !fields.end || fields.warmup_start >= fields.start || fields.start > fields.end) {
    error.value = '预热开始须早于评价开始，评价结束须在评价开始当天或之后。'
    return
  }
  if (!delayOptions.includes(executionDelay.value)) {
    error.value = '执行延迟须为 0 至 3 分钟的整数。'
    return
  }
  return {
    ...fields, contract, product,
    formula_version: fields.formula_version || selected.value?.formula_version || undefined,
    profile_id: fields.profile_id || selected.value?.profile_id || undefined,
    parameters: executionDelay.value ? { execution_delay_minutes: executionDelay.value } : undefined,
  }
}

async function save() {
  const config = effectiveConfiguration()
  if (!config || !templateName.value.trim()) {
    if (config) error.value = '请填写模板名称。'
    return
  }
  saving.value = true
  message.value = ''
  try {
    const id = activeTemplate.value || crypto.randomUUID()
    const template = await saveTemplate(id, templateName.value.trim(), config)
    templates.value = [...templates.value.filter(row => row.template_id !== template.template_id), template]
    activeTemplate.value = template.template_id
    message.value = '模板已保存。'
  } catch (reason) {
    error.value = diagnosticCode(reason) ?? '模板保存失败'
  } finally {
    saving.value = false
  }
}

async function submit() {
  if (!permitted.value || submitting.value) return
  const config = effectiveConfiguration()
  if (!config) return
  submitting.value = true
  message.value = ''
  try {
    const pending = await pendingRunRequest('submit', config)
    const result = await submitRun(pending.key, config)
    pending.accepted()
    if (!controller.signal.aborted) await router.push({ name: 'backtests', params: { runId: result.run_id } })
  } catch (reason) {
    if (!controller.signal.aborted) error.value = diagnosticCode(reason) ?? '提交结果未确认。再次提交相同配置将沿用原请求。'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="bt-columns bt-config">
    <section aria-labelledby="configuration-heading">
      <h2 id="configuration-heading">回测配置</h2>
      <div class="bt-template-controls">
        <label>已保存模板
          <select v-model="activeTemplate" @change="loadTemplate">
            <option value="">新配置</option><option v-for="item in templates" :key="item.template_id" :value="item.template_id">{{ item.name }}</option>
          </select>
        </label>
        <p v-if="templateError" class="bt-alert">{{ diagnosticLabel(templateError) }}</p>
      </div>
      <form class="bt-form" @submit.prevent="submit">
        <label>策略 <select :value="fields.strategy_id" :disabled="loading" @change="selectStrategy(($event.target as HTMLSelectElement).value)">
          <option v-for="[id, label] in strategyOptions" :key="id" :value="id">{{ label }}</option>
        </select></label>
        <label>物理合约 <input v-model="fields.contract" maxlength="12" placeholder="FU2603" required /></label>
        <label>品种 <input v-model="fields.product" maxlength="8" required /></label>
        <label>信号周期 <select v-model="fields.signal_frequency"><option v-for="value in ['5m','15m','30m','60m','1d','1w']" :key="value">{{ value }}</option></select></label>
        <label>公式版本 <input :value="fields.formula_version || selected?.formula_version || '待核验'" readonly /></label>
        <label>参数 Profile <input :value="fields.profile_id || selected?.profile_id || '待核验'" readonly /></label>
        <label>预热开始 <input v-model="fields.warmup_start" type="date" required /></label>
        <label>评价开始 <input v-model="fields.start" type="date" required /></label>
        <label>评价结束 <input v-model="fields.end" type="date" required /></label>
        <label>初始资金 <input v-model="fields.initial_capital" inputmode="decimal" required /></label>
        <label>手续费倍率 <input v-model="fields.commission_multiplier" inputmode="decimal" required /></label>
        <label>滑点（跳） <input v-model.number="fields.slippage_ticks" type="number" min="0" max="20" step="1" required /></label>
        <label>执行延迟（分钟）
          <select v-model="executionDelay" :disabled="!selected?.research_parameters?.execution_delay_minutes" aria-describedby="execution-delay-note">
            <option v-for="delay in delayOptions" :key="delay" :value="delay">{{ delay }}</option>
          </select>
        </label>
        <p id="execution-delay-note" class="bt-form-wide bt-note">从同一 Session 内严格晚于信号可用时点的首个 1m 开盘起再延迟指定分钟。公式与信号保持固定。</p>
        <div class="bt-form-wide">
          <p v-if="!loading && !permitted && !versionMismatch" class="bt-note">{{ selected?.reason ? diagnosticLabel(selected.reason) : '所选策略、品种及周期组合未核验。' }}</p>
          <p v-if="versionMismatch" class="bt-note">所选目录版本尚无回测资格。 <button class="bt-button" type="button" @click="selectStrategy(fields.strategy_id)">改用当前试验版本</button></p>
          <p v-if="error" class="bt-alert" role="alert">{{ diagnosticLabel(error) }}</p>
          <p v-if="message" class="bt-note" role="status">{{ message }}</p>
          <div class="bt-actions">
            <button class="bt-button bt-primary" type="submit" :disabled="submitting || !permitted">{{ submitting ? '正在提交' : '提交回测' }}</button>
            <label>模板名称 <input v-model="templateName" maxlength="80" /></label>
            <button class="bt-button" type="button" :disabled="saving" @click="save">{{ activeTemplate ? '更新模板' : '保存模板' }}</button>
          </div>
        </div>
      </form>
    </section>
    <section aria-labelledby="eligibility-heading">
      <h2 id="eligibility-heading">回测接入资格</h2>
      <p v-if="eligibilityError" class="bt-alert" role="alert">{{ eligibilityError }}</p>
      <p v-else-if="loading" class="bt-note">正在读取策略目录与组合资格</p>
      <div v-else class="bt-table-scroll">
        <table class="bt-table" aria-labelledby="eligibility-heading">
          <thead><tr><th>策略</th><th>资格与原因</th><th>已声明组合</th></tr></thead>
          <tbody><tr v-for="item in items" :key="[item.strategy_id, item.product, item.signal_frequency, item.profile_id].join('/')">
            <th scope="row">{{ item.label }}</th>
            <td>
              <span class="bt-status" :data-status="item.status">{{ statusLabel(item.status) }}</span>
              <p>{{ diagnosticLabel(item.reason) }}</p>
              <template v-for="(link, label) in item.links" :key="label">
                <RouterLink v-if="safeLocalLink(link)" :to="link">{{ linkLabels[label] ?? label }}</RouterLink>
              </template>
            </td>
            <td>{{ [item.product, item.signal_frequency, item.execution_frequency].filter(Boolean).join(' / ') || '—' }}</td>
          </tr></tbody>
        </table>
      </div>
    </section>
  </div>
</template>
