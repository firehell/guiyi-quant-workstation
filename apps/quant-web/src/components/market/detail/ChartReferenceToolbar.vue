<script setup lang="ts">
import { newowReferencePrice } from '../../../utils/newowPagePresentation.ts'
withDefaults(defineProps<{ targetPrice?: string | null; absorbPrice?: string | null; status?: string }>(), { targetPrice: null, absorbPrice: null, status: '不可用' })
</script>
<template>
  <div class="chart-reference-toolbar newow-product-chart-stage__reference-prices" aria-label="主图参考价格">
    <span class="is-target" :title="targetPrice == null ? status : '牛哇页面目标参考，非委托价格'">目标价: {{ newowReferencePrice(targetPrice) }}<small v-if="targetPrice == null"> · {{ status }}</small></span>
    <span class="is-absorb" :title="absorbPrice == null ? status : '牛哇页面吸筹参考，非委托价格'">吸筹价: {{ newowReferencePrice(absorbPrice) }}<small v-if="absorbPrice == null"> · {{ status }}</small></span>
    <div class="newow-product-chart-stage__reference-controls"><slot /></div>
  </div>
</template>
<style scoped>
.chart-reference-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;min-width:0;min-height:36px;box-sizing:border-box;padding:4px 12px;border-bottom:1px solid #eef0f3;background:#f4f5f8;font-size:11px;font-weight:600}
.is-target{color:#ff6935}.is-absorb{color:#34c759}small{font-weight:400}
.newow-product-chart-stage__reference-controls{margin-left:auto;display:flex;align-items:center;gap:8px;min-width:0;max-width:100%}
.chart-reference-toolbar :deep(.newow-chart-frequency){display:flex;align-items:center;gap:0;padding:2px;border-radius:6px;background:#eeeeef;max-width:100%;overflow-x:auto}
.chart-reference-toolbar :deep(.newow-chart-frequency button){min-height:22px;height:22px;border:0;border-radius:4px;padding:0 8px;color:#666;background:transparent;font-size:11px;line-height:22px;font-weight:500;cursor:pointer;white-space:nowrap}
.chart-reference-toolbar :deep(.newow-chart-frequency button:hover){color:#333}
.chart-reference-toolbar :deep(.newow-chart-frequency button.is-active){color:#222;background:#fff;box-shadow:0 1px 3px #00000012}
</style>
