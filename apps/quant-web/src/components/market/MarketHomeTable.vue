<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { MarketHomeAvailability, MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { MarketHomeSort, MarketHomeSortDirection } from '@/utils/marketHomeWorkspace'
import { marketHomeDirection, marketHomePercent, marketHomePrice, marketHomeRatio } from '@/utils/marketHomePresentation'
import { productSectorLabel } from '@/utils/productDirectory'

const props = defineProps<{ rows: MarketHomeRow[]; eventAvailability: MarketHomeAvailability; compact: boolean; sort: MarketHomeSort; sortDirection: MarketHomeSortDirection }>()
defineEmits<{ open: [row: MarketHomeRow]; sort: [column: MarketHomeSort] }>()
const ariaSort = (column: MarketHomeSort) => props.sort !== column ? 'none' : props.sortDirection === 'asc' ? 'ascending' : 'descending'
const sortGlyph = (column: MarketHomeSort) => props.sort !== column ? '↕' : props.sortDirection === 'asc' ? '↑' : '↓'
</script>

<template>
  <div class="table-wrap" :class="{ 'table-wrap--compact': compact }">
    <table>
      <caption class="market-home-sr-only">最近完整交易日收盘快照</caption>
      <thead><tr>
        <th scope="col">品种</th>
        <th scope="col">板块</th>
        <th scope="col" :aria-sort="ariaSort('close')"><button type="button" @click="$emit('sort', 'close')">最新收盘 <span aria-hidden="true">{{ sortGlyph('close') }}</span></button></th>
        <th scope="col" :aria-sort="ariaSort('change')"><button type="button" @click="$emit('sort', 'change')">1d 涨跌幅 <span aria-hidden="true">{{ sortGlyph('change') }}</span></button></th>
        <th scope="col" title="尚未接入同身份目标参考价">目标参考价</th>
        <th scope="col" :aria-sort="ariaSort('volume')"><button type="button" @click="$emit('sort', 'volume')">量比 <span aria-hidden="true">{{ sortGlyph('volume') }}</span></button></th>
        <th scope="col" :aria-sort="ariaSort('oi')"><button type="button" @click="$emit('sort', 'oi')">1d 增仓率 <span aria-hidden="true">{{ sortGlyph('oi') }}</span></button></th>
        <th scope="col">1d</th><th scope="col">1w</th><th scope="col">同向</th>
        <th scope="col"><span class="market-home-sr-only">详情</span></th>
      </tr></thead>
      <tbody><tr v-for="row in rows" :key="row.symbol" :data-symbol="row.symbol" tabindex="0" :aria-label="`${row.symbol.toUpperCase()} ${row.product_name}，按 Enter 进入品种复核`" @click="$emit('open', row)" @keyup.enter="$emit('open', row)">
        <th scope="row"><strong>{{ row.product_name }}</strong> <span class="product-code">{{ row.symbol.toUpperCase() }}</span></th>
        <td class="sector-label">{{ productSectorLabel(row.sector) }}</td>
        <td class="close-price" :class="marketHomeDirection(row.price_change_1d)">{{ marketHomePrice(row.close) }}</td>
        <td><span class="change-badge" :class="marketHomeDirection(row.price_change_1d)">{{ marketHomePercent(row.price_change_1d) }}</span></td>
        <td class="target-unavailable"><span title="尚未接入同身份目标参考价">—</span></td>
        <td>{{ marketHomeRatio(row.volume_ratio20) }}</td>
        <td class="oi-change">{{ marketHomePercent(row.oi_change_1d) }}</td>
        <td><MarketStateIcon :state="row.dailyState" /></td>
        <td><MarketStateIcon :state="row.weeklyState" /></td>
        <td><span v-if="row.alignment === 'aligned-up' || row.alignment === 'aligned-down'" class="alignment"><MarketStateIcon state="aligned" /><MarketStateIcon :state="row.alignment === 'aligned-up' ? 'up' : 'down'" size="micro" /></span><MarketStateIcon v-else-if="row.alignment === 'unavailable'" state="unavailable" /><span v-else title="日周未同向">—</span></td>
        <td class="detail-arrow" aria-hidden="true">›</td>
      </tr></tbody>
    </table>
  </div>
</template>
