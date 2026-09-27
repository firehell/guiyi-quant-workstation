<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, useId } from 'vue'
import NewowStatusCard from './NewowStatusCard.vue'
import NewowDailyWeeklyPath from './NewowDailyWeeklyPath.vue'
import { NewowProductRequestError, getNewowProductSection } from '@/api/newowProduct'
import type { NewowProductSectionResponse } from '@/types/newowProduct'
import type { NewowDecisionV2, DecisionPriceSource } from '@/types/newowDecisionV2'
import { formatBeijingInstant, formatMarketDecimal } from '@/utils/marketDisplay'
import { decisionContextIdentity, decisionRoleLabel, decisionFactState, decisionFactAge, decisionFactReason, decisionDisplay, decisionMismatchReason } from '@/utils/newowDecisionV2Presentation'

const props = defineProps<{ response: NewowProductSectionResponse<'chart'> }>()
const context = computed(() => decisionContextIdentity(props.response.meta.identity))
const result = ref<NewowDecisionV2 | null>(null), loading = ref(false), error = ref('')
function preference() {
  try { return typeof localStorage === 'undefined' || localStorage.getItem('guiyi_newow_composite_collapsed') !== '0' } catch { return true }
}
const collapsed = ref(preference()), evidenceExpanded = ref(false)
const bodyId = useId(), evidenceId = useId()
function toggleCard() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem('guiyi_newow_composite_collapsed', collapsed.value ? '1' : '0') } catch { /* storage is optional */ }
}
let generation = 0, controller: AbortController | null = null
watch(() => [props.response.meta.identity.product, props.response.meta.identity.strategy, props.response.meta.identity.frequency, props.response.meta.as_of, props.response.meta.snapshot_token].join('|'), () => {
  generation++; controller?.abort(); result.value = null; loading.value = false; error.value = ''; evidenceExpanded.value = false
  void load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; controller?.abort() })
async function load() {
  const token = ++generation
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; result.value = null
  try {
    const next = await getNewowProductSection({ identity: context.value.identity, section: 'explanation', decisionV2: true, asOf: props.response.meta.as_of, ...(!context.value.background && props.response.meta.snapshot_token ? { snapshotToken: props.response.meta.snapshot_token } : {}) }, { signal: controller.signal, ...(context.value.background ? { timeout: 60000 } : {}) })
    if (next.section !== 'explanation' || !next.value?.decision_v2) throw new Error('missing decision')
    if (token === generation) result.value = next.value.decision_v2
  } catch (failure) {
    if (token === generation) error.value = failure instanceof NewowProductRequestError && failure.classification === 'busy' ? '图表仍在计算，请稍后重试综合解释。' : '综合解释读取失败或输入快照不一致，请刷新后重试。'
  } finally { if (token === generation) loading.value = false }
}
const cd = computed(() => result.value?.cdv2)
const view = computed(() => cd.value ? decisionDisplay(cd.value) : null)
const copy = computed(() => cd.value?.presentation?.version === 'guiyi_cdv2_daily_weekly_presentation_v1' && cd.value.presentation.scope === 'daily_weekly' ? cd.value.presentation : null)
const prices = computed(() => result.value?.prices)
const dailyWeeklyFacts = computed(() => ['trend_week', 'trend_day', 'oscillation_week', 'oscillation_day'].map(role => ({ role, fact: cd.value?.facts.find(f => f.role === role) })))
const missingDailyWeekly = computed(() => cd.value?.missing_roles.filter(role => !role.endsWith('_m60')) ?? [])
const deductions: Record<string, string> = { j_reduce: 'J 减仓', care: 'care', tent: 'tent' }
const bias = (axis: 'trend' | 'oscillation') => {
  const value = axis === 'trend' ? cd.value?.trend_bias : cd.value?.oscillation_bias
  return ({ bullish: { label: '看多', color: '#ff3b30' }, bearish: { label: '看空', color: '#34c759' }, cautious: { label: '偏空', color: '#ff9500' }, warning: { label: '偏多', color: '#ff6b35' } } as Record<string, { label: string; color: string }>)[value ?? ''] ?? { label: '未明确', color: '#8e8e93' }
}
const chipColor = (axis: string, period: string) => {
  const state = axis === 'trend' ? cd.value?.trend_state?.[period] : cd.value?.oscillation_state?.[period]
  return state === 'up' || state === 'holding' ? '#ff3b30' : state === 'down' || state === 'cleared' ? '#34c759' : '#8e8e93'
}
const showPrice = (p: DecisionPriceSource | null | undefined) => p ? formatMarketDecimal(p.display_value ?? p.raw) : '—'
</script>

<template>
  <section class="decision-v2" aria-label="新版综合决策 CDV2" :style="{ '--certainty-color': view?.tier.color ?? '#8e8e93' }">
    <div class="decision-v2__header">
      <button type="button" class="decision-v2__toggle" :aria-label="collapsed ? '展开综合决策' : '收起综合决策'" :aria-expanded="!collapsed" :aria-controls="bodyId" @click="toggleCard">
        <strong>综合决策 <small>{{ context.background ? "日周背景" : "日周" }}</small></strong>
        <template v-if="cd && view">
          <span class="decision-v2__score-wrap"><span class="decision-v2__score-track" role="progressbar" aria-label="综合决策确定性评分" :aria-valuenow="cd.total" :aria-valuemin="0" :aria-valuemax="100"><i :style="{ width: cd.total + '%' }" /></span><b>{{ cd.total }} 分</b></span>
          <span class="decision-v2__badge">{{ view.tier.label }}</span>
          <span class="decision-v2__tag" :style="{ color: view.resonance.color }">共振 {{ cd.resonance }}</span>
          <span v-if="view.mismatch" class="decision-v2__tag decision-v2__tag--mismatch">错配 {{ cd.mismatch }}</span>
          <span class="decision-v2__basis" :title="'截至 ' + formatBeijingInstant(cd.as_of)">收盘终值 · 已完成日周 K 线</span>
        </template>
        <span v-else class="decision-v2__basis">{{ loading ? '读取中…' : '综合依据待就绪' }}</span>
        <span class="decision-v2__arrow" :class="{ collapsed }" aria-hidden="true">▾</span>
      </button>
      <button type="button" class="decision-v2__refresh" aria-label="刷新综合决策" title="刷新综合决策" :disabled="loading" @click="load">↻</button>
    </div>
    <p v-if="loading" class="decision-v2__message" role="status">正在读取同一快照的已完成日周策略…</p>
    <p v-else-if="error" class="decision-v2__message" role="alert">{{ error }} <button type="button" @click="load">重试</button></p>
    <div v-show="!collapsed" :id="bodyId" class="decision-v2__body">
      <template v-if="cd && view">
        <section v-if="copy" class="decision-v2__first-action" :data-level="copy.first_action.level" aria-label="第一行动原则">
          <b>{{ { ok:'遵守', warn:'提示', violate:'警示', unknown:'待确认' }[copy.first_action.level] }}</b>
          <div><strong>{{ copy.first_action.title }}</strong><p>{{ copy.first_action.detail }}</p></div>
        </section>
        <p v-if="missingDailyWeekly.length" class="decision-v2__missing">日周输入不可用：{{ missingDailyWeekly.map(decisionRoleLabel).join('、') }}；缺失不当作空仓，不使用其他周期替代。</p>
        <section v-if="view.mismatch" class="decision-v2__mismatch" aria-label="错配期提示" :style="{ '--mismatch-color': view.mismatch.color }">
          <div><strong>{{ view.mismatch.name }}</strong><b>{{ cd.action }}</b></div>
          <p><b>{{ view.mismatch.ageLabel }}</b> {{ view.mismatch.detail }}</p>
        </section>
        <div class="decision-v2__scores" aria-label="综合决策五项评分">
          <div v-for="score in view.scores" :key="score.key" class="decision-v2__score"><b :style="{ color: score.color }">{{ score.value ?? '—' }}</b><small>{{ score.label }}</small></div>
        </div>
        <div class="decision-v2__resonance" aria-label="共振与错配依据" :style="{ '--resonance-color': view.resonance.color }">
          <strong>{{ view.resonance.name }}</strong><span class="decision-v2__dots" aria-hidden="true">{{ view.resonance.dots }}</span><p>{{ view.resonance.description }}</p>
        </div>
        <button type="button" class="decision-v2__detail-toggle" :aria-label="evidenceExpanded ? '收起综合依据' : '展开综合依据'" :aria-expanded="evidenceExpanded" :aria-controls="evidenceId" @click="evidenceExpanded = !evidenceExpanded">{{ evidenceExpanded ? '收起依据' : '展开依据 · 波动率 / 日周状态 / 方向判读' }} <span aria-hidden="true">{{ evidenceExpanded ? '▴' : '▾' }}</span></button>
        <div v-show="evidenceExpanded" :id="evidenceId" class="decision-v2__evidence">
          <div v-if="view.volatility" class="decision-v2__volatility">
            <strong>波动率</strong><div class="decision-v2__vol-track"><i :style="{ left: view.volatility.position + '%', background: view.volatility.color }" /></div><b :style="{ color: view.volatility.color }">{{ view.volatility.value }}%</b><span class="decision-v2__vol-tag" :data-level="view.volatility.level">{{ view.volatility.label }}</span>
          </div>
          <p v-else class="decision-v2__missing">波动率数据不足，未作波动扣分；不把缺失解释为低波动。</p>
          <section class="decision-v2__states" aria-label="日周策略状态与信号年龄">
            <div v-for="axis in (['trend', 'oscillation'] as const)" :key="axis" class="decision-v2__column">
              <header><strong>{{ axis === 'trend' ? '趋势策略' : '震荡策略' }}</strong><b :style="{ color: bias(axis).color }">{{ bias(axis).label }}</b></header>
              <article v-for="item in dailyWeeklyFacts.filter(item => item.role.startsWith(axis))" :key="item.role" :style="{ color: chipColor(axis, item.role.endsWith('week') ? 'week' : 'day') }">
                <strong>{{ decisionRoleLabel(item.role) }}</strong><b>{{ decisionFactState(item.fact) }}</b><span>{{ decisionFactAge(item.fact) }}</span>
              </article>
            </div>
          </section>
          <div class="decision-v2__direction" :style="{ borderLeftColor: view.direction.color }"><strong>方向</strong><p :style="{ color: view.direction.color }">{{ view.direction.text }}</p></div>
          <p>沿用原版权重，日周最高78分；60分钟未参与，不补分、不归一化。确定性表示信号明确性，不是胜率。</p>
          <p>错配依据：{{ decisionMismatchReason(cd) }}</p>
          <details class="decision-v2__proof"><summary>数据来源、信号计龄与参考强度</summary>
            <p>信号年龄为距最近一次策略动作的已完成 K 线数；0根表示本周期当前 Bar 发生动作，日K与周K分别计龄。</p>
            <div class="decision-v2__scroll"><table><thead><tr><th>策略周期</th><th>状态</th><th>信号年龄</th><th>Bar / 合约</th><th>来源</th></tr></thead><tbody><tr v-for="item in dailyWeeklyFacts" :key="item.role"><td>{{ decisionRoleLabel(item.role) }}</td><td>{{ decisionFactState(item.fact) }}</td><td>{{ decisionFactAge(item.fact) }}</td><td>{{ item.fact?.bar_end ? formatBeijingInstant(item.fact.bar_end) : '—' }} / {{ item.fact?.physical_contract || '—' }}</td><td>{{ decisionFactReason(item.fact) }}</td></tr></tbody></table></div>
            <p>额外扣分 {{ cd.cert_extra }}：<span v-for="(score,key) in cd.deductions" :key="key">{{ deductions[key] ?? key }} {{ score }}（{{ cd.extra_sources[key] }}） </span></p>
            <p>确定性轴上限 {{ cd.certainty_cap }}% · 共振轴上限 {{ cd.resonance_cap }}% → 参考强度上限 {{ cd.reference_exposure_cap }}%</p>
            <small>{{ cd.formula_version }}{{ copy ? ' · ' + copy.version : '' }}</small>
          </details>
          <details v-if="prices" class="decision-v2__proof"><summary>目标吸筹价格来源与 1.005 升级规则</summary>
            <p>共享选择使用1.005升级缓冲；日视图双持有不自动升级。周状态卡独立覆盖为周 HHV10 / LLV10，月线缺失不编造。价格来自同合约 Canonical 通道，是期货适配，不冒充私有 batch 价格。</p>
            <p>现价 {{ showPrice(prices.current_price) }} · 昨收 {{ showPrice(prices.previous_close) }}（同合约前一有效日线 Close；缺失不使用结算价替代）</p>
            <div class="decision-v2__scroll"><table><thead><tr><th>表面</th><th>价格</th><th>周期 / 时间 / 合约</th><th>命中分支</th></tr></thead><tbody><template v-for="surface in (['shared','status_card'] as const)" :key="surface"><tr v-for="kind in (['target','absorb'] as const)" :key="kind"><td>{{ surface === 'shared' ? '共享选择' : '状态卡' }} · {{ kind === 'target' ? '目标' : '吸筹' }}</td><td>{{ showPrice(prices[surface][kind]) }}</td><td>{{ prices[surface][kind]?.frequency || '—' }} · {{ prices[surface][kind]?.bar_end ? formatBeijingInstant(prices[surface][kind]!.bar_end) : '—' }} · {{ prices[surface][kind]?.physical_contract || '—' }}</td><td>{{ prices[surface][kind]?.branch || '输入不足' }}</td></tr></template></tbody></table></div>
            <small>{{ prices.formula_version }} · {{ prices.guard_status }}</small>
          </details>
        </div>
        <section class="decision-v2__conclusion" aria-label="综合决策结论" :class="{ 'decision-v2__conclusion--high': cd.total >= 80 }">
          <header><strong>{{ cd.action }}</strong><span class="decision-v2__badge">{{ view.tier.label }}</span><span class="decision-v2__exposure">建议仓位 {{ view.exposure }}</span></header>
          <p>{{ copy?.advice ?? '操作说明暂不可用，仍可查看日周状态和评分依据。' }}</p>
        </section>
        <p class="decision-v2__compliance">本结论基于策略信号的机械判定，仅供参考，不构成投资建议。</p>
      </template>
    </div>
    <p class="decision-v2__scope">{{ context.background ? `当前 ${response.meta.identity.frequency} 未参与综合评分 · 日周仅作背景` : "分钟周期未参与" }} · 仅使用已完成日线／周线；建议仓位为页面参考强度，不代表保证金比例、手数或账户持仓。</p>
  </section>
  <NewowDailyWeeklyPath :decision="result" :loading="loading" :error="error" />
  <NewowStatusCard :background="context.background" :decision="result" :strategy="response.meta.identity.strategy" :loading="loading" :error="error" @retry="load" />
</template>

<style scoped>
.decision-v2 { margin:8px 0; background:#fff; border-bottom:1px solid #f0f0f0; color:#1c1c1e; }
.decision-v2__header { display:flex; align-items:center; gap:6px; padding:9px 14px; }
button { font:inherit; cursor:pointer; } button:focus-visible { outline:2px solid #007aff; outline-offset:2px; } button:disabled { cursor:wait; opacity:.5; }
.decision-v2__toggle { display:flex; align-items:center; gap:7px; flex:1; min-width:0; border:0; padding:0; background:transparent; color:inherit; text-align:left; flex-wrap:wrap; }
.decision-v2__toggle>strong { font-size:14px; white-space:nowrap; } .decision-v2__toggle small { font-size:10px; color:#8e8e93; font-weight:400; }
.decision-v2__score-wrap { display:flex; align-items:center; gap:7px; flex:1; min-width:90px; max-width:420px; color:var(--certainty-color); font-size:13px; white-space:nowrap; }
.decision-v2__score-track { flex:1; height:6px; border-radius:3px; overflow:hidden; background:#f0f0f2; }
.decision-v2__score-track i { display:block; height:100%; border-radius:3px; background:var(--certainty-color); transition:width .3s; }
.decision-v2__badge { color:#fff; background:var(--certainty-color); font-size:11px; font-weight:600; padding:3px 7px; border-radius:4px; white-space:nowrap; }
.decision-v2__tag { background:#f0f0f2; padding:2px 5px; font-size:10px; font-weight:700; border-radius:4px; white-space:nowrap; }
.decision-v2__tag--mismatch { background:#ff6b3520; color:#c2410c; }
.decision-v2__basis { color:#8e8e93; font-size:10px; } .decision-v2__arrow { margin-left:auto; color:#8e8e93; font-size:11px; transition:transform .2s; } .decision-v2__arrow.collapsed { transform:rotate(-90deg); }
.decision-v2__refresh { background:transparent; color:#8e8e93; border:0; font-size:18px; padding:0 3px; flex-shrink:0; }
.decision-v2__body { display:flex; flex-direction:column; gap:7px; padding:0 14px 8px; }
p { margin:0; font-size:12px; line-height:1.55; color:#8e8e93; }
.decision-v2__message { padding:4px 14px; } .decision-v2__message button { border:0; background:transparent; color:#007aff; }
.decision-v2__first-action { display:flex; align-items:flex-start; gap:8px; padding:10px 12px; border:1px solid #e5e5ea; border-radius:8px; background:#f7f7f9; color:#8e8e93; }
.decision-v2__first-action>b { color:white; padding:3px 6px; border-radius:5px; background:#8e8e93; font-size:10px; white-space:nowrap; }
.decision-v2__first-action strong { font-size:13px; } .decision-v2__first-action p { color:inherit; font-size:12px; margin-top:2px; }
.decision-v2__first-action[data-level=ok] { background:#34c75918; border-color:#34c75955; color:#1d7a43; } .decision-v2__first-action[data-level=ok]>b { background:#1d7a43; }
.decision-v2__first-action[data-level=warn] { background:#ff950018; border-color:#ff950055; color:#b26a00; } .decision-v2__first-action[data-level=warn]>b { background:#b26a00; }
.decision-v2__first-action[data-level=violate] { background:#ff3b3018; border-color:#ff3b3055; color:#c0392b; } .decision-v2__first-action[data-level=violate]>b { background:#d61e1e; }
.decision-v2__mismatch { border:1px solid #ff6b3555; border-left:3px solid var(--mismatch-color); background:#fff7f2; border-radius:6px; padding:8px 10px; }
.decision-v2__mismatch>div { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px; font-size:12px; } .decision-v2__mismatch strong,.decision-v2__mismatch p b { color:var(--mismatch-color); } .decision-v2__mismatch p { margin-top:3px; font-size:11px; }
.decision-v2__scores { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); background:#f7f7f9; border-radius:6px; padding:10px 0; }
.decision-v2__score { text-align:center; border-right:1px solid #e5e5ea; } .decision-v2__score:last-child { border-right:0; } .decision-v2__score b { display:block; font-size:20px; line-height:1.3; } .decision-v2__score small { color:#8e8e93; font-size:11px; }
.decision-v2__resonance { display:flex; align-items:flex-start; gap:8px; border-left:3px solid var(--resonance-color); border-radius:6px; padding:8px 10px; background:#f7f7f9; }
.decision-v2__resonance strong { color:var(--resonance-color); white-space:nowrap; font-size:13px; } .decision-v2__dots { color:var(--resonance-color); font-size:10px; letter-spacing:1px; white-space:nowrap; } .decision-v2__resonance p { flex:1; min-width:0; font-size:11px; }
.decision-v2__detail-toggle { border:0; background:transparent; color:#8e8e93; font-size:11px; padding:5px 0; }
.decision-v2__evidence { display:flex; flex-direction:column; gap:7px; }
.decision-v2__volatility { display:flex; align-items:center; gap:10px; background:#f7f7f9; padding:8px 10px; border-radius:6px; font-size:12px; color:#8e8e93; }
.decision-v2__vol-track { flex:1; height:5px; border-radius:3px; position:relative; background:linear-gradient(90deg,#34c7594d 0 33.33%,#ff95004d 33.33% 66.66%,#ff3b3047 66.66% 100%); }
.decision-v2__vol-track i { position:absolute; top:50%; width:9px; height:9px; border-radius:50%; border:2px solid #fff; transform:translate(-50%,-50%); }
.decision-v2__vol-tag { padding:1px 7px; border-radius:8px; font-size:10px; font-weight:700; background:#ececee; } .decision-v2__vol-tag[data-level=low] { background:#34c75924; color:#1d7a43; } .decision-v2__vol-tag[data-level=mid] { background:#ff950024; color:#b26a00; } .decision-v2__vol-tag[data-level=high] { background:#ff3b301f; color:#c0392b; }
.decision-v2__states { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; } .decision-v2__column { background:#f7f7f9; border-radius:6px; padding:8px 10px; }
.decision-v2__column header { display:flex; justify-content:space-between; align-items:center; gap:7px; color:#8e8e93; font-size:12px; margin-bottom:6px; }
.decision-v2__column article { display:inline-flex; align-items:center; flex-wrap:wrap; gap:4px; background:#fff; border-radius:4px; padding:3px 5px; margin:0 5px 4px 0; font-size:11px; } .decision-v2__column article span { color:#8e8e93; font-size:10px; }
.decision-v2__direction { display:flex; align-items:baseline; gap:10px; background:#f7f7f9; border-left:3px solid #8e8e93; border-radius:6px; padding:7px 10px; color:#8e8e93; font-size:12px; }
.decision-v2__conclusion { background:#8e8e9314; border:1px solid #8e8e9340; border-radius:10px; padding:11px 13px; }
.decision-v2__conclusion--high { background:#ff3b300f; border-color:#ff3b3040; }
.decision-v2__conclusion header { display:flex; gap:8px; align-items:center; flex-wrap:wrap; } .decision-v2__conclusion strong { color:var(--certainty-color); font-size:21px; font-weight:600; } .decision-v2__exposure { color:#8e8e93; font-size:12px; margin-left:auto; } .decision-v2__conclusion p { margin-top:6px; }
.decision-v2__scope { font-size:10px; color:#aeaeb2; padding:0 14px 8px; } .decision-v2__compliance { font-size:10px; color:#aeaeb2; }
.decision-v2__proof { font-size:12px; color:#8e8e93; } summary { cursor:pointer; padding:4px 0; } .decision-v2__proof p { margin:5px 0; } .decision-v2__proof small { font-size:10px; overflow-wrap:anywhere; }
.decision-v2__scroll { overflow:auto; } table { width:100%; border-collapse:collapse; font-size:11px; white-space:nowrap; } td,th { padding:7px; text-align:left; border-bottom:1px solid #eef0f4; }
.decision-v2__missing { color:#94611b; }
@media(max-width:600px) { .decision-v2__score-wrap { min-width:80px; } .decision-v2__basis { flex-basis:100%; } .decision-v2__states { grid-template-columns:1fr; } .decision-v2__resonance { flex-wrap:wrap; } .decision-v2__resonance p { flex-basis:100%; } .decision-v2__conclusion strong { font-size:17px; } .decision-v2__exposure { margin-left:0; flex-basis:100%; } .decision-v2__score small { font-size:10px; } .decision-v2__first-action { padding:8px; } }
@media(prefers-reduced-motion:reduce) { .decision-v2__score-track i,.decision-v2__arrow { transition:none; } }
</style>
