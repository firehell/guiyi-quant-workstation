<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { MarketHomeIconState } from '@/utils/marketHomeIcons'
import type { MarketHomeRow } from '@/utils/marketHomeViewModel'
import type { MarketHomeLiveDisplayRow } from '@/utils/marketHomeLiveView'

type DisplayRow = MarketHomeLiveDisplayRow<MarketHomeRow>
defineProps<{ rows: DisplayRow[]; liveStale: boolean }>()
defineEmits<{ open: [row: MarketHomeRow] }>()
const alignment = (value: string): MarketHomeIconState => value.startsWith('aligned') ? 'aligned' : value === 'unavailable' ? 'unavailable' : 'mixed'
const percentage = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(2)}%`
</script>

<template><section class="mobile-list" aria-label="移动端品种列表"><button v-for="row in rows" :key="row.symbol" @click="$emit('open',row)"><strong>{{row.symbol.toUpperCase()}} {{row.product_name}}</strong><span>{{ row.liveQuote ? (liveStale ? '断线保留价' : row.liveQuote.source === 'completed_1m' ? '最新 1m' : '历史收盘') : '日线收盘' }} {{row.close}} · {{ row.liveQuote ? '同合约较昨收' : '1d 涨跌幅' }} {{percentage(row.price_change_1d)}}</span><i><b>日 <MarketStateIcon :state="row.dailyState"/></b><b>周 <MarketStateIcon :state="row.weeklyState"/></b><b>同向 <MarketStateIcon :state="alignment(row.alignment)"/></b></i></button></section></template>

<style scoped>.mobile-list{display:none}@media(max-width:767px){.mobile-list{display:grid;gap:8px}.mobile-list button{display:grid;gap:6px;text-align:left;border:.5px solid var(--gy-border);border-radius:var(--gy-radius-md);background:var(--gy-bg-panel);padding:12px}.mobile-list i{display:flex;align-items:center;gap:8px;font-style:normal;font-size:var(--gy-font-size-xs)}.mobile-list b{display:inline-flex;align-items:center;gap:4px}.mobile-list .event{margin-left:auto}}</style>
