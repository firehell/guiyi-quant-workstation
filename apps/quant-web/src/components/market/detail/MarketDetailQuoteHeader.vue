<script setup lang="ts">
import { computed } from 'vue'

import type { MarketDetailHeaderModel } from '@/types/marketDetail'
import MarketDetailIcon from './MarketDetailIcon.vue'
import MarketFactsDisclosure from './MarketFactsDisclosure.vue'

const props = defineProps<{
  header: MarketDetailHeaderModel
  identityKey: string
}>()

const direction = computed(() => props.header.change === null ? 'neutral' : props.header.change > 0 ? 'up' : props.header.change < 0 ? 'down' : 'neutral')
const statusLabel = computed(() => ({ fresh: '数据正常', stale: '数据可能过时', unavailable: '数据不可用' })[props.header.freshness])

function number(value: number | null, digits = 2): string {
  return value === null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function integer(value: number | null): string {
  return value === null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}
</script>

<template>
  <section class="quote-header" data-detail-section="quote">
    <div class="quote-header__identity">
      <div>
        <p class="quote-header__eyebrow">{{ header.exchange }} · {{ header.sector }}</p>
        <h1>{{ header.productName }}</h1>
        <p>{{ header.displayContract || (header.seriesKind === 'continuous' ? '主连序列' : header.symbol.toUpperCase()) }}</p>
      </div>
      <span class="quote-header__status" :class="`quote-header__status--${header.freshness}`">
        <MarketDetailIcon :name="header.freshness === 'fresh' ? 'data' : 'warning'" :size="16" />
        {{ statusLabel }}
      </span>
    </div>

    <div class="quote-header__price" :class="`quote-header__price--${direction}`">
      <strong>{{ number(header.close) }}</strong>
      <span>{{ header.change === null ? '变动 —' : `${header.change >= 0 ? '+' : ''}${number(header.change)}` }}</span>
      <span>{{ header.pct === null ? '涨跌幅 —' : `${header.pct >= 0 ? '+' : ''}${number(header.pct)}%` }}</span>
    </div>
    <p class="quote-header__asof">截至 {{ header.asOf || '—' }}</p>

    <dl class="quote-header__facts">
      <div><dt>开</dt><dd>{{ number(header.open) }}</dd></div>
      <div><dt>高</dt><dd>{{ number(header.high) }}</dd></div>
      <div><dt>低</dt><dd>{{ number(header.low) }}</dd></div>
      <div><dt>成交量</dt><dd>{{ integer(header.volume) }}</dd></div>
      <div><dt>持仓量</dt><dd>{{ integer(header.openInterest) }}</dd></div>
    </dl>

    <MarketFactsDisclosure
      :identity-key="identityKey"
      :sections="header.extendedSections"
      :freshness="header.freshness"
    />
  </section>
</template>

<style scoped>
.quote-header { padding: var(--gy-space-5) 0; border-bottom: 1px solid var(--gy-border-subtle); }
.quote-header__identity { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gy-space-4); }
.quote-header__identity h1 { margin: var(--gy-space-1) 0; color: var(--gy-text-primary); font-size: var(--gy-font-size-2xl); }
.quote-header__identity p { margin: 0; color: var(--gy-text-muted); }
.quote-header__eyebrow { font-size: var(--gy-font-size-xs); }
.quote-header__status { display: inline-flex; align-items: center; gap: var(--gy-space-1); padding: var(--gy-space-1) var(--gy-space-2); border-radius: var(--gy-radius-pill); font-size: var(--gy-font-size-sm); white-space: nowrap; }
.quote-header__status--fresh { color: var(--gy-status-ok); background: var(--gy-status-ok-soft); }
.quote-header__status--stale { color: var(--gy-status-warning); background: var(--gy-status-warning-soft); }
.quote-header__status--unavailable { color: var(--gy-status-error); background: var(--gy-status-error-soft); }
.quote-header__price { display: flex; align-items: baseline; gap: var(--gy-space-3); margin-top: var(--gy-space-4); }
.quote-header__price strong { color: var(--gy-text-primary); font-family: var(--gy-font-mono); font-size: var(--gy-font-size-2xl); line-height: 1; }
.quote-header__price span { font-weight: 600; }
.quote-header__price--up span { color: var(--gy-up); }
.quote-header__price--down span { color: var(--gy-down); }
.quote-header__price--neutral span { color: var(--gy-text-muted); }
.quote-header__asof { margin: var(--gy-space-2) 0 var(--gy-space-4); color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.quote-header__facts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--gy-space-2); margin: 0; }
.quote-header__facts div { min-width: 0; padding: var(--gy-space-2) var(--gy-space-3); border-radius: var(--gy-radius-md); background: var(--gy-detail-section-bg); }
.quote-header__facts dt { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.quote-header__facts dd { margin: var(--gy-space-1) 0 0; color: var(--gy-text-primary); font-family: var(--gy-font-mono); }

@media (max-width: 640px) {
  .quote-header { padding-top: var(--gy-space-4); }
  .quote-header__price { flex-wrap: wrap; }
  .quote-header__price strong { flex-basis: 100%; font-size: var(--gy-font-size-2xl); }
  .quote-header__facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
