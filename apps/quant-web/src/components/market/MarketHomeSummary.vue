<script setup lang="ts">
import type { MarketHomeLocalFilter } from '@/utils/marketHomeWorkspace'
defineProps<{ summary: { price_up_count: number; price_down_count: number; price_flat_count: number; aligned_up_count: number; aligned_down_count: number } | null; active: MarketHomeLocalFilter }>()
defineEmits<{ filter: [kind: MarketHomeLocalFilter] }>()
</script>
<template><section v-if="summary" class="summary" aria-label="本地概览筛选"><button :class="{active:active==='up'}" @click="$emit('filter','up')">上涨 {{summary.price_up_count}}</button><button :class="{active:active==='down'}" @click="$emit('filter','down')">下跌 {{summary.price_down_count}}</button><button :class="{active:active==='aligned'}" @click="$emit('filter','aligned')">同向 {{summary.aligned_up_count+summary.aligned_down_count}}</button><button v-if="active!=='all'" @click="$emit('filter','all')">清除筛选</button></section></template>
<style scoped>.summary{display:flex;gap:8px}.summary button{border:.5px solid var(--gy-border);border-radius:var(--gy-radius-md);background:var(--gy-bg-panel);padding:10px 14px;cursor:pointer}</style>
