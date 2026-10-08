<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import NewowDetailDialog from './NewowDetailDialog.vue'
import { getNewowAiAnalysis, type AiAnalysis, type AiCombo } from '@/api/newowAiAnalysis'
const props = defineProps<{ open: boolean; product: string; asOf: string | null; identityKey: string }>()
const emit = defineEmits<{ close: []; adopt: [combo: AiCombo] }>()
const result = ref<AiAnalysis | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
let generation = 0
let pending: AbortController | null = null
const groups = [{ strategy: 'oscillation', name: '震荡策略', description: '吸筹—拉高' }, { strategy: 'trend', name: '趋势策略', description: '黄蓝带 MA7/MA10' }] as const
const periods = [{ frequency: '1w', name: '周线' }, { frequency: '1d', name: '日线' }, { frequency: '60m', name: '60分钟' }] as const
const best = computed(() => result.value?.combos.find(c => c.is_best) ?? null)
const ranked = computed(() => [...(result.value?.combos ?? [])].sort((a, b) => Number(b.score ?? -1) - Number(a.score ?? -1)))
const strategyName = (c: AiCombo) => c.strategy === 'trend' ? '趋势策略' : '震荡策略'
const periodName = (c: AiCombo) => c.frequency === '1w' ? '周线' : c.frequency === '1d' ? '日线' : '60分钟'
const signed = (v: string) => `${Number(v) >= 0 ? '+' : '−'}${Math.abs(Number(v)).toFixed(1)}%`
function combo(strategy: string, frequency: string) { return result.value?.combos.find(c => c.strategy === strategy && c.frequency === frequency) }
function stop() { ++generation; pending?.abort(); pending = null; loading.value = false; result.value = null; error.value = null }
async function run() {
  stop()
  if (!props.open) return
  if (!props.asOf) { error.value = '当前行情快照尚未就绪，请待图表加载完成后重试。'; return }
  const current = generation
  pending = new AbortController(); loading.value = true
  try {
    const value = await getNewowAiAnalysis(props.product, props.asOf, { signal: pending.signal })
    if (current === generation && props.open) result.value = value
  } catch (failure) {
    if (current === generation && props.open) error.value = failure instanceof Error && failure.message === 'NEWOW_RESOURCE_BUSY'
      ? '图表或融合参考仍在计算，请稍后点击“重新回测”。'
      : '分析数据暂不可用，请重新回测。行情质量或身份未确认时不生成推荐。'
  } finally { if (current === generation) { loading.value = false; pending = null } }
}
function adopt() { if (!loading.value && best.value && props.open) emit('adopt', best.value) }
watch(() => [props.open, props.product, props.asOf, props.identityKey] as const, () => {
  if (props.open) void run(); else stop()
}, { immediate: true })
onBeforeUnmount(stop)
</script>
<template>
  <NewowDetailDialog :open="open" title="AI策略分析推荐" :identity-key="identityKey" variant="ai-analysis" @close="emit('close')">
    <p class="ai-subtitle">震荡策略 · 趋势策略 × 周线 / 日线 / 60分钟 历史回测</p>
    <div class="ai-toolbar"><button type="button" class="ai-refresh" :disabled="loading" @click="run">重新回测</button></div>
    <div v-if="loading" class="ai-loading" role="status"><span class="ai-spinner" />正在回测 2 策略 × 3 周期…</div>
    <p v-else-if="error" class="ai-error" role="alert">{{ error }}</p>
    <template v-else-if="result">
      <div v-if="best?.summary" class="ai-banner">
        <div class="ai-banner-title">综合评分推荐</div>
        <div class="ai-banner-main">建议采用 <strong>{{ strategyName(best) }} · {{ periodName(best) }}</strong></div>
        <div class="ai-reason">理由：累计收益 <b>{{ signed(best.summary.cumulative_return) }}</b>；六组合综合评分优先推荐（同分比较交易数）；胜率 <b>{{ best.summary.win_rate }}%</b>；最大回撤 <b>{{ Number(best.summary.max_drawdown).toFixed(1) }}%</b>。<span v-if="best.confidence === 'mid'">样本较少，请谨慎参考。</span></div>
      </div>
      <p v-else class="ai-error" role="status">有效交易样本不足 3 次，暂不推荐策略。</p>
      <section v-for="group in groups" :key="group.strategy" class="ai-group">
        <div class="ai-group-head"><span class="ai-tag" :class="group.strategy">{{ group.name }}</span><span class="ai-description">{{ group.description }}</span></div>
        <div class="ai-grid">
          <div v-for="period in periods" :key="period.frequency" class="ai-cell" :class="{ best: combo(group.strategy, period.frequency)?.is_best }">
            <span v-if="combo(group.strategy, period.frequency)?.is_best" class="ai-best-flag">推荐</span>
            <div class="ai-period">{{ period.name }}</div>
            <template v-if="combo(group.strategy, period.frequency)?.summary">
              <div class="ai-metric"><span>累计收益</span><b :class="Number(combo(group.strategy, period.frequency)!.summary!.cumulative_return) >= 0 ? 'up' : 'down'">{{ signed(combo(group.strategy, period.frequency)!.summary!.cumulative_return) }}</b></div>
              <div class="ai-metric"><span>胜率</span><b>{{ combo(group.strategy, period.frequency)!.summary!.win_rate }}%</b></div>
              <div class="ai-metric"><span>最大回撤</span><b class="drawdown">{{ Number(combo(group.strategy, period.frequency)!.summary!.max_drawdown).toFixed(1) }}%</b></div>
              <div class="ai-metric"><span>交易</span><b>{{ combo(group.strategy, period.frequency)!.summary!.trade_count }}次</b></div>
              <details class="ai-sample"><summary>样本详情</summary><p>含 {{ combo(group.strategy, period.frequency)!.summary!.terminal_valuation_count }} 次段末参考估值</p><p>{{ combo(group.strategy, period.frequency)?.since }} 至 {{ combo(group.strategy, period.frequency)?.through ?? '—' }}</p></details>
            </template>
            <p v-else class="ai-unavailable">数据或预热不足<br>暂不可用</p>
          </div>
        </div>
      </section>
      <div class="ai-ranks" aria-label="综合评分排行">
        <div v-for="(item, index) in ranked" :key="`${item.strategy}:${item.frequency}`" class="ai-rank-row" :class="{ top: item.is_best }">
          <span class="ai-rank-number">{{ index + 1 }}</span><span class="ai-rank-name">{{ strategyName(item) }} · {{ periodName(item) }}<small v-if="item.score === null"> 样本不足</small></span><b>{{ item.score === null ? '—' : (Number(item.score) * 100).toFixed(1) }}</b>
        </div>
      </div>
      <details class="ai-method"><summary>评分与统计口径</summary><p>累计收益、收益回撤比、胜率分别归一化后按 40% / 35% / 25% 加权。至少 3 次交易参与排名；不足 10 次评分乘 0.85；推荐同分时交易数较多者优先。</p><p>按物理合约及质量段分别预热和回看，段末按收盘价参考估值；不跨合约配对，不代表清仓或换月成交。回撤为含浮动的累计收益峰值差（百分点），与下方仅已完成参考交易统计不同。六组合均使用同一历史截止快照。</p><p>截止快照 {{ result.as_of }}；期末参考估值也计入交易次数和胜率。{{ result.formula_version }}</p></details>
    </template>
    <p class="ai-disclaimer">历史页面参考，不含手续费、滑点、涨跌停限制；不构成投资建议，历史表现不代表未来收益。采纳推荐仅切换图表策略与周期。</p>
    <template #footer>
      <div class="ai-actions"><button type="button" class="ai-ghost" @click="emit('close')">知道了</button><button type="button" class="ai-primary" :disabled="loading || !best" @click="adopt">采纳推荐</button></div>
    </template>
  </NewowDetailDialog>
</template>
<style scoped>
.ai-subtitle { margin:0 0 12px; font-size:12px; color:#8e8e93; text-align:center; line-height:1.6; }
.ai-toolbar { display:flex; margin-bottom:12px; }.ai-refresh { padding:7px 16px; border:1px solid #e5e5ea; border-radius:10px; font-size:13px; font-weight:600; background:#f2f2f7; color:#1c1c1e; cursor:pointer; }
.ai-banner { border-radius:14px; padding:12px 14px; margin-bottom:12px; background:linear-gradient(135deg,#ff6b3524,#ff95001a); border:1px solid #ff6b3566; }
.ai-banner-title { font-size:12px; font-weight:700; color:#ff6b35; margin-bottom:4px; }.ai-banner-main { font-size:15px; font-weight:700; line-height:1.5; }.ai-banner-main strong,.ai-reason b { color:#ff6b35; }.ai-reason { font-size:12px; margin-top:4px; line-height:1.7; }
.ai-group { margin-bottom:12px; }.ai-group-head { display:flex; align-items:center; gap:8px; margin-bottom:8px; }.ai-tag { font-size:12px; font-weight:700; padding:3px 10px; border-radius:12px; }.ai-tag.oscillation { background:#ff6b351f; color:#ff6b35; border:1px solid #ff6b354d; }.ai-tag.trend { background:#007aff1f; color:#007aff; border:1px solid #007aff4d; }.ai-description { font-size:11px; color:#8e8e93; }
.ai-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }.ai-cell { min-width:0; background:#f2f2f7; border:1px solid #e5e5ea; border-radius:14px; padding:14px 10px; position:relative; }.ai-cell.best { border:2px solid #ff6b35; box-shadow:0 0 0 2px #ff6b351a; }.ai-period { font-size:14px; font-weight:700; text-align:center; margin-bottom:12px; }.ai-metric { display:flex; justify-content:space-between; gap:6px; font-size:12px; line-height:2; flex-wrap:wrap; }.ai-metric span { color:#8e8e93; }.ai-metric b { margin-left:auto; white-space:nowrap; font-variant-numeric:tabular-nums; }.ai-sample summary { cursor:pointer; }.ai-sample p { margin:4px 0 0; }.up { color:#ff3b30; }.down { color:#34c759; }.drawdown { color:#ff9500; }.ai-best-flag { position:absolute; top:-9px; left:50%; transform:translateX(-50%); background:#ff6b35; color:#fff; font-size:10px; font-weight:700; padding:2px 8px; border-radius:10px; }
.ai-window,.ai-sample { margin:5px 0 0; font-size:10px; color:#8e8e93; line-height:1.5; }.ai-unavailable { font-size:12px; color:#8e8e93; text-align:center; }.ai-rank-row { display:flex; align-items:center; gap:8px; font-size:12px; padding:7px 10px; border-radius:8px; }.ai-rank-row:nth-child(odd) { background:#f2f2f7; }.ai-rank-number { width:14px; text-align:center; font-weight:800; color:#8e8e93; }.ai-rank-name { flex:1; font-weight:600; }.ai-rank-row b { color:#8e8e93; }.ai-rank-row.top b,.ai-rank-row.top .ai-rank-number { color:#ff6b35; }.ai-rank-name small { color:#ff9500; font-weight:400; font-size:10px; }
.ai-method { font-size:10.5px; color:#8e8e93; margin:12px 0; line-height:1.6; }.ai-method summary { cursor:pointer; }.ai-disclaimer { font-size:10.5px; color:#8e8e93; line-height:1.6; text-align:center; padding-top:10px; border-top:1px solid #e5e5ea; margin:6px 0 0; }.ai-actions { display:flex; gap:10px; width:100%; }.ai-actions button { flex:1; padding:10px 0; border:0; border-radius:22px; font-size:14px; cursor:pointer; font-weight:600; min-height:44px; }.ai-actions button.ai-ghost { background:#f2f2f7; color:#1c1c1e; border:1px solid #e5e5ea !important; }.ai-actions button.ai-primary { background:#007aff; color:#fff; }button:disabled { opacity:.45; cursor:default; }button:focus-visible { outline:2px solid #007aff; outline-offset:2px; }
.ai-loading { text-align:center; padding:18px; color:#8e8e93; font-size:13px; }.ai-spinner { display:block; width:20px; height:20px; border:3px solid #e5e5ea; border-top-color:#007aff; border-radius:50%; margin:0 auto 8px; animation:ai-spin .8s linear infinite; }.ai-error { background:#fcebeb; color:#a32d2d; border:1px solid #f7c1c1; border-radius:12px; padding:10px 14px; font-size:12px; }@keyframes ai-spin { to { transform:rotate(360deg); } }@media(prefers-reduced-motion:reduce) { .ai-spinner { animation:none; } }
</style>
