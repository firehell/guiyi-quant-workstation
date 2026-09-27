<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import type { NewowDecisionV2, DecisionPriceSource } from '@/types/newowDecisionV2'
import { dailyWeeklyPathGeometry } from '@/utils/newowDailyWeeklyPath'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
const props = defineProps<{ decision: NewowDecisionV2 | null; loading: boolean; error: string }>()
const expanded = ref(false), bodyId = useId()
const data = computed(() => props.decision?.daily_weekly_path)
const paths = computed(() => dailyWeeklyPathGeometry(data.value?.periods ?? []))
const price = (p: DecisionPriceSource | null) => p ? formatMarketDecimal(p.raw) : '—'
const reasons: Record<string,string> = { PERIOD_CONTEXT_UNAVAILABLE:'周期数据不足', FLAT_NO_OPEN_ENTRY:'空仓，无当前建仓成本', OPEN_ENTRY_UNAVAILABLE:'当前建仓身份或价格缺失', TARGET_UNAVAILABLE:'同周期目标缺失' }
</script>

<template>
  <section class="period-path" aria-label="日周路径示意图">
    <button class="period-path__toggle" type="button" :aria-expanded="expanded" :aria-controls="bodyId" @click="expanded = !expanded">
      <strong>日周路径示意图</strong><span>成本 → 现价 → 目标</span><b aria-hidden="true">{{ expanded ? '▴' : '▾' }}</b>
    </button>
    <div v-show="expanded" :id="bodyId" class="period-path__body">
      <p v-if="loading" role="status">读取同一快照的日周路径…</p>
      <p v-else-if="error" role="alert">路径数据读取失败，请刷新综合决策。</p>
      <p v-else-if="!data">日周路径数据不可用。</p>
      <template v-else>
        <div class="period-path__legend"><span v-for="path in paths" :key="path.frequency" :style="{ color:path.color }">● {{ path.label }} {{ path.state === null ? '[数据不足]' : path.active ? '[持有]' : '[观望]' }}</span><small>实线：成本至现价　虚线：目标示意</small></div>
        <div class="period-path__canvas">
          <svg viewBox="0 0 760 275" role="img" aria-label="日周参考成本、现价与目标的价格示意">
            <rect x="55" y="22" width="325" height="220" fill="#f8f9fb" />
            <rect x="380" y="22" width="325" height="220" fill="#f5f3ff" />
            <path d="M55 242 H705 M380 22 V242" stroke="#d8dbe2" stroke-dasharray="4 5" fill="none" />
            <text x="18" y="35" class="period-path__axis">价格</text>
            <text x="180" y="265" class="period-path__axis">已完成阶段</text><text x="520" y="265" class="period-path__axis">未来目标示意</text>
            <text x="85" y="15" class="period-path__axis">参考成本</text><text x="365" y="15" class="period-path__axis">现价</text><text x="635" y="15" class="period-path__axis">目标</text>
            <g v-for="(path,index) in paths" :key="path.frequency" :stroke="path.color" :fill="path.color">
              <path v-if="path.cost && path.current && path.active" :d="`M${path.cost.x} ${path.cost.y} L${path.current.x} ${path.current.y}`" fill="none" stroke-width="2.5" />
              <path v-if="path.current && path.target" :d="`M${path.current.x} ${path.current.y} L${path.target.x} ${path.target.y}`" fill="none" stroke-width="2.5" stroke-dasharray="7 5" />
              <template v-for="(point,key) in { cost:path.cost, current:path.current, target:path.target }" :key="key"><circle v-if="point" :cx="point.x" :cy="point.y" :r="key === 'current' ? 5 : 4" stroke="white" stroke-width="1.5" /></template>
              <text v-if="path.cost" :x="path.cost.x - 45" :y="path.cost.y + (index === 0 ? -10 : 20)" stroke="none">{{ path.label }}成本 {{ price(data.periods[index]!.cost) }}</text>
              <text v-if="path.target" :x="path.target.x - 25" :y="path.target.y + (index === 0 ? -10 : 20)" stroke="none">{{ path.label }}目标 {{ price(data.periods[index]!.target) }}</text>
            </g>
          </svg>
        </div>
        <div class="period-path__values"><article v-for="period in data.periods" :key="period.frequency"><strong>{{ period.frequency === '1w' ? '周线' : '日线' }}</strong><span>成本 {{ price(period.cost) }}</span><span>现价 {{ price(period.current) }}</span><span>目标 {{ price(period.target) }}</span><small v-if="period.reason">{{ reasons[period.reason] ?? '输入不足' }}</small></article></div>
        <p>页面路径仅连接参考价格，横轴为阶段示意，不是预测时间或价格保证；空仓不绘制已持有路径。无止损事实时不补画止损。</p>
        <details class="period-path__sources"><summary>日周独立价格来源</summary><div v-for="period in data.periods" :key="period.frequency"><strong>{{ period.frequency === '1w' ? '周线' : '日线' }}</strong><p v-for="(source,key) in {cost:period.cost,current:period.current,target:period.target}" :key="key">{{ {cost:'建仓成本',current:'现价',target:'目标'}[key] }}：{{ source ? `${price(source)} · ${source.frequency} · ${formatBeijingInstant(source.bar_end)} · ${source.physical_contract} / ${source.segment_id} · ${source.source_category}` : '来源缺失' }}<span v-if="key === 'cost' && period.cost"> · BUILD {{ period.cost.entry_marker_id }}</span></p><small>{{ period.formula_versions?.join(' / ') }}</small></div><p>目标为同周期 HHV10 通道，是期货适配，不冒充牛哇私有价格；不参与策略评分或收益。</p></details>
      </template>
    </div>
  </section>
</template>

<style scoped>
.period-path { margin:8px 0; background:#fff; border-bottom:1px solid #ececf0; color:#1c1c1e; }
.period-path__toggle { width:100%; display:flex; align-items:center; gap:10px; padding:12px 14px; border:0; background:transparent; color:inherit; font:inherit; cursor:pointer; text-align:left; }
.period-path__toggle strong { font-size:14px; } .period-path__toggle span { color:#8e8e93; font-size:11px; } .period-path__toggle b { margin-left:auto; color:#8e8e93; }
.period-path__toggle:focus-visible { outline:2px solid #007aff; outline-offset:-2px; }
.period-path__body { padding:0 14px 12px; } .period-path__legend { display:flex; flex-wrap:wrap; gap:14px; font-size:12px; } .period-path__legend small { color:#8e8e93; margin-left:auto; }
.period-path__canvas { overflow-x:auto; margin:10px 0; } svg { width:100%; max-width:1000px; min-width:560px; display:block; margin:0 auto; } svg text { font-size:11px; } .period-path__axis { fill:#8e8e93; }
.period-path__values { display:grid; grid-template-columns:1fr 1fr; gap:8px; } article { display:flex; flex-wrap:wrap; gap:8px; padding:8px 10px; border-radius:6px; background:#f7f7f9; font-size:12px; } article small { flex-basis:100%; color:#94611b; }
p { color:#8e8e93; font-size:11px; line-height:1.6; margin:7px 0 0; } .period-path__sources { font-size:11px; color:#8e8e93; margin-top:8px; overflow-wrap:anywhere; } summary { cursor:pointer; } .period-path__sources strong { display:block; margin-top:8px; } .period-path__sources small { font-size:10px; }
@media(max-width:600px) { .period-path__values { grid-template-columns:1fr; } .period-path__toggle { flex-wrap:wrap; } .period-path__legend small { flex-basis:100%; margin-left:0; } }
</style>
