<script setup lang="ts">
import type { NewowCupWitness } from '@/types/newowProduct'
import { formatMarketDecimal } from '@/utils/marketDisplay'
import { shortNewowTime } from '@/utils/newowDetailPresentation'
import { projectNewowCupPoints } from './newowCupFactsPresentation'

defineProps<{ witnesses: readonly NewowCupWitness[]; physicalContract: string; segmentId: string }>()
const facts = (witness: NewowCupWitness) => [witness.left_rim, witness.bottom, witness.right_rim, witness.handle_extreme]
const points = (witness: NewowCupWitness) => projectNewowCupPoints(witness)
</script>

<template>
  <section class="newow-cup-facts" aria-label="归一杯柄候选事实">
    <header><h3>归一杯柄候选</h3><span>{{ physicalContract }} · {{ segmentId }}</span></header>
    <p>已确认结构示意，非完整 K 线；非牛哇私有原公式。</p>
    <p v-if="witnesses.length === 0" role="status">当前区段没有已确认杯柄事实；这不表示策略看空。</p>
    <article v-for="witness in witnesses" :key="witness.witness_id" class="newow-cup-facts__card">
      <svg viewBox="0 0 240 70" role="img" :aria-label="`杯柄候选 ${witness.candidate_id} 的四个已确认拐点`">
        <polyline v-if="points(witness).every(point => point.available)" :points="points(witness).map(point => `${point.x},${point.y}`).join(' ')" fill="none" stroke="#ff6b2c" stroke-width="3" />
        <text v-else x="12" y="36">拐点价格不可用</text>
      </svg>
      <dl><div v-for="(point, index) in facts(witness)" :key="point.kind"><dt>{{ ['左杯沿', '杯底', '右杯沿', '柄极值'][index] }}</dt><dd>{{ formatMarketDecimal(point.price) }} · {{ shortNewowTime(point.pivot_at) }}</dd><small>确认 {{ shortNewowTime(point.confirmed_at) }}</small></div></dl>
      <p>Pivot {{ formatMarketDecimal(witness.pivot_price) }} · 确认 {{ shortNewowTime(witness.confirmed_at) }} · score {{ witness.score }}</p>
      <details><summary>评分与可审计事实</summary><p>{{ witness.candidate_id }} · {{ witness.witness_id }}</p><p>{{ witness.score_breakdown.map(([key, value]) => `${key}: ${value}`).join(' / ') || '无评分拆分' }}</p><p>{{ witness.formula_version }} · {{ witness.profile_identity }}</p></details>
    </article>
  </section>
</template>

<style scoped>
.newow-cup-facts { display:grid; gap:12px; }.newow-cup-facts header { display:flex; align-items:center; justify-content:space-between; gap:12px; }.newow-cup-facts h3,.newow-cup-facts p { margin:0; }.newow-cup-facts > p { color:#667085; }.newow-cup-facts__card { padding:12px; border:1px solid #f0d7c8; border-radius:10px; background:#fffaf6; }.newow-cup-facts svg { width:100%; height:70px; }.newow-cup-facts dl { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }.newow-cup-facts dt { color:#667085; font-size:12px; }.newow-cup-facts dd { margin:3px 0; font-variant-numeric:tabular-nums; } small { color:#667085; }
</style>
