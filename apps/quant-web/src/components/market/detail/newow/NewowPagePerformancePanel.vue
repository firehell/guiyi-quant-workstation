<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PagePerformance } from '@/utils/newowPagePerformance'
import { pagePerformancePlot } from '@/utils/newowPagePerformance'
import { referencePercentDisplay } from '@/utils/newowDetailPresentation'
import { formatMarketDecimal } from '@/utils/marketDisplay'
import { newowReferenceWindow } from '@/utils/newowReferenceWindows'
const props = defineProps<{ value: PagePerformance | null | undefined; since?: string; through?: string; floor?: string; loading?: boolean }>()
const emit = defineEmits<{ reload: [window: {performanceSince: string; performanceThrough: string}] }>()
const selection = ref<'ordinary' | 'ideal'>('ordinary')
const count = ref(100)
const active = computed(() => props.value?.[selection.value] ?? null)
const idealExplanation = computed(() => ({
  trend: '回看最高收盘价，包含清仓当根',
  main_rise: '回看建仓后最高收盘价，不含清仓当根',
  oscillation: '回看滚动区间高点，可含建仓前高点',
  fusion: '回看最高价，不含清仓当根',
}[props.value?.strategy ?? 'trend']))
const segments = computed(() => pagePerformancePlot(active.value))
const records = computed(() => [...(active.value?.trades ?? [])].reverse().slice(0, count.value))
watch(() => props.value, () => { count.value = 100 })
function preset(kind: 'three_months' | 'one_year' | 'three_years' | 'ytd' | 'all') {
  if (props.through) emit('reload', newowReferenceWindow(props.through, kind, props.floor ?? props.since))
}
</script>
<template>
  <section class="page-performance newow-reference" aria-label="公开页面收益投影" :aria-busy="loading">
    <header class="newow-reference__returns-heading"><strong>策略收益率走势</strong><span>公开页面 3.3.79</span></header>
    <div v-if="value" class="newow-reference__presets" aria-label="页面收益模式">
      <button type="button" :aria-pressed="selection === 'ordinary'" @click="selection = 'ordinary'">普通值</button>
      <button type="button" :aria-pressed="selection === 'ideal'" @click="selection = 'ideal'">理论值</button>
    </div>
    <div v-if="value && through" class="newow-reference__presets" aria-label="页面统计快捷窗口">
      <button v-for="item in ([['three_months','近3月'], ['one_year','近1年'], ['three_years','近3年'], ['ytd','今年'], ['all','全部']] as const)" :key="item[0]" type="button" :disabled="loading" @click="preset(item[0])">{{ item[1] }}</button>
    </div>
    <p>页面乐观收益 · 零手续费、零滑点；{{ selection === 'ideal' ? idealExplanation : '包含末根估值平仓' }}，不代表模拟账户或可执行收益。</p>
    <p v-if="!active" role="status">{{ loading ? '正在读取页面收益投影…' : '当前页面收益投影不可用。' }}</p>
    <template v-else>
      <p>{{ since }} → {{ through }} · {{ selection === 'ideal' ? '理论值' : '普通值' }}；曲线、统计和下方记录使用同一口径。</p>
      <section class="newow-reference__curve" aria-label="页面估值收益曲线">
        <p v-if="segments.length === 0" role="status">当前区间无页面收益曲线。</p>
        <svg v-else viewBox="0 0 712 140" preserveAspectRatio="none" role="img" :aria-label="`${selection === 'ideal' ? '理论' : '普通'}页面收益曲线，区段中断处断线`" style="width:100%;height:180px">
          <polyline v-for="(part,index) in segments" :key="index" :points="part" fill="none" stroke="#ff403a" stroke-width="1.8" />
        </svg>
        <p v-if="active.equity.length">末根累计 {{ referencePercentDisplay(active.equity.at(-1)).text }} · {{ active.trading_days.at(-1) }}</p>
      </section>
      <dl class="newow-reference__metrics" data-testid="page-performance-summary">
        <div><dt>累计收益</dt><dd>{{ referencePercentDisplay(active.summary.cumReturn).text }}</dd></div>
        <div><dt>胜率</dt><dd>{{ active.summary.accuracy }}%</dd></div>
        <div><dt>页面回撤</dt><dd>{{ referencePercentDisplay(active.summary.maxDrawdown).text }}</dd></div>
        <div><dt>估值交易次数</dt><dd>{{ active.summary.tradeCount }}</dd></div>
      </dl>
      <p v-if="value?.ordinary_interrupted_count">{{ value.ordinary_interrupted_count }} 笔跨区段未完成配对未计入普通收益。</p>
      <p v-if="selection === 'ideal' && value?.ideal_open_count">{{ value.ideal_open_count }} 笔理论未平仓未计入完成统计。</p>
      <h3>页面估值操盘记录 · {{ selection === 'ideal' ? '理论值' : '普通值' }}</h3>
      <p>此处为公开页面收益算法的独立投影。末根估值不是 CLEAR Marker，也不是 ReferenceTrade 已完成事实。</p>
      <p v-if="records.length === 0">当前口径暂无页面估值交易。</p>
      <article v-for="(trade,index) in records" :key="`${trade.segment_id}:${trade.buyDate}:${trade.sellDate}:${index}`" class="newow-reference__card" :data-page-force-close="trade.forceClose">
        <header><strong>{{ trade.forceClose ? '末根估值平仓' : '页面清仓参考' }}</strong><span>{{ referencePercentDisplay(trade.pct).text }}</span></header>
        <p>建仓 {{ trade.buyDate }} · {{ formatMarketDecimal(trade.buyPrice) }}</p>
        <p>{{ trade.forceClose ? '估值' : '清仓参考' }} {{ trade.sellDate }} · {{ formatMarketDecimal(trade.sellPrice) }}</p>
        <p v-if="trade.buyBarIsLive">末根新建仓的页面估值投影；不代表真实成交。</p>
      </article>
      <button v-if="count < active.trades.length" type="button" @click="count += 100">显示更多页面估值记录</button>
    </template>
  </section>
</template>
<style scoped src="./newowReferencePanel.css"></style>
