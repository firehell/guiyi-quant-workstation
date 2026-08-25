<script setup lang="ts">
import { computed } from 'vue'
import type { MarketRadarItem } from '@/types/market'
import { groupMarketScatterItems } from '@/utils/marketScatter'

const props = defineProps<{ items: MarketRadarItem[] }>()
const emit = defineEmits<{ open: [item: MarketRadarItem] }>()

const quadrants = computed(() => groupMarketScatterItems(props.items))
const directionalQuadrants = computed(() => quadrants.value.filter((quadrant) => quadrant.key !== 'neutral'))
const neutralQuadrant = computed(() => quadrants.value.find((quadrant) => quadrant.key === 'neutral')!)

function signedPercent(value: number) {
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

function priceLabel(item: MarketRadarItem) { return signedPercent(item.price_change_1d!) }

function priceTone(item: MarketRadarItem) {
  if (item.price_change_1d! > 0) return 'up'
  if (item.price_change_1d! < 0) return 'down'
  return 'neutral'
}

function openInterestLabel(item: MarketRadarItem) {
  const value = item.oi_change_1d!
  if (value > 0) return `增仓 ${signedPercent(value)}`
  if (value < 0) return `减仓 ${signedPercent(value)}`
  return '持仓不变 0.00%'
}
</script>

<template>
  <section class="market-scatter" aria-labelledby="market-scatter-heading" data-testid="market-quadrant-list">
    <header><span>结构分布</span><h2 id="market-scatter-heading">价格变化 × OI 变化</h2></header>
    <div v-if="directionalQuadrants.some((quadrant) => quadrant.items.length)" class="market-scatter__grid">
      <article
        v-for="quadrant in directionalQuadrants"
        :key="quadrant.key"
        class="market-scatter__quadrant"
        :data-testid="`market-quadrant-${quadrant.key.replace('_', '-')}`"
      >
        <header class="market-scatter__quadrant-heading">
          <h3>{{ quadrant.label }}</h3><span>{{ quadrant.items.length }}</span>
        </header>
        <p v-if="!quadrant.items.length" class="market-scatter__empty">暂无</p>
        <div v-else class="market-scatter__items">
          <button
            v-for="item in quadrant.items"
            :key="item.symbol"
            class="market-scatter__item"
            :aria-label="`打开 ${item.symbol.toUpperCase()} ${item.product_name}`"
            @click="emit('open', item)"
          >
            <span class="market-scatter__identity"><strong>{{ item.symbol.toUpperCase() }}</strong><span>{{ item.product_name }}</span></span>
            <span class="market-scatter__metrics">
              <span :class="`market-scatter__price market-scatter__price--${priceTone(item)}`">{{ priceLabel(item) }}</span>
              <span class="market-scatter__oi">{{ openInterestLabel(item) }}</span>
            </span>
          </button>
        </div>
      </article>
    </div>
    <p v-else class="market-scatter__empty">暂无同时具备价格与 OI 变化的数据</p>
    <article
      v-if="neutralQuadrant.items.length"
      class="market-scatter__quadrant market-scatter__quadrant--neutral"
      data-testid="market-quadrant-neutral"
    >
      <header class="market-scatter__quadrant-heading"><h3>{{ neutralQuadrant.label }}</h3><span>{{ neutralQuadrant.items.length }}</span></header>
      <div class="market-scatter__items">
        <button
          v-for="item in neutralQuadrant.items"
          :key="item.symbol"
          class="market-scatter__item"
          :aria-label="`打开 ${item.symbol.toUpperCase()} ${item.product_name}`"
          @click="emit('open', item)"
        >
          <span class="market-scatter__identity"><strong>{{ item.symbol.toUpperCase() }}</strong><span>{{ item.product_name }}</span></span>
          <span class="market-scatter__metrics">
            <span :class="`market-scatter__price market-scatter__price--${priceTone(item)}`">{{ priceLabel(item) }}</span>
            <span class="market-scatter__oi">{{ openInterestLabel(item) }}</span>
          </span>
        </button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.market-scatter { padding: 16px; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-panel); }
.market-scatter > header > span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }.market-scatter h2 { margin: 3px 0 0; font-size: var(--gy-font-size-md); }
.market-scatter__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.market-scatter__quadrant { min-width: 0; border: .5px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-app); overflow: hidden; }.market-scatter__quadrant--neutral { margin-top: 10px; }
.market-scatter__quadrant-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border-bottom: .5px solid var(--gy-border); }.market-scatter__quadrant-heading h3 { margin: 0; font-size: var(--gy-font-size-sm); }.market-scatter__quadrant-heading span { color: var(--gy-text-muted); font-family: var(--gy-font-mono); font-size: var(--gy-font-size-xs); }
.market-scatter__items { display: grid; }.market-scatter__item { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 10px; border: 0; border-bottom: .5px solid var(--gy-border); background: transparent; color: var(--gy-text-primary); cursor: pointer; text-align: left; }.market-scatter__item:last-child { border-bottom: 0; }.market-scatter__item:hover { background: var(--gy-bg-panel); }
.market-scatter__identity { display: flex; min-width: 0; align-items: baseline; gap: 6px; }.market-scatter__identity strong { font-family: var(--gy-font-mono); font-size: var(--gy-font-size-sm); }.market-scatter__identity span { overflow: hidden; color: var(--gy-text-secondary); font-size: var(--gy-font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
.market-scatter__metrics { display: flex; flex: none; align-items: center; gap: 5px; font-family: var(--gy-font-mono); font-size: var(--gy-font-size-xs); white-space: nowrap; }.market-scatter__price { font-weight: 600; }.market-scatter__price--up { color: var(--gy-up); }.market-scatter__price--down { color: var(--gy-down); }.market-scatter__price--neutral, .market-scatter__oi { color: var(--gy-text-secondary); }.market-scatter__oi { padding: 2px 4px; border-radius: 3px; background: var(--gy-bg-panel); }
.market-scatter__empty { margin: 0; padding: 12px 10px; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
@media (max-width: 760px) { .market-scatter__grid { grid-template-columns: 1fr; }.market-scatter__item { padding-block: 8px; } }
</style>
