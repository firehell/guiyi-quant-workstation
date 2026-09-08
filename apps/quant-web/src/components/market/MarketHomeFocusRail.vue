<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
import type { AlertEvent } from '@/types/market'
import { alertEventHomeIconState, alertEventHomeResultLabel, alertEventRuleShortLabel } from '@/utils/alertRules'
import { formatChartTimeInShanghai } from '@/utils/barTime'
defineProps<{ availability: string; events: AlertEvent[]; collapsed: boolean }>()
defineEmits<{ open: [event: AlertEvent]; 'update:collapsed': [value: boolean] }>()
</script>

<template>
  <aside v-if="!collapsed" id="market-home-observations" class="rail" aria-label="研究观察">
    <p v-if="availability === 'unavailable'">当前 Alert Event 暂不可用；不能据此判断本时段无研究观察。</p>
    <p v-else-if="!events.length">当前交易日暂无正式研究观察 Event</p>
    <div v-else class="market-home-event-list">
      <button v-for="event in events" :key="event.id" type="button" @click="$emit('open', event)">
        <MarketStateIcon :state="alertEventHomeIconState(event)" size="micro" />
        <span><b>{{ event.symbol.toUpperCase() }} · {{ alertEventRuleShortLabel(event) }} · {{ alertEventHomeResultLabel(event) }} · {{ event.frequency }}</b>
          <small>{{ event.contract }} · bar {{ formatChartTimeInShanghai(event.bar_end) }}<br>detected {{ event.detected_at }} · transport attempted {{ event.notification_attempted_at ?? '—' }}</small>
        </span>
      </button>
    </div>
  </aside>
</template>
