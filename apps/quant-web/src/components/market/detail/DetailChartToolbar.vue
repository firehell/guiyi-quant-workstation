<script setup lang="ts">
import { computed } from 'vue'
import ChartReferenceToolbar from './ChartReferenceToolbar.vue'
import { MARKET_FREQUENCIES, type MarketFrequency } from '../../../types/market.ts'
import type { MarketDetailIdentity } from '../../../types/marketDetail.ts'
const props = withDefaults(defineProps<{
  identity: MarketDetailIdentity
  frequencies?: readonly MarketFrequency[]
  targetPrice?: string | null
  absorbPrice?: string | null
  status?: string
}>(), { frequencies: () => MARKET_FREQUENCIES })
const emit = defineEmits<{ select: [frequency: MarketFrequency] }>()
const periods = computed(() => props.frequencies.filter(period => period !== '1m' || !['htdy', 'subing'].includes(props.identity.view)))
const label = (period: MarketFrequency) => period === '1d' ? '日线' : period === '1w' ? '周线' : period.replace('m', '分钟')
</script>
<template>
  <ChartReferenceToolbar :target-price="targetPrice" :absorb-price="absorbPrice" :status="status">
    <div class="newow-chart-frequency" role="group" aria-label="周期">
      <button v-for="period in periods" :key="period" type="button" :aria-pressed="identity.frequency === period"
        :class="{ 'is-active': identity.frequency === period }" @click="emit('select', period)">{{ label(period) }}</button>
    </div>
  </ChartReferenceToolbar>
</template>
