<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { MarketHomeIconState } from '@/utils/marketHomeIcons'
import type { AlertEvent } from '@/types/market'
defineProps<{ availability: string; events: AlertEvent[]; collapsed: boolean }>()
defineEmits<{ open: [event: AlertEvent]; 'update:collapsed': [value: boolean] }>()
const label = (event: AlertEvent) => event.result_codes.length === 2 ? '双向观察' : event.result_codes[0] === 'buy' ? '买观察' : '卖观察'
const state = (event: AlertEvent): MarketHomeIconState => event.result_codes.length === 2 ? 'aligned' : event.result_codes[0] === 'buy' ? 'up' : 'down'
</script>

<template><aside class="rail"><header><h2>HTDY Focus</h2><button class="collapse" @click="$emit('update:collapsed',!collapsed)">{{collapsed?'展开':'收起'}}</button></header><template v-if="!collapsed"><p v-if="availability==='unavailable'">HTDY 当前 Event 暂不可用；不能据此判断本时段无观察。</p><p v-else-if="!events.length">当前交易日暂无 HTDY 正式观察 Event</p><template v-else><button v-for="event in events" :key="event.id" @click="$emit('open',event)"><MarketStateIcon :state="state(event)" size="micro"/><span><b>{{event.symbol.toUpperCase()}} · {{label(event)}} · {{event.frequency}}</b><small>{{event.rule_code}} · {{event.contract}}<br>bar {{event.bar_end}} · detected {{event.detected_at}}<br>transport attempted {{event.notification_attempted_at??'—'}}</small></span></button></template></template></aside></template>

<style scoped>.rail{border:.5px solid var(--gy-border);border-radius:var(--gy-radius-lg);padding:12px;background:var(--gy-bg-panel)}header{display:flex;justify-content:space-between;align-items:center}h2{font-size:var(--gy-font-size-md);margin:0 0 8px}.collapse{width:auto;border:0;padding:0;color:var(--gy-accent);background:transparent;cursor:pointer}.rail button:not(.collapse){display:flex;width:100%;align-items:center;gap:8px;text-align:left;border:0;border-top:.5px solid var(--gy-border);padding:9px 0;background:transparent;cursor:pointer}.rail small{display:block;margin-top:3px;color:var(--gy-text-muted);font-size:var(--gy-font-size-xs)}</style>
