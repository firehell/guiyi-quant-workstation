<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { MarketHomeIconState } from '@/utils/marketHomeIcons'
import type { MarketHomeAvailability, MarketHomeRow } from '@/utils/marketHomeViewModel'

const props = defineProps<{ rows: MarketHomeRow[]; eventAvailability: MarketHomeAvailability }>()
defineEmits<{ open: [row: MarketHomeRow] }>()
const alignment = (value: string): MarketHomeIconState | null => value.startsWith('aligned') ? 'aligned' : value === 'neutral' ? 'neutral' : value === 'unavailable' ? 'unavailable' : null
const percentage = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(2)}%`
const eventState = (row: MarketHomeRow): MarketHomeIconState | null => props.eventAvailability === 'unavailable' ? 'unavailable' : !row.event ? null : row.event.result_codes.length === 2 ? 'aligned' : row.event.result_codes[0] === 'buy' ? 'up' : 'down'
const eventLabel = (row: MarketHomeRow) => props.eventAvailability === 'unavailable' ? 'Event 不可用' : !row.event ? '—' : row.event.result_codes.length === 2 ? '双向观察' : row.event.result_codes[0] === 'buy' ? '买观察' : '卖观察'
</script>

<template><section class="mobile-list" aria-label="移动端品种列表"><button v-for="row in rows" :key="row.symbol" @click="$emit('open',row)"><strong>{{row.symbol.toUpperCase()}} {{row.product_name}}</strong><span>收盘 {{row.close}} · 1D {{percentage(row.price_change_1d)}}</span><i><b>日 <MarketStateIcon :state="row.dailyState"/></b><b>周 <MarketStateIcon :state="row.weeklyState"/></b><b>同向 <MarketStateIcon v-if="alignment(row.alignment)" :state="alignment(row.alignment)!"/><span v-else>未同向</span></b><b class="htdy">HTDY <template v-if="eventState(row)"><MarketStateIcon :state="eventState(row)!" size="micro"/></template>{{eventLabel(row)}}</b></i></button></section></template>

<style scoped>.mobile-list{display:none}@media(max-width:767px){.mobile-list{display:grid;gap:8px}.mobile-list button{display:grid;gap:6px;text-align:left;border:.5px solid var(--gy-border);border-radius:var(--gy-radius-md);background:var(--gy-bg-panel);padding:12px}.mobile-list i{display:flex;align-items:center;gap:8px;font-style:normal;font-size:var(--gy-font-size-xs)}.mobile-list b{display:inline-flex;align-items:center;gap:4px}.mobile-list .htdy{margin-left:auto}}</style>
