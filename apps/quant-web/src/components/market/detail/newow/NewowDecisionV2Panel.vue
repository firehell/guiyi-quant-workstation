<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { getNewowProductSection } from '@/api/newowProduct'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import type { NewowDecisionV2, DecisionPriceSource } from '@/types/newowDecisionV2'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
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
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
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
const periods: Record<string,string> = { week:'周',day:'日',m60:'60分' }
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
    <header><strong>综合决策 CDV2 <small>仅作解释</small></strong><button :disabled="loading" @click="load">{{ loading ? '读取中…' : result ? '刷新综合解释' : '读取综合决策与跨周期价格' }}</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="cd">
      <div class="decision-v2__headline"><progress :value="cd.total" max="100" /><b>{{ cd.total }} 分</b><span>{{ cd.resonance }} 共振</span><span v-if="cd.mismatch">{{ cd.mismatch }} 错配 · {{ cd.mismatch_age >= 0 ? cd.mismatch_age + ' 根' : '计龄未知' }}</span><strong>{{ cd.action }}</strong></div>
      <p>截至 {{ formatBeijingInstant(cd.as_of) }} · 已完成 Bar · 参考强度 {{ cd.reference_exposure_range || '0%' }}（不代表保证金比例或手数）</p>
      <p v-if="cd.missing_roles.length" class="decision-v2__warning">部分周期缺失：{{ cd.missing_roles.map(v => v.replace('trend_', '趋势 ').replace('oscillation_', '震荡 ').replace('m60', '60分').replace('week', '周').replace('day', '日')).join('、') }}；没有跨周期替代或猜测年龄。</p>
      <div class="decision-v2__scores"><div v-for="(score,key) in cd.scores" :key="key"><b>{{ score }}</b><small>{{ captions[key] }}</small></div></div>
      <details><summary>展开依据 · 信号计龄 / 额外扣分 / 双轴仓位</summary>
        <div class="decision-v2__scroll"><table><thead><tr><th>策略周期</th><th>状态</th><th>信号年龄</th><th>Bar / 合约</th><th>来源</th></tr></thead><tbody><tr v-for="f in cd.facts" :key="f.role"><td>{{ f.role.startsWith('trend') ? '趋势' : '震荡' }} {{ periods[f.role.split('_').at(-1)!] }}</td><td>{{ f.state || '未知' }}</td><td>{{ f.age < 0 ? '未知' : f.age + ' 根' }}</td><td>{{ f.bar_end ? formatBeijingInstant(f.bar_end) : '—' }} / {{ f.physical_contract || '—' }}</td><td>{{ f.status === 'ready' ? 'Canonical 策略回放' : f.reason }}</td></tr></tbody></table></div>
        <p>额外扣分 {{ cd.cert_extra }}：<span v-for="(score,key) in cd.deductions" :key="key">{{ captions[key] }} {{ score }}（{{ cd.extra_sources[key] }}） </span></p>
        <p>确定性轴上限 {{ cd.certainty_cap }}% · 共振轴上限 {{ cd.resonance_cap }}% → 参考强度上限 {{ cd.reference_exposure_cap }}%</p>
        <p>日线平均 TR / Close 波动率：{{ cd.volatility_pct === null ? '数据不足，不扣波动分' : cd.volatility_pct + '%' }}。总分为明确性，不是胜率；不会改变建仓、清仓或参考交易。</p>
        <small>{{ cd.formula_version }}</small>
      </details>
    </template>
    <section v-if="prices" class="decision-v2__prices" aria-label="跨周期目标吸筹状态卡">
      <header><strong>跨周期参考价格</strong><span>周 {{ prices.weekly_signal || '未知' }} · 日 {{ prices.daily_signal || '未知' }}</span></header>
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
</style>
