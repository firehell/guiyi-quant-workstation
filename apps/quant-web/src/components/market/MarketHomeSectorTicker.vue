<script setup lang="ts">
import { productSectorLabel } from '@/utils/productDirectory'
import type { MarketHomeOverviewResponse } from '@/types/market'
defineProps<{ sectors: MarketHomeOverviewResponse['sectors']; active: number | null; selected: string }>()
defineEmits<{ select: [sector: string] }>()
</script>

<template>
  <section class="market-home-sectors">
    <h2>品种板块</h2>
    <nav class="ticker" aria-label="品种板块">
      <button type="button" :aria-pressed="!selected" @click="$emit('select', '')">全部 <span>{{ active ?? '—' }}</span></button>
      <button v-for="item in sectors" :key="item.sector" type="button" :aria-pressed="selected === item.sector" @click="$emit('select', selected === item.sector ? '' : item.sector)">
        {{ productSectorLabel(item.sector) }} <span>{{ item.active_count }}</span>
      </button>
    </nav>
  </section>
</template>
