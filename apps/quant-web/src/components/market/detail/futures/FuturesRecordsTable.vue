<script setup lang="ts">
import type { FrozenRecord } from '@/types/newowFutures'
import { futuresTableValue,knownFuturesReason,type FuturesColumn } from '@/utils/newowFuturesPresentation'
defineProps<{items:FrozenRecord[];columns:FuturesColumn[]}>()
</script>
<template>
  <div class="futures-record-table"><table v-if="items.length"><thead><tr><th v-for="column in columns" :key="column.key">{{ column.label }}</th></tr></thead><tbody><tr v-for="(item,index) in items" :key="String(item.trade_id ?? item.reference_trade_id ?? item.action_id ?? item.decision_id ?? index)"><td v-for="column in columns" :key="column.key">
    <span :title="typeof item[column.key]==='string'?String(item[column.key]):undefined">{{ futuresTableValue(item,column) }}</span>
    <details v-if="column.kind==='reason' && item[column.key] && !knownFuturesReason(item[column.key])"><summary>原因代码</summary>{{ item[column.key] }}</details>
  </td></tr></tbody></table><p v-else>该结果没有此类记录。</p></div>
</template>
<style scoped>.futures-record-table{overflow:auto;max-height:420px}.futures-record-table table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}.futures-record-table th,.futures-record-table td{padding:10px 12px;border-bottom:1px solid var(--gy-border-subtle);text-align:left;max-width:320px;overflow:hidden;text-overflow:ellipsis}.futures-record-table th{color:var(--gy-text-muted);font-weight:500}.futures-record-table details{font-size:11px;white-space:normal;overflow-wrap:anywhere}.futures-record-table summary{cursor:pointer}.futures-record-table p{font-size:13px;color:var(--gy-text-muted)}</style>
