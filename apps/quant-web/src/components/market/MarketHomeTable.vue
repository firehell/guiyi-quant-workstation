<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { MarketHomeSort, MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'
import { marketHomeDirection, marketHomePercent, marketHomePrice, marketHomeRatio } from '@/utils/marketHomePresentation'
import { productSectorLabel } from '@/utils/productDirectory'
import type { MarketHomeLiveDisplayRow } from '@/utils/marketHomeLiveView'

type DisplayRow = MarketHomeLiveDisplayRow<MarketHomeRow>
const props = defineProps<{ rows: DisplayRow[]; compact: boolean; sort: MarketHomeSort; sortDirection: MarketHomeSortDirection; liveStale: boolean }>()
defineEmits<{ open: [row: MarketHomeRow]; sort: [column: MarketHomeSort] }>()
const ariaSort = (column: MarketHomeSort) => props.sort !== column ? 'none' : props.sortDirection === 'asc' ? 'ascending' : 'descending'
const sortGlyph = (column: MarketHomeSort) => props.sort !== column ? '↕' : props.sortDirection === 'asc' ? '↑' : '↓'
function quoteLabel(row: DisplayRow) {
  const quote = row.liveQuote
  if (!quote?.barEnd) return '日线收盘'
  const time = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(quote.barEnd))
  const contract = quote.physicalContract ?? '合约未知'
  if (props.liveStale) return `${contract} · 断线保留 · ${time}`
  if (quote.source === 'completed_1d') return `${contract} · 历史收盘 · ${time}`
  if (quote.phase === 'CLOSED' || quote.phase === 'BREAK') return `${contract} · 休市 · 1m ${time}`
  return `${contract} · 1m · ${time}`
}
</script>

<template>
  <div class="table-wrap" :class="{ 'table-wrap--compact': compact }">
    <table>
      <caption class="market-home-sr-only">{{ rows.some((row) => row.liveQuote) ? '最新已完成行情与完整周期指标' : '最近完整交易日收盘快照' }}</caption>
      <thead><tr>
        <th scope="col">品种</th>
        <th scope="col">板块</th>
        <th scope="col" :aria-sort="ariaSort('close')"><button type="button" @click="$emit('sort', 'close')">最新收盘 <span aria-hidden="true">{{ sortGlyph('close') }}</span></button></th>
        <th scope="col" :aria-sort="ariaSort('change')"><button type="button" @click="$emit('sort', 'change')">涨跌幅 <span aria-hidden="true">{{ sortGlyph('change') }}</span></button></th>
        <th scope="col" :aria-sort="ariaSort('volume')" title="最近完整日线收盘口径"><button type="button" @click="$emit('sort', 'volume')">日量比 <span aria-hidden="true">{{ sortGlyph('volume') }}</span></button></th>
        <th scope="col" :aria-sort="ariaSort('oi')" title="最近完整日线收盘口径"><button type="button" @click="$emit('sort', 'oi')">日增仓率 <span aria-hidden="true">{{ sortGlyph('oi') }}</span></button></th>
        <th scope="col">1d</th><th scope="col">1w</th><th scope="col">同向</th>
        <th scope="col"><span class="market-home-sr-only">详情</span></th>
      </tr></thead>
      <tbody><tr v-for="row in rows" :key="row.symbol" :data-symbol="row.symbol" tabindex="0" :aria-label="`${row.symbol.toUpperCase()} ${row.product_name}，按 Enter 进入品种复核`" @click="$emit('open', row)" @keyup.enter="$emit('open', row)">
        <th scope="row"><strong>{{ row.product_name }}</strong> <span class="product-code">{{ row.symbol.toUpperCase() }}</span></th>
        <td class="sector-label">{{ productSectorLabel(row.sector) }}</td>
        <td class="close-price" :class="marketHomeDirection(row.price_change_1d)"><strong>{{ marketHomePrice(row.close) }}</strong><small>{{ quoteLabel(row) }}</small></td>
        <td><span class="change-badge" :class="marketHomeDirection(row.price_change_1d)" :title="row.liveQuote ? '同物理合约较上一完整交易日收盘' : '完整日线 1d 涨跌幅'">{{ marketHomePercent(row.price_change_1d) }}</span></td>
        <td>{{ marketHomeRatio(row.volume_ratio20) }}</td>
        <td class="oi-change">{{ marketHomePercent(row.oi_change_1d) }}</td>
        <td><MarketStateIcon :state="row.dailyState" /></td>
        <td><MarketStateIcon :state="row.weeklyState" /></td>
        <td><span v-if="row.alignment === 'aligned-up' || row.alignment === 'aligned-down'" class="alignment"><MarketStateIcon state="aligned" /><MarketStateIcon :state="row.alignment === 'aligned-up' ? 'up' : 'down'" size="micro" /></span><MarketStateIcon v-else-if="row.alignment === 'unavailable'" state="unavailable" /><MarketStateIcon v-else state="mixed" /></td>
        <td class="detail-arrow" aria-hidden="true">›</td>
      </tr></tbody>
    </table>
  </div>
</template>
