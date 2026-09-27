<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { getNewowProductSection } from '@/api/newowProduct'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import type { NewowDecisionV2, DecisionPriceSource } from '@/types/newowDecisionV2'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
import { decisionRoleLabel, decisionStateLabel, decisionFactState, decisionFactAge, decisionFactReason, decisionResonanceReason, decisionMismatchReason } from '@/utils/newowDecisionV2Presentation'
const props = defineProps<{ response: NewowProductSectionResponse<'chart'> }>()
const result = ref<NewowDecisionV2 | null>(null)
const loading = ref(false)
const error = ref('')
let generation = 0
let controller: AbortController | null = null
watch(() => [props.response.meta.identity.product, props.response.meta.identity.strategy, props.response.meta.identity.frequency, props.response.meta.as_of, props.response.meta.snapshot_token], () => {
  generation++; controller?.abort(); result.value = null; loading.value = false; error.value = ''
})
onBeforeUnmount(() => { generation++; controller?.abort() })
async function load() {
  const token = ++generation
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; result.value = null
  const identity = props.response.meta.identity
  try {
    const next = await getNewowProductSection({ identity: { product: identity.product, strategy: identity.strategy, frequency: identity.frequency, seriesKind: 'actual_dominant' }, section: 'explanation', decisionV2: true, asOf: props.response.meta.as_of, ...(props.response.meta.snapshot_token ? { snapshotToken: props.response.meta.snapshot_token } : {}) }, { signal: controller.signal })
    if (next.section !== 'explanation' || !next.value?.decision_v2) throw new Error('missing decision')
    if (token === generation) result.value = next.value.decision_v2
  } catch { if (token === generation) error.value = '综合解释读取失败或输入快照不一致，请刷新后重试。' }
  finally { if (token === generation) loading.value = false }
}
const cd = computed(() => result.value?.cdv2)
const prices = computed(() => result.value?.prices)
const captions: Record<string,string> = { trend:'趋势明确', oscillation:'震荡明确', resonance:'共振', direction:'方向', volatility:'波动扣分', j_reduce:'J 减仓', care:'care', tent:'tent' }
const dailyWeeklyFacts = computed(() => ['trend_day', 'oscillation_day', 'trend_week', 'oscillation_week'].map(role => ({ role, fact: cd.value?.facts.find(f => f.role === role) })))
const missingDailyWeekly = computed(() => cd.value?.missing_roles.filter(role => !role.endsWith('_m60')) ?? [])
const showPrice = (p: DecisionPriceSource | null | undefined) => p ? formatMarketDecimal(p.display_value ?? p.raw) : '—'
const progress = computed(() => {
  const card = prices.value?.status_card
  if (!card?.target || !card.absorb || !prices.value) return null
  const low = Number(card.absorb.display_value), high = Number(card.target.display_value), now = Number(prices.value.current_price.raw)
  return high > low ? Math.max(0, Math.min(100, (now-low)/(high-low)*100)) : null
})
</script>
<template>
  <section class="decision-v2" aria-label="新版综合决策 CDV2">
    <header><strong>日周综合决策 CDV2 <small>仅作解释</small></strong><button :disabled="loading" @click="load">{{ loading ? '读取中…' : result ? '刷新综合解释' : '读取综合决策与跨周期价格' }}</button></header>
    <p class="decision-v2__scope"><b>60分钟未参与</b> · 仅使用已完成日线／周线，本卡不代表完整三周期综合决策。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="cd">
      <div class="decision-v2__headline"><progress :value="cd.total" max="100" /><b>{{ cd.total }} 分</b><span>{{ cd.resonance }} 共振</span><span v-if="cd.mismatch">{{ cd.mismatch }} 错配</span><strong>{{ cd.action }}</strong></div>
      <p>截至 {{ formatBeijingInstant(cd.as_of) }} · 已完成 Bar · 参考强度 {{ cd.reference_exposure_range || '0%' }}（不代表保证金比例或手数）</p>
      <p v-if="missingDailyWeekly.length" class="decision-v2__warning">日周输入不可用：{{ missingDailyWeekly.map(decisionRoleLabel).join('、') }}；没有跨周期替代或猜测年龄。</p>
      <section class="decision-v2__states" aria-label="日周策略状态与信号年龄">
        <article v-for="item in dailyWeeklyFacts" :key="item.role">
          <strong>{{ decisionRoleLabel(item.role) }}</strong><b>{{ decisionFactState(item.fact) }}</b>
          <span>信号年龄 {{ decisionFactAge(item.fact) }}</span>
          <small>{{ item.fact?.bar_end ? formatBeijingInstant(item.fact.bar_end) : decisionFactReason(item.fact) }}{{ item.fact?.physical_contract ? ' · ' + item.fact.physical_contract : '' }}</small>
        </article>
      </section>
      <p>信号年龄为距最近一次策略动作的已完成 K 线数；0根表示本周期当前 Bar 发生动作，日K与周K分别计龄。</p>
      <div class="decision-v2__reasons" aria-label="共振与错配依据">
        <p><strong>{{ cd.resonance }} 共振依据：</strong>{{ decisionResonanceReason(cd) }}</p>
        <p><strong>{{ cd.mismatch || '无错配命中' }}：</strong>{{ decisionMismatchReason(cd) }}</p>
      </div>
      <div class="decision-v2__scores"><div v-for="(score,key) in cd.scores" :key="key"><b>{{ score }}</b><small>{{ captions[key] }}</small></div></div>
      <details><summary>展开依据 · 信号计龄 / 额外扣分 / 双轴仓位</summary>
        <div class="decision-v2__scroll"><table><thead><tr><th>策略周期</th><th>状态</th><th>信号年龄</th><th>Bar / 合约</th><th>来源</th></tr></thead><tbody><tr v-for="f in cd.facts" :key="f.role"><td>{{ decisionRoleLabel(f.role) }}</td><td>{{ decisionFactState(f) }}</td><td>{{ decisionFactAge(f) }}</td><td>{{ f.bar_end ? formatBeijingInstant(f.bar_end) : '—' }} / {{ f.physical_contract || '—' }}</td><td>{{ decisionFactReason(f) }}</td></tr></tbody></table></div>
        <p>额外扣分 {{ cd.cert_extra }}：<span v-for="(score,key) in cd.deductions" :key="key">{{ captions[key] }} {{ score }}（{{ cd.extra_sources[key] }}） </span></p>
        <p>确定性轴上限 {{ cd.certainty_cap }}% · 共振轴上限 {{ cd.resonance_cap }}% → 参考强度上限 {{ cd.reference_exposure_cap }}%</p>
        <p>日线平均 TR / Close 波动率：{{ cd.volatility_pct === null ? '数据不足，不扣波动分' : cd.volatility_pct + '%' }}。总分为明确性，不是胜率；不会改变建仓、清仓或参考交易。</p>
        <small>{{ cd.formula_version }}</small>
      </details>
    </template>
    <section v-if="prices" class="decision-v2__prices" aria-label="跨周期目标吸筹状态卡">
      <header><strong>跨周期参考价格</strong><span>周 {{ decisionStateLabel(prices.weekly_signal) }} · 日 {{ decisionStateLabel(prices.daily_signal) }}</span></header>
      <div class="decision-v2__price-values"><span class="target">目标 {{ showPrice(prices.status_card.target) }}</span><div class="decision-v2__track"><i v-if="progress !== null" :style="{ left: progress + '%' }" /></div><span class="absorb">吸筹 {{ showPrice(prices.status_card.absorb) }}</span></div>
      <p>现价 {{ showPrice(prices.current_price) }} · 昨收 {{ showPrice(prices.previous_close) }}{{ prices.previous_close ? '（同合约前一有效日线 Close）' : '（缺失，未替换为结算价）' }}</p>
      <details><summary>价格来源与 1.005 升级规则</summary>
        <p>日目标 → 周目标、周目标 → 月目标的升级缓冲为 1.005；日视图双持有不自动升级。周状态卡独立覆盖为周 HHV10 / LLV10。月线目标缺失时不编造。</p>
        <p>本地来源：Canonical HHV10 / LLV10；这是公开通道公式的期货适配，不冒充牛哇私有 batch 价格。主图通道图例与状态卡分别保留来源。</p>
        <div class="decision-v2__scroll"><table><thead><tr><th>表面</th><th>价格</th><th>周期 / 时间 / 合约</th><th>命中分支</th></tr></thead><tbody><template v-for="surface in (['shared','status_card'] as const)" :key="surface"><tr v-for="kind in (['target','absorb'] as const)" :key="kind"><td>{{ surface === 'shared' ? '共享选择' : '状态卡' }} · {{ kind === 'target' ? '目标' : '吸筹' }}</td><td>{{ showPrice(prices[surface][kind]) }}</td><td>{{ prices[surface][kind]?.frequency || '—' }} · {{ prices[surface][kind]?.bar_end ? formatBeijingInstant(prices[surface][kind]!.bar_end) : '—' }} · {{ prices[surface][kind]?.physical_contract || '—' }}</td><td>{{ prices[surface][kind]?.branch || '输入不足' }}</td></tr></template></tbody></table></div>
        <small>{{ prices.formula_version }} · {{ prices.guard_status }}</small>
      </details>
    </section>
  </section>
</template>
<style scoped>
.decision-v2 { margin:8px 0; border:1px solid #e8ebf0; border-left:4px solid #ff6b35; border-radius:8px; padding:14px; color:#30343b; }
header,.decision-v2__headline { display:flex; align-items:center; gap:12px; flex-wrap:wrap; } header { justify-content:space-between; } button { border:1px solid #e8ebf0; border-radius:8px; background:white; padding:8px 12px; cursor:pointer; } p,small { color:#8992a4; font-size:12px; } .decision-v2__headline { margin-top:12px; color:#ff9500; } progress { accent-color:#ff9500; height:8px; width:180px; } .decision-v2__scores { display:grid; grid-template-columns:repeat(5,1fr); background:#f7f8fa; border-radius:8px; margin:12px 0; padding:12px; } .decision-v2__scores div { text-align:center; } .decision-v2__scores b { display:block; font-size:20px; color:#ff9500; } .decision-v2__warning { color:#bd811e; } summary { font-size:13px; cursor:pointer; margin:10px 0; } .decision-v2__scroll { overflow:auto; } table { width:100%; border-collapse:collapse; font-size:12px; white-space:nowrap; } td,th { padding:8px; text-align:left; border-bottom:1px solid #eef0f4; } .decision-v2__prices { margin-top:14px; border-top:1px solid #eef0f4; padding-top:14px; } .decision-v2__price-values { display:flex; align-items:center; gap:12px; margin:14px 0; font-size:13px; } .target { color:#ff6b35; } .absorb { color:#22b957; } .decision-v2__track { flex:1; height:5px; background:#e8ebf0; border-radius:8px; position:relative; } i { position:absolute; width:16px; height:16px; background:#fff; border:1px solid #ddd; border-radius:50%; top:-6px; transform:translateX(-50%); } @media(max-width:600px) { .decision-v2__headline progress { width:100%; } .decision-v2__price-values { flex-wrap:wrap; } .decision-v2__track { min-width:40px; } }
.decision-v2__scope { background:#fff7ed; color:#94611b; padding:9px 12px; border-radius:6px; }
.decision-v2__states { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:14px; }
.decision-v2__states article { display:flex; flex-direction:column; gap:6px; padding:12px; background:#f7f8fa; border-radius:6px; font-size:13px; }
.decision-v2__states b { color:#30343b; font-size:15px; }
.decision-v2__states span { color:#687386; font-size:12px; }
.decision-v2__reasons { border-top:1px solid #eef0f4; border-bottom:1px solid #eef0f4; }
.decision-v2__reasons p { color:#687386; line-height:1.7; }
@media(max-width:800px) { .decision-v2__states { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
