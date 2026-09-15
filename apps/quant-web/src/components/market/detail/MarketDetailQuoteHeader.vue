<script setup lang="ts">
import { computed } from 'vue'

import { priceDirection } from '@/utils/newowDetailPresentation'
import {
  formatMarketNumber,
  formatMarketTime,
  marketChangeBasisLabel,
  marketQuoteBasisLabel,
  quoteAvailabilityLabel,
} from '@/utils/marketDisplay'
import type { MarketDetailHeaderModel } from '@/types/marketDetail'
import MarketDetailIcon from './MarketDetailIcon.vue'
import MarketFactsDisclosure from './MarketFactsDisclosure.vue'

const props = defineProps<{
  header: MarketDetailHeaderModel
  unified?: boolean
  newow?: boolean
  identityKey: string
}>()

const direction = computed(() => priceDirection(props.header.change))
const statusLabel = computed(() => quoteAvailabilityLabel(props.header.freshness, Boolean(props.header.afterMarketFailed)))
const displayFrequency = computed(() => props.newow ? '1d' as const : props.header.frequency)
const quoteBasis = computed(() => marketQuoteBasisLabel(displayFrequency.value, Boolean(props.newow)))
const changeBasis = computed(() => marketChangeBasisLabel(displayFrequency.value, Boolean(props.newow)))
const asOfText = computed(() => formatMarketTime(props.header.asOf, displayFrequency.value, props.header.tradingDay))

function number(value: number | null, digits = 2): string {
  return formatMarketNumber(value, digits)
}

function integer(value: number | null): string {
  return value === null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}
</script>

<template>
  <section class="quote-header" :class="{ 'quote-header--unified': unified }" data-detail-section="quote">
    <div class="quote-header__primary">
      <div class="quote-header__price" :class="`quote-header__price--${direction}`">
        <strong>{{ number(header.close) }}</strong>
        <span>{{ header.change === null ? `${changeBasis} —` : `${changeBasis} ${header.change >= 0 ? '+' : ''}${number(header.change)}` }}</span>
        <span>{{ header.pct === null ? '比例 —' : `${header.pct >= 0 ? '+' : ''}${number(header.pct)}%` }}</span>
      </div>
      <span class="quote-header__status" :class="`quote-header__status--${header.afterMarketFailed ? 'stale' : header.freshness}`">
        <MarketDetailIcon :name="!header.afterMarketFailed && header.freshness === 'fresh' ? 'data' : 'warning'" :size="16" />
        {{ statusLabel }}
      </span>
    </div>
    <div class="quote-header__meta">
      <p class="quote-header__asof" :title="header.asOf ?? undefined">{{ quoteBasis }} · {{ newow ? '非实时 · ' : '' }}截至 {{ asOfText }}</p>
      <div class="quote-header__facts-row">
        <p class="quote-header__facts-label">OHLCV · {{ quoteBasis }}</p>
        <dl class="quote-header__facts">
          <div><dt>开</dt><dd>{{ number(header.open) }}</dd></div>
          <div><dt>高</dt><dd>{{ number(header.high) }}</dd></div>
          <div><dt>低</dt><dd>{{ number(header.low) }}</dd></div>
          <div><dt>成交量</dt><dd>{{ integer(header.volume) }}</dd></div>
          <div><dt>持仓量</dt><dd>{{ integer(header.openInterest) }}</dd></div>
        </dl>
      </div>
    </div>

    <MarketFactsDisclosure
      v-if="!newow"
      :identity-key="identityKey"
      :sections="header.extendedSections"
      :freshness="header.freshness"
      :after-market-failed="header.afterMarketFailed"
    />
  </section>
</template>

<style scoped>
.quote-header { padding: var(--gy-space-3) 0; border-bottom: 1px solid var(--gy-border-subtle); }
.quote-header__primary { display: flex; align-items: center; justify-content: space-between; gap: var(--gy-space-3); }
.quote-header__status { display: inline-flex; align-items: center; gap: var(--gy-space-1); padding: var(--gy-space-1) var(--gy-space-2); border-radius: var(--gy-radius-pill); font-size: var(--gy-font-size-sm); white-space: nowrap; }
.quote-header__status--fresh { color: var(--gy-status-ok); background: var(--gy-status-ok-soft); }
.quote-header__status--stale { color: var(--gy-status-warning); background: var(--gy-status-warning-soft); }
.quote-header__status--unavailable { color: var(--gy-status-error); background: var(--gy-status-error-soft); }
.quote-header__price { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--gy-space-2) var(--gy-space-3); }
.quote-header__price strong { color: var(--gy-text-primary); font-family: var(--gy-font-mono); font-size: var(--gy-font-size-2xl); line-height: 1; }
.quote-header__price span { font-weight: 600; }
.quote-header__price--up span { color: var(--gy-up); }
.quote-header__price--down span { color: var(--gy-down); }
.quote-header__price--neutral span { color: var(--gy-text-muted); }
.quote-header__asof { margin: var(--gy-space-1) 0 var(--gy-space-2); color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.quote-header__facts-label { margin: 0 0 var(--gy-space-1); color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.quote-header__meta { display: grid; gap: var(--gy-space-2); }
.quote-header__facts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--gy-space-2); margin: 0; }
.quote-header__facts div { min-width: 0; padding: var(--gy-space-2) var(--gy-space-3); border-radius: var(--gy-radius-md); background: var(--gy-detail-section-bg); }
.quote-header__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.quote-header__facts dd { margin: var(--gy-space-1) 0 0; color: var(--gy-text-primary); font-family: var(--gy-font-mono); }

@media (max-width: 640px) {
  .quote-header { padding-top: var(--gy-space-2); }
  .quote-header__primary { align-items: flex-start; }
  .quote-header__price { flex-wrap: wrap; }
  .quote-header__price strong { flex-basis: 100%; font-size: var(--gy-font-size-2xl); }
  .quote-header__facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
