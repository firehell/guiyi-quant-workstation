<script setup lang="ts">
import type { deriveBasisDecision } from '@/utils/newowBasisDecision'
import { computed, ref, watch, useId } from 'vue'
import type { NewowDecisionV2 } from '@/types/newowDecisionV2'
import { buildStatusCard } from '@/utils/newowStatusCardPresentation'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
import { decisionFactAge } from '@/utils/newowDecisionV2Presentation'
const props=defineProps<{ decision:NewowDecisionV2|null; strategy:string; loading:boolean; error:string; background?:boolean; basis?:'week'|'day'; dominant?:'trend'|'oscillation'|null; basisDecision?:ReturnType<typeof deriveBasisDecision> }>()
const emit=defineEmits<{retry:[]}>()
const bodyId=useId(), explanationId=useId()
function preference() { try { return typeof localStorage!=='undefined'&&localStorage.getItem('guiyi_newow_status_card_collapsed')==='1' } catch { return false } }
const collapsed=ref(preference()), expanded=ref(false)
const card=computed(()=>buildStatusCard(props.decision,props.strategy,props.basisDecision ?? undefined))
const color=computed(()=>props.basisDecision?.stance.color ?? ({bullish:'#ff3b30',cautious:'#ff9500',warning:'#ff6b35',bearish:'#34c759',unknown:'#8e8e93'}[card.value.risk]))
function toggle() { collapsed.value=!collapsed.value; try { localStorage.setItem('guiyi_newow_status_card_collapsed',collapsed.value?'1':'0') } catch { /* restricted storage: presentation still works */ } }
watch(()=>[props.strategy,props.decision?.cdv2.as_of],()=>{expanded.value=false})
</script>
<template>
 <section class="newow-status-card" :aria-label="strategy==='oscillation'?'周日小时状态摘要':'日周状态摘要'" :data-risk="card.risk" :style="{ '--status-color':color }">
  <button type="button" class="newow-status-card__header" :aria-expanded="!collapsed" :aria-controls="bodyId" :aria-label="collapsed?'展开状态摘要':'收起状态摘要'" @click="toggle">
   <span v-if="background">日周背景</span>
   <strong>{{ loading?'状态读取中':card.name }}</strong>
   <span class="newow-status-card__tag" :data-state="card.week.state">周:{{ card.week.label }}</span>
   <span class="newow-status-card__tag" :data-state="card.day.state">日:{{ card.day.label }}</span>
   <span class="newow-status-card__tag" :data-state="card.hour.state">时:{{ card.hour.label }}</span>
   <span class="newow-status-card__risk"><i aria-hidden="true" />{{ card.riskLabel }}</span>
   <span class="newow-status-card__exposure">建议仓位 {{ card.exposure }} <small>参考强度</small></span>
   <span class="newow-status-card__arrow" aria-hidden="true" :class="{collapsed}">▾</span>
  </button>
  <div v-show="!collapsed" :id="bodyId" class="newow-status-card__body">
   <p v-if="loading" role="status">正在读取同一快照的已完成日线、周线、60分钟…</p>
   <p v-else-if="error" role="alert">{{ error }} <button class="newow-status-card__retry" type="button" @click="emit('retry')">重试</button></p>
   <template v-else>
    <p v-if="card.matrixLabel">{{ card.matrixLabel }} · 观察粒度 {{ card.granularity }}</p>
    <p class="newow-status-card__advice">{{ card.advice }}</p>
    <template v-if="card.progress">
     <div class="newow-status-card__prices">
      <span>{{ card.progress.leftLabel }} <b>{{ formatMarketDecimal(card.progress.leftPrice.display_value??card.progress.leftPrice.raw) }}</b></span>
      <div class="newow-status-card__track" role="progressbar" aria-label="参考价格区间进度" :aria-valuenow="Number(card.progress.progress)" :aria-valuemin="0" :aria-valuemax="100"><i :style="{width:card.progress.progress+'%'}"/><em :style="{left:card.progress.progress+'%'}"/></div>
      <span>{{ card.progress.rightLabel }} <b>{{ formatMarketDecimal(card.progress.rightPrice.display_value??card.progress.rightPrice.raw) }}</b> ~</span>
     </div>
     <div class="newow-status-card__statistics"><span>{{ card.progress.leftStatisticLabel }} <b>{{ card.progress.leftStatistic }}</b></span><span>{{ card.progress.rightStatisticLabel }} <b>{{ card.progress.rightStatistic }}</b></span></div>
    </template>
    <p v-else class="newow-status-card__missing">价格进度暂不可用 · 未替换缺失价格或跨合约计算。</p>
    <button class="newow-status-card__explanation" type="button" :class="{expanded}" :aria-expanded="expanded" :aria-controls="explanationId" :title="expanded?'收起解释':'展开解释'" @click="expanded=!expanded">
     <span>{{ strategy==='oscillation'?'多周期感知':'AI解读' }}</span><span class="newow-status-card__text">{{ strategy==='oscillation'?'日周小时策略状态 · 点击展开详情':card.explanation }}</span>
    </button>
    <div v-show="expanded" :id="explanationId" class="newow-status-card__details">
     <template v-if="strategy==='oscillation'">
      <div v-for="item in [{name:'周线',tag:card.week,fact:card.weekFact},{name:'日线',tag:card.day,fact:card.dayFact},{name:'60分钟',tag:card.hour,fact:card.hourFact}]" :key="item.name" class="newow-status-card__period"><strong>{{ item.name }}</strong><b :data-state="item.tag.state">{{ item.tag.label }}</b><span>{{ decisionFactAge(item.fact) }}</span><span>{{ item.fact?.bar_end?formatBeijingInstant(item.fact.bar_end):'状态未就绪' }} · {{ item.fact?.physical_contract??'—' }}</span></div>
      <p>{{ card.explanation }}</p>
     </template>
     <p>状态名称保留原多周期背景，立场与综合卡共享所选口径；仅使用同一快照的已完成数据；这是信号机械解释，不代表真实持仓或交易建议。</p>
     <p v-if="decision">截至 {{ formatBeijingInstant(decision.cdv2.as_of) }} · 价格来自同合约 Canonical 通道；主力状态及未证实的探底试盘分支不作推断。</p>
    </div>
   </template>
  </div>
 </section>
</template>
<style scoped>
.newow-status-card { margin:8px 0 12px; border-left:4px solid var(--status-color); background:#fff; box-shadow:0 2px 8px #0000000a; color:#1c1c1e; }
.newow-status-card__header { width:100%; display:flex; align-items:center; gap:6px; flex-wrap:wrap; padding:12px 14px 6px; background:transparent; border:0; text-align:left; cursor:pointer; color:inherit; font:inherit; }
.newow-status-card__header strong { font-size:14px; font-weight:600; }
.newow-status-card__tag { font-size:12px; font-weight:600; padding:2px 7px; border-radius:4px; color:white; line-height:1.3; background:#c7c7cc; }
.newow-status-card__tag[data-state=buy],.newow-status-card__tag[data-state=hold] { background:#ff3b30; }
.newow-status-card__tag[data-state=sell] { background:#34c759; }
.newow-status-card__tag[data-state=wait] { background:#007aff; }
.newow-status-card__risk { color:var(--status-color); font-size:13px; font-weight:500; display:flex; gap:5px; align-items:center; }
.newow-status-card__risk i { width:9px; height:9px; background:var(--status-color); border-radius:50%; }
.newow-status-card__exposure { font-size:12px; color:#8e8e93; margin-left:2px; }
.newow-status-card__exposure small { font-size:10px; }
.newow-status-card__arrow { font-size:11px; color:#8e8e93; transition:transform .2s; margin-left:4px; }
.newow-status-card__arrow.collapsed { transform:rotate(-90deg); }
.newow-status-card__body { padding:0 14px 10px; display:flex; flex-direction:column; gap:6px; }
p { margin:0; font-size:12px; color:#8e8e93; line-height:1.5; }
.newow-status-card__advice { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.newow-status-card__prices { display:flex; align-items:center; gap:6px; height:28px; color:#8e8e93; font-size:13px; }
.newow-status-card__prices>span { white-space:nowrap; } .newow-status-card__prices b { color:#1c1c1e; font-weight:600; }
.newow-status-card__track { flex:1; min-width:30px; height:5px; background:#e5e5ea; border-radius:3px; position:relative; }
.newow-status-card__track i { display:block; height:100%; border-radius:3px; background:linear-gradient(90deg,var(--status-color),color-mix(in srgb,var(--status-color) 87%,white)); }
.newow-status-card__track em { position:absolute; top:50%; transform:translate(-50%,-50%); width:16px; height:16px; border-radius:50%; background:#fff; box-shadow:0 1px 4px #00000026; }
.newow-status-card__statistics { display:flex; justify-content:space-between; color:#aeaeb2; font-size:13px; }
.newow-status-card__statistics b { color:var(--status-color); font-weight:600; }
.newow-status-card[data-risk=cautious] .newow-status-card__statistics b { color:#ff3b30; }
.newow-status-card[data-risk=warning] .newow-status-card__statistics b { color:#34c759; }
.newow-status-card__explanation { border:0; border-top:1px solid #0000000f; padding:7px 0 0; background:transparent; display:flex; align-items:flex-start; text-align:left; cursor:pointer; font:inherit; font-size:13px; color:#8e8e93; gap:6px; min-width:0; }
.newow-status-card__explanation>span:first-child { flex-shrink:0; color:#aeaeb2; }
.newow-status-card__text { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.expanded .newow-status-card__text { white-space:normal; overflow:visible; }
.newow-status-card__details { font-size:12px; color:#8e8e93; display:flex; flex-direction:column; gap:6px; }
.newow-status-card__period { display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:7px 10px; background:#f7f7f9; border-radius:6px; }
.newow-status-card__period b[data-state=buy],.newow-status-card__period b[data-state=hold] { color:#ff3b30; }
.newow-status-card__period b[data-state=sell] { color:#34c759; }
.newow-status-card__retry { border:1px solid #e5e5ea; background:#fff; border-radius:5px; cursor:pointer; color:#007aff; }
button:focus-visible { outline:2px solid #007aff; outline-offset:2px; }
@media(max-width:600px) { .newow-status-card__prices { flex-wrap:wrap; height:auto; } .newow-status-card__track { order:3; flex-basis:100%; margin:8px 0; } .newow-status-card__prices>span:last-child { margin-left:auto; } .newow-status-card__advice { white-space:normal; } }
@media(prefers-reduced-motion:reduce) { .newow-status-card__arrow { transition:none; } }
</style>
