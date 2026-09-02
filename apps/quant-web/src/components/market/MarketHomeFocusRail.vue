<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { MarketHomeIconState } from '@/utils/marketHomeIcons'
import type { AlertEvent } from '@/types/market'
import {
  alertEventDirectionalTone,
  alertEventHomeResultLabel,
  alertEventRuleShortLabel,
} from '@/utils/alertRules'
import { formatChartTimeInShanghai } from '@/utils/barTime'
defineProps<{ availability: string; events: AlertEvent[]; collapsed: boolean }>()
defineEmits<{ open: [event: AlertEvent]; 'update:collapsed': [value: boolean] }>()
const label = (event: AlertEvent) => alertEventHomeResultLabel(event)
const state = (event: AlertEvent): MarketHomeIconState => {
  const direction = alertEventDirectionalTone(event, event.result_codes)
  if (direction === 'buy') return 'up'
  if (direction === 'sell') return 'down'
  return event.result_codes.length === 2 ? 'aligned' : 'neutral'
}
const barTime = (event: AlertEvent) => formatChartTimeInShanghai(event.bar_end)
</script>

<template><aside class="rail"><header><h2>观察 Focus</h2><button class="collapse" @click="$emit('update:collapsed',!collapsed)">{{collapsed?'展开':'收起'}}</button></header><template v-if="!collapsed"><p v-if="availability==='unavailable'">当前 Alert Event 暂不可用；不能据此判断本时段无研究观察。</p><p v-else-if="!events.length">当前交易日暂无正式研究观察 Event</p><template v-else><button v-for="event in events" :key="event.id" @click="$emit('open',event)"><MarketStateIcon :state="state(event)" size="micro"/><span><b>{{event.symbol.toUpperCase()}} · {{alertEventRuleShortLabel(event)}} · {{label(event)}} · {{event.frequency}}</b><small>{{event.contract}}<br>bar {{barTime(event)}} · detected {{event.detected_at}}<br>transport attempted {{event.notification_attempted_at??'—'}}</small></span></button></template></template></aside></template>

<style scoped>.rail{border:.5px solid var(--gy-border);border-radius:var(--gy-radius-lg);padding:12px;background:var(--gy-bg-panel)}header{display:flex;justify-content:space-between;align-items:center}h2{font-size:var(--gy-font-size-md);margin:0 0 8px}.collapse{width:auto;border:0;padding:0;color:var(--gy-accent);background:transparent;cursor:pointer}.rail button:not(.collapse){display:flex;width:100%;align-items:center;gap:8px;text-align:left;border:0;border-top:.5px solid var(--gy-border);padding:9px 0;background:transparent;cursor:pointer}.rail small{display:block;margin-top:3px;color:var(--gy-text-muted);font-size:var(--gy-font-size-xs)}</style>
