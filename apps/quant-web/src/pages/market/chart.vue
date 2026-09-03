<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import LegacyMarketChart from './LegacyMarketChart.vue'
import MarketDetailPage from './MarketDetailPage.vue'

const route = useRoute()
const hasExplicitView = computed(() => route.query.view !== undefined)
</script>

<template>
  <MarketDetailPage v-if="hasExplicitView" :key="route.fullPath" />
  <LegacyMarketChart v-else />
</template>
