<script setup lang="ts">
import { readNewowBasis, saveNewowBasis } from '@/utils/newowDecisionPreferences'
import { deriveBasisDecision } from '@/utils/newowBasisDecision'
import { newowErrorDisplay } from '@/utils/newowDataDiagnostics'
import { previewInstant } from '@/utils/candidatePreviewInstant'
import { historicalAnalysisAsOf } from '@/api/newowAiAnalysis'
import { ref, computed, watch, onBeforeUnmount, onMounted, useId } from 'vue'
import { sharedDecisionForOwner, type NewowDisplayOwner } from '@/utils/newowSharedPresentation'
import NewowPriceSources from './NewowPriceSources.vue'
import { type PriceSourceRow, decisionPriceSources } from '@/utils/newowPriceSources'
import NewowStatusCard from './NewowStatusCard.vue'
import NewowDailyWeeklyPath from './NewowDailyWeeklyPath.vue'
import { NewowProductRequestError, getNewowProductSection } from '@/api/newowProduct'
import type { NewowProductSectionResponse, NewowProductFrequency } from '@/types/newowProduct'
import type { NewowDecisionV2 } from '@/types/newowDecisionV2'
import { formatBeijingInstant } from '@/utils/marketDisplay'
import { cardChain, cardMergedChain, cardPresentation, cardStateColor, cardChipState, cardActionColor } from '@/utils/newowDecisionCard'
import { decisionContextIdentity, decisionRoleLabel, decisionFactState, decisionFactAge, decisionFactReason, decisionMismatchReason } from '@/utils/newowDecisionV2Presentation'

const props = withDefaults(defineProps<{ response: NewowProductSectionResponse<'chart'>; historical?: boolean; chartSources?: PriceSourceRow[]; latestCompletedFrequencies?: readonly NewowProductFrequency[]; magic11Ready?:boolean; displayStrategy?: string; pathStrategy?: string; dominant?: 'trend'|'oscillation'|null; dominantAsOf?: string; dominantReady?: boolean; showPath?: boolean; showPriceSources?: boolean; backgroundLabel?: string; mainRiseBackground?: boolean; currentState?: string; expectedOwner?: NewowDisplayOwner | null }>(), { showPath: true, showPriceSources: true })
const emit = defineEmits<{ magic11:[]; 'path-context': [value: { decision: NewowDecisionV2 | null; loading: boolean; error: string }] }>()
const decisionAsOf = computed(() => props.expectedOwner ? props.expectedOwner.asOf : props.response.snapshotContext || props.latestCompletedFrequencies?.includes(props.response.meta.identity.frequency)
  ? props.response.meta.as_of : historicalAnalysisAsOf(props.response.meta.as_of))
const context = computed(() => decisionContextIdentity(props.response.meta.identity))
const result = ref<NewowDecisionV2 | null>(null), loading = ref(false), error = ref('')
const collapsed = ref(true), evidenceExpanded = ref(false)
const surface = ref<HTMLElement | null>(null), visible = ref(typeof IntersectionObserver === 'undefined')
let observer: IntersectionObserver | null = null
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') { visible.value = true; return }
  observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { visible.value = true; observer?.disconnect() } }, { rootMargin: '100px' })
  if (surface.value) observer.observe(surface.value)
})
const bodyId = useId(), evidenceId = useId()
watch([result, loading, error], () => emit('path-context', { decision: result.value, loading: loading.value, error: error.value }), { flush: 'sync' })
function toggleCard() { collapsed.value = !collapsed.value }
let generation = 0, controller: AbortController | null = null
watch(() => [visible.value, props.pathStrategy, props.displayStrategy, props.response.meta.identity.product, props.response.meta.identity.strategy, props.response.meta.identity.frequency, props.response.meta.as_of, props.response.meta.snapshot_token, decisionAsOf.value, props.expectedOwner?.physicalContract, props.expectedOwner?.segmentId, props.expectedOwner?.calculationSegmentId, props.expectedOwner?.frequency].join('|'), () => {
  generation++; controller?.abort(); result.value = null; loading.value = false; error.value = ''; evidenceExpanded.value = false; collapsed.value = true
  if (visible.value) void load()
}, { immediate: true })
onBeforeUnmount(() => { observer?.disconnect(); generation++; controller?.abort(); emit('path-context', {decision:null,loading:false,error:''}) })
async function load() {
  const token = ++generation
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; result.value = null
  collapsed.value = true; evidenceExpanded.value = false
  try {
    const asOf = decisionAsOf.value
    const next = await getNewowProductSection({ identity: context.value.identity, section: 'explanation', decisionV2: true, pathStrategy: props.pathStrategy ?? (props.displayStrategy === 'dual' ? 'fusion' : props.displayStrategy), asOf, ...(!context.value.background && asOf === props.response.meta.as_of && props.response.meta.snapshot_token ? { snapshotToken: props.response.meta.snapshot_token } : {}) }, { signal: controller.signal })
    if (next.section !== 'explanation' || !next.value?.decision_v2) throw new Error('missing decision')
    if (props.expectedOwner && previewInstant(props.expectedOwner.asOf) !== previewInstant(props.response.meta.as_of)) throw new Error('shared cutoff mismatch')
    if (props.expectedOwner && !sharedDecisionForOwner(next.value.decision_v2, props.expectedOwner, props.mainRiseBackground ? 'trend' : 'oscillation')) throw new Error('shared owner mismatch')
    if (token === generation) result.value = next.value.decision_v2
  } catch (failure) {
    if (token === generation) {
      error.value = failure instanceof NewowProductRequestError
        ? failure.classification === 'busy' ? '图表仍在计算，请稍后重试综合解释。'
          : failure.diagnostic ? failure.message
            : newowErrorDisplay(failure.code) ?? '综合解释暂不可用，请重试。'
        : '综合解释读取失败或输入快照不一致，请刷新后重试。'
    }
  } finally { if (token === generation) loading.value = false }
}
const basis = ref(readNewowBasis())
function selectBasis(value: 'week' | 'day') { basis.value = value; collapsed.value = true; evidenceExpanded.value = false }
watch(basis, saveNewowBasis)
function refreshBasis() { if (document.visibilityState === 'visible') basis.value = readNewowBasis() }
function syncBasis(event: StorageEvent) { if (event.key === null || event.key === 'guiyi.newow.decision-basis.v1') refreshBasis() }
onMounted(() => { if (typeof document !== 'undefined') document.addEventListener('visibilitychange', refreshBasis); if (typeof window !== 'undefined') window.addEventListener('storage', syncBasis) })
onBeforeUnmount(() => { if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', refreshBasis); if (typeof window !== 'undefined') window.removeEventListener('storage', syncBasis) })
const displayStrategy = computed(() => props.displayStrategy ?? props.response.meta.identity.strategy)
const hasBasisBucket = computed(() => ['trend','oscillation','dual'].includes(displayStrategy.value))
const basisDecision = computed(() => displayStrategy.value === 'dual' && (!props.dominantReady || props.dominantAsOf !== result.value?.cdv2.as_of) ? null : deriveBasisDecision(result.value,displayStrategy.value,basis.value,props.dominant ?? null))
const cd = computed(() => result.value?.cdv2)
const view = computed(() => cd.value ? cardPresentation(cd.value) : null)
const copy = computed(() => cd.value?.presentation?.version === 'guiyi_cdv2_daily_weekly_hourly_presentation_v1' && cd.value.presentation.scope === 'daily_weekly_hourly' ? cd.value.presentation : null)
const prices = computed(() => result.value?.prices)
const priceSnapshotNote = computed(() => prices.value && previewInstant(prices.value.as_of) !== previewInstant(props.response.meta.as_of) ? `共享／状态卡价格截至 ${formatBeijingInstant(prices.value.as_of)}，与主图截止不同；不替代主图通道价格。` : undefined)
const dailyWeeklyFacts = computed(() => ['trend_week', 'trend_day', 'oscillation_week', 'oscillation_day', 'trend_m60', 'oscillation_m60'].map(role => ({ role, fact: cd.value?.facts.find(f => f.role === role) })))
const missingDailyWeekly = computed(() => cd.value?.missing_roles ?? [])
const deductions: Record<string, string> = { j_reduce: 'J 减仓', care: '小心', tent: '暂定峰（关闭）' }
const bias = (axis: 'trend' | 'oscillation') => {
  const value = axis === 'trend' ? cd.value?.trend_bias : cd.value?.oscillation_bias
  return ({ bullish: { label: '看多', color: '#ff3b30' }, bearish: { label: '看空', color: '#34c759' }, cautious: { label: '偏空', color: '#ff9500' }, warning: { label: '偏多', color: '#ff6b35' } } as Record<string, { label: string; color: string }>)[value ?? ''] ?? { label: '--', color: '#8e8e93' }
}
const chain = computed(() => cardChain(cd.value, displayStrategy.value, basis.value, displayStrategy.value === 'dual' && (!props.dominantReady || props.dominantAsOf !== cd.value?.as_of) ? null : props.dominant))
const mergedChain = computed(() => cardMergedChain(chain.value))
const signalCells = computed(() => chain.value.filter(cell => cell.fact?.status === 'ready' && cell.fact.last_signal))
const action = computed(() => basisDecision.value?.action ?? (['trend','oscillation','dual'].includes(displayStrategy.value) ? '等待' : cd.value?.action ?? ''))
const signalPrice = (price: string) => Number(price).toFixed(2)
const signalDate = (at: string) => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(at))
</script>
<template>
  <section ref="surface" data-testid="composite-card-surface" class="decision-v2 composite-action-card" aria-label="新版综合决策 CDV2" :style="{ '--certainty-color': view?.tier.color ?? '#8e8e93' }">
    <div class="composite-header">
      <button type="button" class="decision-v2__toggle" :aria-label="collapsed ? '展开综合决策' : '收起综合决策'" :aria-expanded="!collapsed" :aria-controls="bodyId" @click="toggleCard">
        <strong class="composite-title">综合决策</strong>
        <span class="composite-spacer" />
        <span v-if="cd && hasBasisBucket" class="composite-action-word" :style="{color:cardActionColor(action)}">{{ action }}</span>
        <span v-else-if="!cd" class="composite-basis">{{ loading ? '读取中…' : '综合依据待就绪' }}</span>
        <span class="composite-collapse" :class="{collapsed}" aria-hidden="true">▾</span>
      </button>
    </div>
    <p v-if="loading" v-show="!collapsed" class="decision-v2__message" role="status">正在读取同一快照的已完成日周小时策略…</p>
    <p v-if="error" v-show="!collapsed" class="decision-v2__message" role="alert">{{ error }} <button type="button" @click="load">重试</button></p>
    <div v-show="!collapsed" :id="bodyId" class="decision-v2__body">
      <template v-if="cd && view">
        <div v-if="chain.length" class="composite-chain" aria-label="三周期口径链">
          <span v-if="mergedChain" class="chain-single">{{ mergedChain }}</span>
          <template v-else v-for="(cell,index) in chain" :key="cell.period">
            <span v-if="index" class="chain-arrow" aria-hidden="true">→</span>
            <div class="chain-cell" :class="{main:cell.main,ref:cell.reference}"><div class="cc-top"><span class="cc-key">{{cell.label}}</span></div><div class="cc-bottom"><span class="st" :style="{color:cell.color}">{{cell.state}}</span></div></div>
          </template>
        </div>
        <div v-if="basisDecision?.conflict" class="composite-conflict" role="status">
          <span class="conflict-chip">周期错配</span><div class="conflict-text">周线口径仍持仓，日线已兑现。按「周线主 / 日线从」规则仅作提示，<b>不改动现有仓位</b>。关注周线是否转弱。<span class="conflict-note">口径切换仅影响本页展示，不改变策略信号及现有参考记录。</span></div>
        </div>
        <div v-if="chain.length" class="decision-v2__period-choice composite-basis-switch" aria-label="页面决策口径">
          <button type="button" class="basis-btn" :class="{active:basis==='week'}" aria-label="周线口径" :aria-pressed="basis==='week'" @click="selectBasis('week')">周线主</button>
          <button type="button" class="basis-btn" :class="{active:basis==='day'}" aria-label="日线口径" :aria-pressed="basis==='day'" @click="selectBasis('day')">日线主 · 短线</button>
          <span class="basis-note">周线定方向，日线定买卖点（切换仅影响本页展示）</span>
        </div>
        <div class="composite-body">
          <p class="composite-reason">{{basisDecision?.reason ?? (['trend','oscillation','dual'].includes(displayStrategy) ? '所选口径不可用，等待已完成信号明确。' : copy?.advice ?? view.direction.text)}}</p>
          <div class="composite-alert">
            <section v-if="basisDecision || copy" class="composite-firstaction" :class="'fa-'+(basisDecision ? basisDecision.strength==='tip'?'warn':basisDecision.strength : copy!.first_action.level==='unknown'?'warn':copy!.first_action.level)" aria-label="口径行动原则">
              <b class="fa-icon">{{basisDecision?.strengthName ?? ({ok:'遵守',warn:'提示',violate:'违反',unknown:'待确认'}[copy!.first_action.level])}}</b>
              <div class="fa-text"><strong class="fa-title">{{basisDecision ? '第一行动原则：'+basisDecision.strengthText : copy!.first_action.title}}</strong><p v-if="!basisDecision" class="fa-detail">{{copy!.first_action.detail}}</p></div>
            </section>
            <div v-if="view.mismatch" class="composite-mismatch-row" :style="{'--mismatch-color':view.mismatch.color}"><i class="mm-bar" :style="{background:view.mismatch.color}"/><strong class="mm-type">{{view.mismatch.name}}</strong><span class="mm-sep">·</span><b class="mm-bars">{{view.mismatch.ageLabel}}</b></div>
          </div>
          <p v-if="missingDailyWeekly.length" class="decision-v2__missing">日周小时输入不可用：{{missingDailyWeekly.map(decisionRoleLabel).join('、')}}；缺失不当作空仓，不使用其他周期替代。</p>
          <button type="button" class="decision-v2__detail-toggle composite-detail-toggle" :aria-label="evidenceExpanded ? '收起综合依据' : '展开综合依据'" :aria-expanded="evidenceExpanded" :aria-controls="evidenceId" @click="evidenceExpanded=!evidenceExpanded">{{evidenceExpanded?'收起依据':'展开依据'}}<span aria-hidden="true">{{evidenceExpanded?'▴':'▾'}}</span></button>
          <div v-show="evidenceExpanded" :id="evidenceId" class="decision-v2__evidence">
            <div class="composite-tier-row"><span class="composite-tier-lb">可靠性档位</span><span class="composite-badge" :style="{background:view.tier.color}">{{view.tier.label}}</span></div>
            <div v-if="basisDecision?.conflict || view.position" class="composite-pos-row"><b class="composite-pos-lb">建议仓位（跨策略综合上限）</b><span class="composite-decision-pos">{{basisDecision?.conflict?'仅提示，不改动仓位':view.position}}</span></div>
            <div class="composite-headtag-row"><b class="composite-headtag-lb">共振级别</b><span class="composite-head-tag" :style="{color:view.resonance.color}">{{view.resonance.name}} {{cd.resonance}}</span><span v-if="view.mismatch" class="composite-head-tag ht-mm">{{view.mismatch.name}}</span></div>
            <div v-if="view.mismatch" class="composite-mm-detail-row"><strong class="mm-action">{{view.mismatch.action}}</strong><span class="mm-detail">{{view.mismatch.detail}}</span></div>
            <div class="composite-cert-row" aria-label="综合决策五项评分"><div v-for="score in view.scores" :key="score.key" class="decision-v2__score composite-cert-item"><b class="composite-cert-num" :style="{color:score.color}">{{score.value??'—'}}</b><small class="composite-cert-lab">{{score.label}}</small></div></div>
            <div v-if="view.volatility" class="composite-vol-row"><strong class="composite-vol-lb">波动率</strong><div class="composite-vol-track"><span class="composite-vol-seg vs-g"/><span class="composite-vol-seg vs-o"/><span class="composite-vol-seg vs-r"/><i class="composite-vol-dot" :style="{left:view.volatility.position+'%',background:view.volatility.color}"/></div><b class="composite-vol-num" :style="{color:view.volatility.color}">{{view.volatility.value}}%</b><span class="composite-vol-tag" :class="'vt-'+view.volatility.level">{{view.volatility.label}}</span></div>
            <div class="composite-dual" aria-label="日周小时策略状态与信号年龄"><div v-for="axis in (['trend','oscillation'] as const)" :key="axis" class="composite-dcol"><header class="composite-dcol-h"><strong class="composite-dcol-t">{{axis==='trend'?'趋势策略':'震荡策略'}}</strong><b class="composite-dcol-d" :style="{color:bias(axis).color}">{{bias(axis).label}}</b></header><div class="composite-chips"><span v-for="item in dailyWeeklyFacts.filter(item=>item.role.startsWith(axis))" :key="item.role" class="composite-chip" :title="decisionFactAge(item.fact)" :style="{color:cardStateColor(item.fact)}">{{item.role.endsWith('week')?'周线':item.role.endsWith('m60')?'60分':'日线'}} {{cardChipState(axis,item.fact)}}</span></div></div></div>
            <div class="composite-dir-row" :style="{borderLeftColor:view.direction.color}"><strong class="composite-dir-label">方向</strong><span class="composite-dir-value" :style="{color:view.direction.color}">{{view.direction.text}}</span></div>
            <div class="composite-resonance-row" aria-label="共振与错配依据" :style="{borderLeftColor:view.resonance.color}"><strong class="composite-resonance-name" :style="{color:view.resonance.color}">{{view.resonance.name}}</strong><span class="composite-resonance-dots" :style="{color:view.resonance.color}">{{view.resonance.dots}}</span><p class="composite-resonance-desc">{{view.resonance.description}}</p></div>
            <div v-if="signalCells.length" class="composite-signal-price-row"><div v-for="cell in signalCells" :key="cell.period" class="sp-line"><span class="sp-tag">信号价</span>{{cell.label}} {{signalPrice(cell.fact!.last_signal!.price)}} · {{signalDate(cell.fact!.last_signal!.bar_end)}}</div></div>
            <span class="composite-basis">已收盘数据</span>
          </div>
          <div v-if="!hasBasisBucket" class="composite-decision-card" :class="{'dc-bull':view.tier.color==='#ff3b30','dc-bear':view.tier.color==='#34c759'}"><div class="composite-decision-top"><span class="composite-decision-label" :style="{color:view.tier.color}">{{cd.action}}</span></div></div>
          <p class="compliance-row">本结论基于策略信号的机械判定，仅供参考，不构成投资建议。</p>
        </div>
      </template>
    </div>
  </section>
  <details class="decision-v2__audit" aria-label="综合决策来源与诊断"><summary>综合决策来源与诊断</summary>
    <template v-if="cd && view"><details class="decision-v2__proof"><summary>数据来源、信号计龄与参考强度</summary>    <p class="decision-v2__scope">{{ context.background ? `当前 ${response.meta.identity.frequency} 未参与综合评分 · 日周小时作背景` : "60分钟参与综合评分" }} · 仅使用同一历史快照的已完成日线／周线／60分钟；建议仓位为页面参考强度，不代表保证金比例、手数或账户持仓。</p>
                      <p>建议仓位（跨策略综合上限）：{{ view.exposure }} · 页面参考强度，不代表账户持仓。</p><p>沿用原版权重，日周小时共同参与；缺失不补分、不归一化。确定性表示信号明确性，不是胜率。</p>
          <p>错配依据：{{ decisionMismatchReason(cd) }}</p>
            <p v-if="copy && !basisDecision">{{ copy.first_action.detail }}</p>
            <p>信号年龄为距最近一次策略动作的已完成 K 线数；0根表示本周期当前 Bar 发生动作，日K与周K分别计龄。</p>
            <div class="decision-v2__scroll"><table><thead><tr><th>策略周期</th><th>状态</th><th>信号年龄</th><th>Bar / 合约</th><th>来源</th></tr></thead><tbody><tr v-for="item in dailyWeeklyFacts" :key="item.role"><td>{{ decisionRoleLabel(item.role) }}</td><td>{{ decisionFactState(item.fact) }}</td><td>{{ decisionFactAge(item.fact) }}</td><td>{{ item.fact?.bar_end ? formatBeijingInstant(item.fact.bar_end) : '—' }} / {{ item.fact?.physical_contract || '—' }}</td><td>{{ decisionFactReason(item.fact) }}</td></tr></tbody></table></div>
            <p>额外扣分 {{ cd.cert_extra }}：<span v-for="(score,key) in cd.deductions" :key="key">{{ deductions[key] ?? key }} {{ score }}（{{ cd.extra_sources[key] }}） </span></p>
            <p v-if="cd.care_input">小心来源：{{ cd.care_input.status==='ready' ? `最近 ${cd.care_input.window_size} 根已完成K线 · ${cd.care_input.physical_contract} · 截至 ${cd.care_input.bar_end}` : '当前计算段来源不足，不作为已验证的无事件' }}</p>
            <p>确定性轴上限 {{ cd.certainty_cap }}% · 共振轴上限 {{ cd.resonance_cap }}% → 参考强度上限 {{ cd.reference_exposure_cap }}%</p>
            <small>{{ cd.formula_version }}{{ copy ? ' · ' + copy.version : '' }}</small>
          </details></template>
    <button type="button" class="decision-v2__refresh" aria-label="刷新综合决策" :disabled="loading" @click="load">刷新综合决策</button>
  </details>
  <div data-testid="status-card-surface"><NewowStatusCard :magic11-ready="magic11Ready" @magic11="emit('magic11')" :background="context.background" :background-label="backgroundLabel" :main-rise-background="mainRiseBackground" :current-state="currentState" :decision="result" :strategy="displayStrategy" :basis="basis" :dominant="dominant" :basis-decision="basisDecision" :loading="loading" :error="error" @retry="load" /></div>
  <NewowPriceSources v-if="showPriceSources" :rows="[...(chartSources ?? []), ...decisionPriceSources(prices)]" label="目标／吸筹来源" :guard-status="prices?.guard_status" :snapshot-note="priceSnapshotNote" :background-label="backgroundLabel" />
  <NewowDailyWeeklyPath v-if="showPath !== false" :decision="result" :loading="loading" :error="error" />
</template>

<style scoped>
.composite-action-card { background: #fff; border-bottom: 0.5px solid #f0f0f0; }
.composite-action-card .composite-header { display: flex; align-items: center; gap: 6px; padding: 10px 14px; cursor: pointer; user-select: none; }
.composite-action-card .composite-title { font-size: 13px; font-weight: 600; color: #1C1C1E; flex-shrink: 0; }
.composite-action-card .composite-summary { font-size: 12px; font-weight: 600; flex-shrink: 0; }
.composite-action-card .composite-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; color: #fff; flex-shrink: 0; line-height: 1.3; }
.composite-action-card .composite-spacer { flex: 1; min-width: 4px; }
.composite-action-card .composite-collapse { font-size: 11px; color: var(--nw-muted); transition: transform .2s; flex-shrink: 0; }
.composite-action-card.collapsed .composite-collapse { transform: rotate(-90deg); }
.composite-action-card .composite-body { padding: 0 14px 12px; display: flex; flex-direction: column; gap: 6px; }
.composite-action-card.collapsed > :not(.composite-header) { display: none !important; }
.composite-action-card .composite-action-word { font-size: 19px; font-weight: 700; flex-shrink: 0; letter-spacing: .5px; }
.composite-action-card .composite-basis-summary { font-size: 11px; color: var(--nw-muted); padding: 0 14px 10px; line-height: 1.5; }
.composite-action-card .composite-reason { font-size: 12px; color: #1c1c1e; line-height: 1.55; }
[data-theme="dark"] .composite-action-card .composite-reason { color: #e5e5e7; }
.composite-action-card .composite-signal-price-row { background: #f7f7f9; border-radius: 6px; padding: 7px 10px; }
.composite-action-card .composite-signal-price-row .sp-line { font-size: 11px; color: #1c1c1e; line-height: 1.7; font-variant-numeric: tabular-nums; }
.composite-action-card .composite-signal-price-row .sp-tag { display: inline-block; font-size: 9px; font-weight: 700; color: var(--nw-muted); border: 0.5px solid #d1d1d6; border-radius: 3px; padding: 0 4px; margin-right: 5px; }
[data-theme="dark"] .composite-action-card .composite-signal-price-row { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-signal-price-row .sp-line { color: #e5e5e7; }
.composite-action-card .composite-signal-row { display: flex; align-items: center; gap: 8px; background: #f7f7f9; border-radius: 6px; padding: 6px 10px; }
.composite-action-card .composite-signal-label { font-size: 11px; color: var(--nw-muted); flex-shrink: 0; }
.composite-action-card .composite-signal-value { font-size: 12px; color: #1C1C1E; flex: 1; min-width: 0; }
.composite-action-card .composite-signal-dir { font-size: 11px; font-weight: 600; flex-shrink: 0; }
.composite-action-card .composite-decision-row { display: flex; align-items: baseline; gap: 8px; padding-top: 2px; }
.composite-action-card .composite-decision-label { font-size: 17px; font-weight: 600; }
.composite-action-card .composite-decision-pos { font-size: 12px; color: var(--nw-muted); }
.composite-action-card .composite-advice { font-size: 11px; color: var(--nw-muted); line-height: 1.5; }
.composite-action-card .composite-score-wrap { flex: 1; min-width: 64px; display: flex; align-items: center; gap: 6px; }
.composite-action-card .composite-score-track { flex: 1; height: 6px; border-radius: 3px; background: #f0f0f2; overflow: hidden; }
.composite-action-card .composite-score-fill { display: block; height: 100%; width: 0%; border-radius: 3px; background: var(--nw-muted); transition: width .3s; }
.composite-action-card .composite-score-num { font-size: 12px; font-weight: 700; flex-shrink: 0; }
.composite-action-card .composite-cert-row { display: flex; align-items: center; background: #f7f7f9; border-radius: 6px; padding: 9px 4px; }
.composite-action-card .composite-cert-item { flex: 1; text-align: center; min-width: 0; }
.composite-action-card .composite-cert-num { font-size: 17px; font-weight: 700; }
.composite-action-card .composite-cert-lab { font-size: 10px; color: var(--nw-muted); margin-top: 1px; }
.composite-action-card .composite-cert-sep { width: 0.5px; height: 26px; background: #e5e5ea; flex-shrink: 0; }
.composite-action-card .composite-vol-row { display: flex; align-items: center; gap: 10px; background: #f7f7f9; border-radius: 6px; padding: 8px 10px; }
.composite-action-card .composite-vol-lb { font-size: 11px; color: var(--nw-muted); font-weight: 600; flex-shrink: 0; }
.composite-action-card .composite-vol-track { flex: 1; height: 5px; border-radius: 3px; background: #ececee; position: relative; }
.composite-action-card .composite-vol-seg { position: absolute; top: 0; bottom: 0; }
.composite-action-card .composite-vol-seg.vs-g { left: 0; width: 33.4%; background: rgba(52,199,89,.30); border-radius: 3px 0 0 3px; }
.composite-action-card .composite-vol-seg.vs-o { left: 33.3%; width: 33.4%; background: rgba(255,149,0,.30); }
.composite-action-card .composite-vol-seg.vs-r { left: 66.6%; width: 33.4%; background: rgba(255,59,48,.28); border-radius: 0 3px 3px 0; }
.composite-action-card .composite-vol-dot { position: absolute; top: 50%; width: 9px; height: 9px; border-radius: 50%; background: var(--nw-muted); border: 2px solid #fff; transform: translate(-50%,-50%); }
.composite-action-card .composite-vol-num { font-size: 12px; font-weight: 700; flex-shrink: 0; min-width: 34px; text-align: right; }
.composite-action-card .composite-vol-tag { flex-shrink: 0; font-size: 10px; font-weight: 700; border-radius: 8px; padding: 1px 7px; }
.composite-action-card .composite-vol-tag.vt-low { background: rgba(52,199,89,.14); color: #1d7a43; }
.composite-action-card .composite-vol-tag.vt-mid { background: rgba(255,149,0,.14); color: #b26a00; }
.composite-action-card .composite-vol-tag.vt-high { background: rgba(255,59,48,.12); color: #c0392b; }
.composite-action-card .composite-dual { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.composite-action-card .composite-dcol { background: #f7f7f9; border-radius: 6px; padding: 8px 10px; min-width: 0; }
.composite-action-card .composite-dcol-h { display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; }
.composite-action-card .composite-dcol-t { font-size: 11px; font-weight: 600; color: var(--nw-muted); }
.composite-action-card .composite-dcol-d { font-size: 11px; font-weight: 700; }
.composite-action-card .composite-chips { display: flex; gap: 4px; flex-wrap: wrap; }
.composite-action-card .composite-chip { font-size: 10px; font-weight: 600; border-radius: 4px; padding: 2px 5px; background: #fff; color: #1C1C1E; }
.composite-action-card .composite-chip.chip-hot { color: var(--nw-rise); }
.composite-action-card .composite-chip.chip-cold { color: var(--nw-fall); }
.composite-action-card .composite-decision-card { border-radius: 10px; padding: 10px 12px; background: rgba(142,142,147,.08); border: 0.5px solid rgba(142,142,147,.25); }
.composite-action-card .composite-decision-card.dc-bull { background: rgba(255,59,48,.06); border-color: rgba(255,59,48,.25); }
.composite-action-card .composite-decision-card.dc-bear { background: rgba(52,199,89,.06); border-color: rgba(52,199,89,.25); }
.composite-action-card .composite-decision-top { display: flex; align-items: center; gap: 8px; }
.composite-action-card .composite-decision-top .composite-decision-label { font-size: 19px; }
.composite-action-card .composite-decision-top .composite-decision-pos { margin-left: auto; }
.composite-action-card .composite-decision-card .composite-advice { margin-top: 5px; }
[data-theme="dark"] .composite-action-card .composite-score-track { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-cert-row { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-vol-row { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-dcol { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-vol-track { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-cert-sep { background: #3a3a3c; }
[data-theme="dark"] .composite-action-card .composite-chip { background: #3a3a3c; color: #e5e5e7; }
[data-theme="dark"] .composite-action-card .composite-vol-dot { border-color: #1c1c1e; }
[data-theme="dark"] .composite-action-card .composite-decision-card { background: rgba(255,255,255,.05); border-color: #3a3a3c; }
.composite-action-card .composite-firstaction { display: flex; align-items: flex-start; gap: 8px; border-radius: 8px; padding: 9px 11px; background: #f2f2f7; border: 1px solid #e5e5ea; }
.composite-action-card .composite-firstaction .fa-icon { font-size: 10px; font-weight: 700; color: #fff; background: var(--nw-muted); border-radius: 5px; padding: 2px 6px; flex-shrink: 0; line-height: 1.5; letter-spacing: 1px; }
.composite-action-card .composite-firstaction .fa-text { flex: 1; min-width: 0; }
.composite-action-card .composite-firstaction .fa-title { font-size: 12px; font-weight: 700; line-height: 1.45; }
.composite-action-card .composite-firstaction .fa-detail { font-size: 11px; line-height: 1.5; margin-top: 2px; opacity: .92; }
.composite-action-card .composite-firstaction.fa-ok { background: rgba(52,199,89,.10); border-color: rgba(52,199,89,.35); }
.composite-action-card .composite-firstaction.fa-ok .fa-icon { background: #1d7a43; }
.composite-action-card .composite-firstaction.fa-ok .fa-title { color: #1d7a43; }
.composite-action-card .composite-firstaction.fa-ok .fa-detail { color: #2e8b57; }
.composite-action-card .composite-firstaction.fa-warn { background: rgba(255,149,0,.10); border-color: rgba(255,149,0,.35); }
.composite-action-card .composite-firstaction.fa-warn .fa-icon { background: #b26a00; }
.composite-action-card .composite-firstaction.fa-warn .fa-title { color: #b26a00; }
.composite-action-card .composite-firstaction.fa-warn .fa-detail { color: #c07f1d; }
.composite-action-card .composite-firstaction.fa-violate { background: rgba(255,59,48,.10); border-color: rgba(255,59,48,.40); border-left: 4px solid #d61e1e; }
.composite-action-card .composite-firstaction.fa-violate .fa-icon { background: #d61e1e; }
.composite-action-card .composite-firstaction.fa-violate .fa-title { color: #d61e1e; }
.composite-action-card .composite-firstaction.fa-violate .fa-detail { color: #c0392b; }
[data-theme="dark"] .composite-action-card .composite-firstaction { background: rgba(255,255,255,.05); border-color: #3a3a3c; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-violate { background: rgba(255,59,48,.10); border-color: rgba(255,59,48,.40); border-left: 4px solid #d61e1e; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-warn { background: rgba(255,149,0,.10); border-color: rgba(255,149,0,.35); }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-ok { background: rgba(52,199,89,.10); border-color: rgba(52,199,89,.35); }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-ok .fa-title { color: #4ade80; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-ok .fa-detail { color: #6ee7a0; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-warn .fa-title { color: #fbbf24; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-warn .fa-detail { color: #fcd34d; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-violate .fa-title { color: #f87171; }
[data-theme="dark"] .composite-action-card .composite-firstaction.fa-violate .fa-detail { color: #fca5a5; }
[data-theme="dark"] .composite-action-card .composite-firstaction .fa-detail { opacity: .85; }
.composite-action-card .composite-dir-row { display: flex; align-items: center; gap: 8px; background: #f7f7f9; border-radius: 6px; padding: 6px 10px; border-left: 3px solid var(--nw-muted); }
.composite-action-card .composite-dir-label { font-size: 11px; color: var(--nw-muted); flex-shrink: 0; font-weight: 600; }
.composite-action-card .composite-dir-value { font-size: 12px; font-weight: 600; flex: 1; min-width: 0; line-height: 1.5; }
[data-theme="dark"] .composite-action-card .composite-dir-row { background: #2c2c2e; }
.composite-action-card .composite-head-tag { font-size: 10px; font-weight: 700; border-radius: 4px; padding: 1px 5px; flex-shrink: 0; line-height: 1.4; background: rgba(142,142,147,.14); color: var(--nw-muted); white-space: nowrap; }
.composite-action-card .composite-head-tag.ht-mm { background: rgba(255,107,53,.14); color: #c2410c; }
.composite-action-card .composite-basis { font-size: 10px; color: var(--nw-muted); flex-shrink: 0; white-space: nowrap; }
.composite-action-card .composite-resonance-row { display: flex; align-items: flex-start; gap: 7px; background: #f7f7f9; border-radius: 6px; padding: 7px 10px; border-left: 3px solid var(--nw-muted); }
.composite-action-card .composite-resonance-name { font-size: 12px; font-weight: 700; flex-shrink: 0; }
.composite-action-card .composite-resonance-dots { font-size: 9px; letter-spacing: 1px; flex-shrink: 0; line-height: 1.6; }
.composite-action-card .composite-resonance-desc { font-size: 11px; color: var(--nw-muted); line-height: 1.5; flex: 1; min-width: 0; }
.composite-action-card .composite-mismatch-row { display: flex; align-items: center; gap: 8px; background: #fff7f2; border-radius: 6px; padding: 7px 10px 7px 0; border: 1px solid rgba(255,107,53,.35); overflow: hidden; }
.composite-action-card .composite-mismatch-row .mm-bar { width: 3px; flex-shrink: 0; background: #ff6b35; border-radius: 3px 0 0 3px; }
.composite-action-card .composite-mismatch-row .mm-main { flex: 1; min-width: 0; padding-left: 5px; }
.composite-action-card .composite-mismatch-row .mm-line1 { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.composite-action-card .composite-mismatch-row .mm-type { font-size: 12px; font-weight: 700; color: #c2410c; }
.composite-action-card .composite-mismatch-row .mm-action { font-size: 11px; font-weight: 600; color: #1c1c1e; }
.composite-action-card .composite-mismatch-row .mm-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; flex-wrap: wrap; }
.composite-action-card .composite-mismatch-row .mm-bars { font-size: 11px; font-weight: 700; color: #ff6b35; flex-shrink: 0; }
.composite-action-card .composite-mismatch-row .mm-detail { font-size: 11px; color: var(--nw-muted); line-height: 1.5; flex: 1; min-width: 0; }
.composite-action-card .composite-alert { display: flex; flex-direction: column; gap: 6px; }
.composite-action-card .composite-mismatch-row .mm-sep { font-size: 11px; font-weight: 700; color: #c2410c; flex-shrink: 0; }
.composite-action-card .composite-pos-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 11px; color: #1c1c1e; line-height: 1.6; }
.composite-action-card .composite-headtag-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 11px; color: #1c1c1e; line-height: 1.6; }
.composite-action-card .composite-mm-detail-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 11px; color: #1c1c1e; line-height: 1.6; }
.composite-action-card .composite-pos-row .composite-pos-lb { font-weight: 700; color: var(--nw-muted); }
.composite-action-card .composite-headtag-row .composite-headtag-lb { font-weight: 700; color: var(--nw-muted); }
.composite-action-card .composite-headtag-row .composite-head-tag { font-size: 10px; font-weight: 700; border-radius: 5px; padding: 1px 6px; }
.composite-action-card .composite-mm-detail-row .mm-action { font-weight: 600; }
.composite-action-card .composite-mm-detail-row .mm-detail { color: var(--nw-muted); }
.composite-action-card .composite-detail-toggle { display: flex; align-items: center; justify-content: center; gap: 4px; font-size: 11px; color: var(--nw-muted); padding: 3px 0; cursor: pointer; user-select: none; }
.composite-action-card .composite-detail-sec { display: flex; flex-direction: column; gap: 6px; }
.composite-action-card .composite-detail-sec.collapsed { display: none; }
.composite-action-card .composite-tier-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; }
.composite-action-card .composite-tier-lb { font-size: 12px; color: var(--nw-muted); }
[data-theme="dark"] .composite-action-card .composite-tier-lb { color: #aeaeb2; }
.composite-action-card .compliance-row { font-size: 10px; color: #aeaeb2; line-height: 1.5; padding: 2px 0 0; text-align: left; }
[data-theme="dark"] .composite-action-card .composite-resonance-row { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-resonance-desc { color: var(--nw-muted); }
[data-theme="dark"] .composite-action-card .composite-mismatch-row { background: rgba(255,107,53,.08); border-color: rgba(255,107,53,.30); }
[data-theme="dark"] .composite-action-card .composite-mismatch-row .mm-action { color: #e5e5e7; }
[data-theme="dark"] .composite-action-card .composite-head-tag { background: rgba(255,255,255,.08); color: #aeaeb2; }
[data-theme="dark"] .composite-action-card .composite-head-tag.ht-mm { background: rgba(255,107,53,.18); color: #ff9a6b; }
[data-theme="dark"] .composite-action-card .compliance-row { color: var(--nw-muted); }
.composite-action-card .composite-chain { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 0 14px 10px; }
.composite-action-card .chain-cell { flex: 0 0 auto; min-width: 78px; background: transparent; border: 0; border-radius: 0; padding: 2px 4px; text-align: center; }
.composite-action-card .chain-cell.main { border: 0; background: transparent; }
.composite-action-card .chain-cell.main .cc-key { font-weight: 800; }
.composite-action-card .chain-cell.ref { border: 0; background: transparent; opacity: .78; }
.composite-action-card .chain-cell .cc-top { display: flex; align-items: baseline; justify-content: center; gap: 4px; margin-bottom: 4px; flex-wrap: wrap; }
.composite-action-card .chain-cell .cc-key { font-size: 12px; font-weight: 700; color: #1c1c1e; }
.composite-action-card .chain-cell .cc-role { font-size: 10px; color: var(--nw-muted); display: none; }
.composite-action-card .chain-cell.ref .cc-key { color: var(--nw-muted); }
.composite-action-card .chain-cell .cc-bucket { font-size: 9px; font-weight: 700; color: var(--nw-muted); border: 0.5px solid #d1d1d6; border-radius: 3px; padding: 0 4px; margin-left: auto; white-space: nowrap; display: none; }
.composite-action-card .chain-cell .cc-bottom { display: flex; align-items: center; justify-content: center; gap: 6px; }
.composite-action-card .chain-cell .cc-price { font-size: 10px; color: var(--nw-muted); font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: none; }
.composite-action-card .chain-cell .st { font-size: 12px; font-weight: 700; white-space: nowrap; }
.composite-action-card .chain-cell .st-hold { color: var(--nw-rise); }
.composite-action-card .chain-cell .st-clear { color: var(--nw-fall); }
.composite-action-card .chain-cell .st-flat { color: var(--nw-muted); }
.composite-action-card .chain-arrow { display: flex; align-items: center; color: #c7c7cc; font-size: 11px; flex: 0 0 auto; }
.composite-action-card .composite-conflict { display: flex; align-items: flex-start; gap: 7px; margin: 0 14px 10px; padding: 8px 10px; border-radius: 6px; background: rgba(255,149,0,.10); border: 1px solid rgba(255,149,0,.35); }
.composite-action-card .composite-conflict .conflict-chip { flex: 0 0 auto; font-size: 10px; font-weight: 700; color: #b26a00; border: 1px solid rgba(178,106,0,.5); border-radius: 4px; padding: 1px 5px; white-space: nowrap; line-height: 1.5; }
.composite-action-card .composite-conflict .conflict-text { font-size: 11px; color: #1c1c1e; line-height: 1.5; flex: 1; min-width: 0; }
.composite-action-card .composite-conflict .conflict-text b { font-weight: 700; }
.composite-action-card .composite-conflict .conflict-note { display: block; margin-top: 3px; font-size: 10px; color: var(--nw-muted); }
.composite-action-card .composite-basis-switch { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 0 14px 10px; }
.composite-action-card .composite-basis-switch .basis-btn { font-size: 11px; color: #1c1c1e; background: #f7f7f9; border: 0.5px solid #d1d1d6; border-radius: 5px; padding: 3px 9px; cursor: pointer; font-family: inherit; line-height: 1.4; }
.composite-action-card .composite-basis-switch .basis-btn.active { background: #0a84ff; color: #fff; border-color: #0a84ff; font-weight: 700; box-shadow: inset 0 0 0 2px rgba(255,255,255,.9); }
.composite-action-card .composite-basis-switch .basis-btn.active::after { content: '当前'; font-size: 9px; margin-left: 4px; opacity: .95; }
.composite-action-card .composite-basis-switch .basis-note { font-size: 10px; color: var(--nw-muted); }
[data-theme="dark"] .composite-action-card .chain-cell { background: transparent; border: 0; }
[data-theme="dark"] .composite-action-card .chain-cell.main { background: transparent; border: 0; }
[data-theme="dark"] .composite-action-card .chain-cell .cc-key { color: #e5e5e7; }
[data-theme="dark"] .composite-action-card .chain-cell.ref .cc-key { color: var(--nw-muted); }
[data-theme="dark"] .composite-action-card .composite-conflict { background: rgba(255,149,0,.12); border-color: rgba(255,149,0,.40); }
[data-theme="dark"] .composite-action-card .composite-conflict .conflict-text { color: #e5e5e7; }
[data-theme="dark"] .composite-action-card .composite-conflict .conflict-chip { color: #fbbf24; border-color: rgba(251,191,36,.5); }
[data-theme="dark"] .composite-action-card .composite-basis-switch .basis-btn { background: #2c2c2e; color: #e5e5e7; border-color: #3a3a3c; }
[data-theme="dark"] .composite-action-card { background: #1c1c1e; border-color: #3a3a3c; }
[data-theme="dark"] .composite-action-card .composite-title { color: #e5e5e7; }
[data-theme="dark"] .composite-action-card .composite-signal-row { background: #2c2c2e; }
[data-theme="dark"] .composite-action-card .composite-signal-value { color: #e5e5e7; }
[data-theme="dark"] .composite-action-card .composite-advice { color: var(--nw-muted); }
[data-theme="dark"] .composite-action-card .composite-decision-pos { color: var(--nw-muted); }
.decision-v2 { --nw-muted:#8e8e93; --nw-rise:#ff3b30; --nw-fall:#34c759; color:#333; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; font-size:16px; line-height:normal; -webkit-font-smoothing:auto; -moz-osx-font-smoothing:auto; margin:0; }
.decision-v2 *, .decision-v2 *::before, .decision-v2 *::after { box-sizing:border-box; }
.decision-v2.composite-action-card button { font-family:inherit; cursor:pointer; min-height:0; }
.decision-v2 p { margin:0; }
.decision-v2__toggle { font:inherit; display:flex;align-items:center;gap:6px;width:100%;padding:0;border:0;background:transparent;text-align:left;color:inherit;line-height:normal; }
.decision-v2__body { display:contents; }
.decision-v2__evidence { display:flex;flex-direction:column;gap:6px; }
.composite-collapse.collapsed { transform:rotate(-90deg); }
.decision-v2__detail-toggle { border:0;width:100%;background:transparent;font-family:inherit;line-height:normal; }
.composite-cert-num { display:block;line-height:normal; }
.composite-cert-lab { display:block;line-height:normal; }
.composite-cert-item + .composite-cert-item { border-left:.5px solid #e5e5ea; }
.chain-single { font-size:12px;line-height:normal; }
.decision-v2__message,.decision-v2__missing { padding:4px 14px;font-size:12px;color:#94611b; }
.decision-v2__audit { font-size:11px;color:var(--gy-text-muted);padding:4px 14px; }
.decision-v2__audit summary { cursor:pointer; }
.decision-v2__audit p { margin:5px 0; }
.decision-v2__audit table { width:100%;border-collapse:collapse; }
.decision-v2__audit td,.decision-v2__audit th { text-align:left;padding:6px;border-bottom:1px solid var(--gy-border); }
.decision-v2__scroll { overflow:auto; }
.decision-v2__refresh { font:inherit;cursor:pointer; }
.decision-v2 button:focus-visible { outline:2px solid #0a84ff;outline-offset:2px; }
.decision-v2 button:disabled { cursor:wait;opacity:.5; }
[data-theme="dark"] .decision-v2 { --nw-muted:#8e8e93; }
[data-theme="dark"] .composite-cert-item + .composite-cert-item { border-color:#3a3a3c; }
@media(prefers-reduced-motion:reduce) { .composite-collapse { transition:none; } }

</style>
