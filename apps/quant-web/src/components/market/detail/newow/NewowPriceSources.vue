<script setup lang="ts">
import type { PriceSourceRow } from '@/utils/newowPriceSources'
import { newowReferencePrice } from '@/utils/newowPagePresentation'
import { formatBeijingInstant } from '@/utils/marketDisplay'
defineProps<{ rows: PriceSourceRow[]; backgroundLabel?: string; guardStatus?: string; snapshotNote?: string }>()
const frequency = (value: string) => ({'1d':'日线','1w':'周线','60m':'60分钟','5m':'5分钟','15m':'15分钟','30m':'30分钟','1M':'月线'}[value] ?? value)
</script>
<template>
  <section class="price-sources-wrapper">
  <p v-if="snapshotNote" class="source-conflict" role="status">{{ snapshotNote }}</p>
  <p v-for="item in rows.filter(row => !row.available && row.reason !== '来源信息不可用')" :key="item.label" class="source-conflict" role="status">{{ item.label }} · {{ item.reason }}</p>
  <details class="price-sources">
    <summary>详情与口径 · 目标／吸筹来源<span v-if="backgroundLabel"> · {{ backgroundLabel }}</span><span v-if="rows.some(row => !row.available)"> · 来源信息不可用</span></summary>
    <p>期货价格来源与公开选择规则分别验证；原站私有价格逐值一致未证明。page_parity=true仅表示页面复刻用途，非私有输入一致证明或可执行指令。</p>
    <p v-if="guardStatus">共享选择使用1.005升级缓冲；周状态卡目标优先共享结果，缺失才用周HHV10；吸筹独立使用周LLV10。实际命中分支见下方。守卫状态 {{ guardStatus }}；昨收缺失不使用结算价替代。</p>
    <div v-for="item in rows" :key="item.label" class="price-source">
      <strong>{{ item.label }}</strong>
      <p v-if="!item.available" role="status">{{ item.reason }}</p>
      <template v-else-if="item.source">
        <p>显示 {{ newowReferencePrice(item.source.display_value) }} · 原始 {{ item.source.raw }} · {{ frequency(item.source.frequency) }} · Bar {{ formatBeijingInstant(item.source.bar_end) }}</p>
        <p v-if="item.label.endsWith('吸筹') && item.source.support_cap_applied !== undefined">吸筹现价上限 {{ item.source.support_cap_applied ? '已应用' : '未应用' }} · 原始与显示值保持分开</p>
        <p>物理合约 {{ item.source.physical_contract }} · Segment {{ item.source.segment_id }} · 计算段 {{ item.source.calculation_segment_id }}</p>
        <p>来源 {{ item.source.source_category }} · 分支 {{ item.source.branch }} · 公式 {{ item.source.formula_version }}</p>
        <p>截至 {{ formatBeijingInstant(item.source.as_of) }}<span v-if="item.source.input_sha256"> · 输入 {{ item.source.input_sha256 }}</span></p>
      </template>
    </div>
  </details>
  </section>
</template>
<style scoped>
.source-conflict{font-size:11px;color:#b88134;margin:4px 10px;overflow-wrap:anywhere}.price-sources{font-size:11px;line-height:1.6;color:#8e8e93;padding:8px 10px;overflow-wrap:anywhere;min-width:0}.price-sources summary{cursor:pointer}.price-sources p{margin:4px 0}.price-source{padding:6px 0;border-top:1px solid #eee}.price-source strong{color:#68686d;font-weight:500}
</style>
