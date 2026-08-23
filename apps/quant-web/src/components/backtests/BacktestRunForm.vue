<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { NAlert, NButton, NCheckbox, NForm, NFormItem, NSelect } from 'naive-ui'
import { validateBacktestForm } from '@/utils/backtestCapability'
import type {
  BacktestParameterDescriptor,
  BacktestParameterValue,
  BacktestRunForm,
  BacktestStrategy,
} from '@/types/backtest'

const props = defineProps<{
  strategies: BacktestStrategy[]
  canStart: boolean
  submitting: boolean
}>()

const emit = defineEmits<{
  start: [form: BacktestRunForm]
}>()

const form = reactive<BacktestRunForm>({
  strategyId: '',
  startDate: '',
  endDate: '',
  frequency: '1d',
  futureCash: '',
  matchingType: 'current_bar',
  marginMultiplier: '',
  futuresCommissionMultiplier: '',
  slippageModel: 'PriceRatioSlippage',
  slippage: '',
  parameters: {},
})
const errors = ref<Record<string, string>>({})

const selectedStrategy = computed(() => props.strategies.find(({ id }) => id === form.strategyId) ?? null)
const frequencyOptions = computed(() => (
  selectedStrategy.value?.supported_frequencies.map((value) => ({ label: value, value })) ?? []
))
const matchingOptions = computed(() => (
  form.frequency === '1d'
    ? [{ label: 'current_bar', value: 'current_bar' }]
    : [
        { label: 'current_bar', value: 'current_bar' },
        { label: 'next_bar', value: 'next_bar' },
      ]
))

watch(
  () => props.strategies,
  (strategies) => {
    if (!strategies.length || strategies.some(({ id }) => id === form.strategyId)) return
    form.strategyId = strategies[0]!.id
  },
  { immediate: true },
)

watch(selectedStrategy, (strategy) => {
  if (!strategy) return
  const defaults = strategy.defaults
  form.frequency = strategy.supported_frequencies[0] ?? '1d'
  form.futureCash = defaults.future_cash ?? ''
  form.matchingType = defaults.matching_type === 'next_bar' ? 'next_bar' : 'current_bar'
  form.marginMultiplier = defaults.margin_multiplier ?? ''
  form.futuresCommissionMultiplier = defaults.futures_commission_multiplier ?? ''
  form.slippageModel = defaults.slippage_model === 'TickSizeSlippage'
    ? 'TickSizeSlippage'
    : 'PriceRatioSlippage'
  form.slippage = defaults.slippage ?? ''
  form.parameters = Object.fromEntries(strategy.parameters.map((descriptor) => [
    descriptor.name,
    descriptor.default,
  ]))
  errors.value = {}
}, { immediate: true })

watch(() => form.frequency, (frequency) => {
  if (frequency === '1d') form.matchingType = 'current_bar'
})

function submit() {
  if (!selectedStrategy.value || !props.canStart || props.submitting) return
  const nextErrors = validateBacktestForm(form, selectedStrategy.value)
  errors.value = nextErrors
  if (Object.keys(nextErrors).length) return
  emit('start', {
    ...form,
    parameters: { ...form.parameters },
  })
}

function parameterValue(descriptor: BacktestParameterDescriptor) {
  return form.parameters[descriptor.name] as BacktestParameterValue | undefined
}

function updateParameter(descriptor: BacktestParameterDescriptor, value: unknown) {
  form.parameters[descriptor.name] = descriptor.type === 'integer'
    ? Number((value as Event).target ? (value as Event & { target: HTMLInputElement }).target.value : value)
    : (value as BacktestParameterValue)
}

function inputValue(event: Event) {
  return (event.target as HTMLInputElement).value
}

function parameterLabel(name: string) {
  return ({
    lookback: '回看周期',
    threshold: '阈值',
    long_only: '仅做多',
    contract: '回测合约',
  } as Record<string, string>)[name] ?? name
}
</script>

<template>
  <section class="backtest-form" data-testid="backtest-form" aria-labelledby="backtest-form-heading">
    <h3 id="backtest-form-heading">新建回测</h3>
    <p v-if="selectedStrategy" class="backtest-form__description">{{ selectedStrategy.description }}</p>
    <NAlert v-if="Object.keys(errors).length" type="error" :bordered="false" class="backtest-form__errors">
      <ul><li v-for="(message, field) in errors" :key="field">{{ message }}</li></ul>
    </NAlert>
    <NForm label-placement="top" class="backtest-form__grid" @submit.prevent="submit">
      <NFormItem label="策略">
        <NSelect
          v-model:value="form.strategyId"
          data-testid="backtest-strategy"
          :options="strategies.map(({ id, name }) => ({ label: name, value: id }))"
        />
      </NFormItem>
      <NFormItem label="频率">
        <NSelect v-model:value="form.frequency" data-testid="backtest-frequency" :options="frequencyOptions" />
      </NFormItem>
      <NFormItem label="开始日期">
        <input v-model="form.startDate" data-testid="backtest-start-date" class="gy-native-input" type="date">
      </NFormItem>
      <NFormItem label="结束日期">
        <input v-model="form.endDate" data-testid="backtest-end-date" class="gy-native-input" type="date">
      </NFormItem>
      <NFormItem label="期货初始资金">
        <input v-model="form.futureCash" class="gy-native-input" inputmode="decimal">
      </NFormItem>
      <NFormItem label="撮合方式">
        <NSelect v-model:value="form.matchingType" :options="matchingOptions" />
      </NFormItem>
      <NFormItem label="保证金倍数">
        <input v-model="form.marginMultiplier" class="gy-native-input" inputmode="decimal">
      </NFormItem>
      <NFormItem label="期货手续费倍数">
        <input v-model="form.futuresCommissionMultiplier" class="gy-native-input" inputmode="decimal">
      </NFormItem>
      <NFormItem label="滑点模型">
        <NSelect
          v-model:value="form.slippageModel"
          :options="[
            { label: 'PriceRatioSlippage', value: 'PriceRatioSlippage' },
            { label: 'TickSizeSlippage', value: 'TickSizeSlippage' },
          ]"
        />
      </NFormItem>
      <NFormItem label="滑点">
        <input v-model="form.slippage" class="gy-native-input" inputmode="decimal">
      </NFormItem>

      <NFormItem
        v-for="descriptor in selectedStrategy?.parameters ?? []"
        :key="descriptor.name"
        :label="parameterLabel(descriptor.name)"
      >
        <NCheckbox
          v-if="descriptor.type === 'boolean'"
          :checked="parameterValue(descriptor) === true"
          @update:checked="updateParameter(descriptor, $event)"
        >
          {{ parameterValue(descriptor) ? '是' : '否' }}
        </NCheckbox>
        <NSelect
          v-else-if="descriptor.type === 'enum'"
          :value="parameterValue(descriptor) as string"
          :options="descriptor.options.map((value) => ({ label: value, value }))"
          @update:value="updateParameter(descriptor, $event)"
        />
        <input
          v-else
          :value="parameterValue(descriptor)"
          class="gy-native-input"
          :inputmode="descriptor.type === 'integer' ? 'numeric' : 'decimal'"
          :type="descriptor.type === 'integer' ? 'number' : 'text'"
          @input="updateParameter(descriptor, descriptor.type === 'integer' ? $event : inputValue($event))"
        >
      </NFormItem>

      <div class="backtest-form__action">
        <NButton
          attr-type="submit"
          type="primary"
          :disabled="!canStart || submitting"
          :loading="submitting"
          data-testid="start-backtest"
        >
          启动研究回测
        </NButton>
      </div>
    </NForm>
  </section>
</template>

<style scoped>
.backtest-form {
  padding: var(--gy-panel-padding);
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  box-shadow: var(--gy-shadow-panel);
}

h3 { margin: 0; font-size: var(--gy-font-size-lg); }
.backtest-form__description { margin: 4px 0 14px; color: var(--gy-text-muted); }
.backtest-form__errors { margin: 12px 0; }
.backtest-form__errors ul { margin: 0; padding-left: 18px; }
.backtest-form__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
.backtest-form__action { grid-column: 1 / -1; display: flex; justify-content: flex-end; }
.gy-native-input { width: 100%; }

@media (max-width: 900px) {
  .backtest-form__grid { grid-template-columns: 1fr; }
}
</style>
