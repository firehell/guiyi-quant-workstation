<script setup lang="ts">
import { computed } from 'vue'
import {
  NButton,
  NButtonGroup,
  NInput,
  NPopover,
  NSelect,
  NSwitch,
  NTag,
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
  showSubingInternalProcess: boolean
  fullscreen: boolean
}>()

const emit = defineEmits<{
  'update:symbol': [value: string]
  'update:series-kind': [value: SeriesKind]
  'update:frequency': [value: MarketFrequency]
  'update:contract': [value: string]
  'update:selected-overlay': [value: ResearchOverlayId]
  'update:optional-ema-indicators': [value: OptionalEmaIndicatorId[]]
  'update:show-subing-internal-process': [value: boolean]
  'open-research': []
  'toggle-fullscreen': []
  back: []
}>()

const symbolOptions = computed(() => props.dominants.map((item) => ({
  label: `${item.product.toUpperCase()} ${item.product_name}`,
  value: item.product,
})))
const currentDominant = computed(() => props.dominants.find((item) => item.product === props.symbol)?.actual_contract)
const overlayOptions: Array<{ label: string; value: ResearchOverlayId }> = RESEARCH_OVERLAY_DEFINITIONS
  .map((definition) => ({ label: definition.label, value: definition.id }))
const optionalEmaOptions: Array<{ label: string; value: OptionalEmaIndicatorId }> = [
  { label: 'EMA10', value: 'ema_10' },
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
    <NTag v-if="selectedOverlay === 'subing'" size="small" type="info" class="toolbar__subing-basis">
      苏冰计算 {{ currentDominant || '等待映射' }}
    </NTag>
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
        <div v-if="selectedOverlay === 'subing'" class="toolbar__settings-title">
          <span>显示苏冰内部研究过程</span>
          <NSwitch
            :value="showSubingInternalProcess"
            size="small"
            aria-label="显示苏冰内部研究过程"
            @update:value="emit('update:show-subing-internal-process', $event)"
          />
        </div>
        <small v-if="selectedOverlay === 'subing'" class="toolbar__settings-help">
          默认关闭；仅显示当前准备 / 研究确认 / 风险 / 结束事实
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
    <div class="toolbar__spacer" />
    <NButton size="small" secondary class="toolbar__research" @click="emit('open-research')">检查</NButton>
    <NButton size="small" secondary @click="emit('toggle-fullscreen')">
      {{ fullscreen ? '退出全屏' : '全屏' }}
    </NButton>
  </div>
</template>

<style scoped>
.product-workspace-toolbar { display: flex; align-items: center; gap: 8px; min-width: 0; flex-wrap: wrap; }
.toolbar__symbol { width: 184px; }
.toolbar__series, .toolbar__periods, .toolbar__overlay, .toolbar__subing-basis { white-space: nowrap; }
.toolbar__spacer { flex: 1 1 8px; }
.toolbar__settings { display: grid; gap: 8px; width: 196px; padding: 4px; }
.toolbar__settings > span { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.toolbar__settings-title { display: flex; align-items: center; justify-content: space-between; color: var(--gy-text-primary); font-size: var(--gy-font-size-sm); }
.toolbar__settings-help { line-height: 1.45; font-size: var(--gy-font-size-xs); }
.toolbar__settings-help { color: var(--gy-text-muted); }

@media (max-width: 860px) {
  .toolbar__back { display: none; }
  .toolbar__symbol { width: min(184px, calc(100vw - 62px)); }
  .toolbar__spacer { display: none; }
}
</style>
