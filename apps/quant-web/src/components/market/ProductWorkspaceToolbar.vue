<script setup lang="ts">
import { computed } from 'vue'
import {
  NButton,
  NButtonGroup,
  NInput,
  NPopover,
  NSelect,
  NSwitch,
} from 'naive-ui'
import type { DominantContractItem, MarketFrequency, OptionalEmaIndicatorId, ResearchOverlayId, SeriesKind } from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'
import { RESEARCH_OVERLAY_DEFINITIONS } from '@/utils/mainIndicators'

const props = defineProps<{
  symbol: string
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract: string
  dominants: DominantContractItem[]
  selectedOverlay: ResearchOverlayId
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showRangeDetector: boolean
  fullscreen: boolean
}>()

const emit = defineEmits<{
  'update:symbol': [value: string]
  'update:series-kind': [value: SeriesKind]
  'update:frequency': [value: MarketFrequency]
  'update:contract': [value: string]
  'update:selected-overlay': [value: ResearchOverlayId]
  'update:optional-ema-indicators': [value: OptionalEmaIndicatorId[]]
  'update:show-range-detector': [value: boolean]
  'open-research': []
  'toggle-fullscreen': []
  back: []
}>()

const symbolOptions = computed(() => props.dominants.map((item) => ({
  label: `${item.product.toUpperCase()} ${item.product_name}`,
  value: item.product,
})))
const overlayOptions: Array<{ label: string; value: ResearchOverlayId }> = RESEARCH_OVERLAY_DEFINITIONS
  .map((definition) => ({ label: definition.label, value: definition.id }))
const optionalEmaOptions: Array<{ label: string; value: OptionalEmaIndicatorId }> = [
  { label: 'EMA10', value: 'ema_10' },
  { label: 'EMA21', value: 'ema_21' },
  { label: 'EMA60', value: 'ema_60' },
]

function periodLabel(value: MarketFrequency) {
  return value === '1d' ? 'D' : value === '1w' ? 'W' : value
}

function toggleOptionalEma(value: OptionalEmaIndicatorId) {
  const selected = new Set(props.optionalEmaIndicators)
  if (selected.has(value)) selected.delete(value)
  else selected.add(value)
  emit('update:optional-ema-indicators', optionalEmaOptions.map((item) => item.value).filter((id) => selected.has(id)))
}

</script>

<template>
  <div class="product-workspace-toolbar">
    <div class="toolbar__identity-row" role="group" aria-label="对象与视图">
      <NButton quaternary size="small" class="toolbar__back" @click="emit('back')">市场</NButton>
      <NSelect
        :value="symbol"
        :options="symbolOptions"
        filterable
        size="small"
        class="toolbar__symbol"
        aria-label="品种"
        @update:value="emit('update:symbol', $event)"
      />
      <NButtonGroup size="small" class="toolbar__series">
        <NButton
          :type="seriesKind === 'actual_dominant' ? 'primary' : 'default'"
          @click="emit('update:series-kind', 'actual_dominant')"
        >真实主力</NButton>
        <NButton
          :type="seriesKind === 'continuous' ? 'primary' : 'default'"
          @click="emit('update:series-kind', 'continuous')"
        >主连</NButton>
      </NButtonGroup>
    </div>

    <div class="toolbar__actions" role="group" aria-label="图表操作">
      <NButton size="small" secondary class="toolbar__research" @click="emit('open-research')">检查</NButton>
      <NPopover trigger="click" placement="bottom-end">
        <template #trigger><NButton size="small" tertiary>图表设置</NButton></template>
        <div class="toolbar__settings">
          <span>EMA</span>
          <NButtonGroup size="small" aria-label="EMA">
            <NButton
              v-for="item in optionalEmaOptions"
              :key="item.value"
              :type="optionalEmaIndicators.includes(item.value) ? 'primary' : 'default'"
              :aria-pressed="optionalEmaIndicators.includes(item.value)"
              @click="toggleOptionalEma(item.value)"
            >{{ item.label }}</NButton>
          </NButtonGroup>
          <div class="toolbar__settings-title">
            <span>箱体识别</span>
            <NSwitch
              :value="showRangeDetector"
              size="small"
              aria-label="显示箱体识别"
              @update:value="emit('update:show-range-detector', $event)"
            />
          </div>
          <small class="toolbar__settings-help">
            使用已完成 K 线；箱体左端为回画展示，确认前不可用于策略判断
          </small>
          <span>指定真实合约</span>
          <NInput
            :value="contract"
            size="small"
            placeholder="例如 JM2601"
            @update:value="emit('update:contract', $event.toUpperCase())"
          />
          <NButton size="small" :type="seriesKind === 'contract' ? 'primary' : 'default'" @click="emit('update:series-kind', 'contract')">
            使用指定合约
          </NButton>
        </div>
      </NPopover>
      <NButton size="small" secondary @click="emit('toggle-fullscreen')">
        {{ fullscreen ? '退出全屏' : '全屏' }}
      </NButton>
    </div>

    <div class="toolbar__analysis-row" role="group" aria-label="研究视角">
      <NButtonGroup size="small" class="toolbar__periods" aria-label="周期">
        <NButton
          v-for="item in MARKET_FREQUENCIES"
          :key="item"
          :type="frequency === item ? 'primary' : 'default'"
          @click="emit('update:frequency', item)"
        >{{ periodLabel(item) }}</NButton>
      </NButtonGroup>
      <NButtonGroup size="small" class="toolbar__overlay" aria-label="Overlay">
        <NButton
          v-for="item in overlayOptions"
          :key="item.value"
          :type="selectedOverlay === item.value ? 'primary' : 'default'"
          @click="emit('update:selected-overlay', item.value)"
        >{{ item.label }}</NButton>
      </NButtonGroup>
    </div>
  </div>
</template>

<style scoped>
.product-workspace-toolbar {
  display: grid;
  grid-template-areas:
    'identity actions'
    'analysis analysis';
  grid-template-columns: minmax(0, 1fr) max-content;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
}
.toolbar__identity-row { grid-area: identity; display: flex; align-items: center; gap: 8px; min-width: 0; }
.toolbar__actions { grid-area: actions; display: flex; align-items: center; justify-self: end; gap: 8px; white-space: nowrap; }
.toolbar__analysis-row { grid-area: analysis; display: flex; align-items: center; gap: 12px; min-width: 0; flex-wrap: wrap; }
.toolbar__symbol { width: 184px; }
.toolbar__series, .toolbar__periods, .toolbar__overlay { white-space: nowrap; }
.toolbar__settings { display: grid; gap: 8px; width: 196px; padding: 4px; }
.toolbar__settings > span { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.toolbar__settings-title { display: flex; align-items: center; justify-content: space-between; color: var(--gy-text-primary); font-size: var(--gy-font-size-sm); }
.toolbar__settings-help { line-height: 1.45; font-size: var(--gy-font-size-xs); }
.toolbar__settings-help { color: var(--gy-text-muted); }

@media (max-width: 860px) {
  .product-workspace-toolbar {
    grid-template-areas:
      'identity'
      'analysis'
      'actions';
    grid-template-columns: minmax(0, 1fr);
  }
  .toolbar__back { display: none; }
  .toolbar__symbol { width: min(184px, calc(100vw - 62px)); }
  .toolbar__identity-row, .toolbar__analysis-row { flex-wrap: wrap; }
  .toolbar__actions { justify-self: start; }
}
</style>
