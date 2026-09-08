<script setup lang="ts">
import MarketStateIcon from './MarketStateIcon.vue'
</script>

<template>
  <section class="legend" aria-label="周期状态图例">
    <h2>周期状态</h2>
    <span><MarketStateIcon state="up" size="legend" />上行</span>
    <span><MarketStateIcon state="down" size="legend" />下行</span>
    <span><MarketStateIcon state="neutral" size="legend" />中性</span>
    <span><MarketStateIcon state="aligned" size="legend" />同向</span>
    <span><MarketStateIcon state="unavailable" size="legend" />数据不足</span>
    <small>仅表示已完成周期状态</small>
  </section>
</template>
