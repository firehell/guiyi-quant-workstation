<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NButtonGroup, NSpin, NTag } from 'naive-ui'
import SubingPerformanceTrendChart from '@/components/market/SubingPerformanceTrendChart.vue'
import SubingStrategyRecords from '@/components/market/SubingStrategyRecords.vue'
import type { SubingStrategyPerformanceResponse, SubingStrategyPerformanceStats } from '@/types/market'
import {
  SUBING_PERFORMANCE_RANGE_OPTIONS,
  buildSubingPerformanceTrend,
  formatSubingMeanHoldingBars,
  nextSubingPerformanceEpisodeLimit,
  subingPerformanceExitReasonRows,
  type SubingPerformanceRangeId,
} from '@/utils/subingStrategyPerformance'

const props = defineProps<{
  symbol: string
  result: SubingStrategyPerformanceResponse | null
  loading: boolean
  error: string | null
}>()

type PerformancePanelTab = 'trend' | 'analysis'
const activeTab = ref<PerformancePanelTab>('trend')
const selectedRange = ref<SubingPerformanceRangeId>('all')
const visibleEpisodeLimit = ref(20)

function percent(value: string | null): string {
  if (value === null) return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed >= 0 ? '+' : ''}${parsed.toFixed(2)}%` : '—'
}

function row(label: string, stats: SubingStrategyPerformanceStats) {
  return { label, stats }
}

function signedTone(label: string): 'up' | 'down' | 'neutral' {
  if (label === '—' || label.startsWith('+0.00%') || label === '+0%') return 'neutral'
  if (label.startsWith('-')) return 'down'
  if (label.startsWith('+')) return 'up'
  return 'neutral'
}

const visibleEpisodes = computed(() => props.result?.episodes.slice(0, visibleEpisodeLimit.value) ?? [])
const hasMoreEpisodes = computed(() => (
  (props.result?.episodes.length ?? 0) > visibleEpisodeLimit.value
))
const exitReasonRows = computed(() => (
  subingPerformanceExitReasonRows(props.result?.exit_reason_counts ?? [])
))
const trend = computed(() => buildSubingPerformanceTrend(
  props.result?.episodes ?? [],
  selectedRange.value,
  props.result?.coverage.resolved_cutoff ?? '',
))
const cumulativeTone = computed(() => signedTone(trend.value.kpis.cumulativeLabel))

watch(
  () => [props.symbol, props.result?.cache_identity_sha256],
  () => {
    visibleEpisodeLimit.value = 20
    activeTab.value = 'trend'
    selectedRange.value = 'all'
  },
)

function showMoreEpisodes(): void {
  visibleEpisodeLimit.value = nextSubingPerformanceEpisodeLimit(
    visibleEpisodeLimit.value,
    props.result?.episodes.length ?? 0,
  )
}

function showAnalysis(): void {
  activeTab.value = 'analysis'
}
</script>

<template>
  <section class="performance" data-testid="subing-strategy-performance">
    <header>
      <div><span>苏冰策略 V1 · {{ props.symbol.toUpperCase() }}</span><h3>历史策略效果</h3></div>
      <NTag type="info" size="small">真实主力 · 15m · 全历史</NTag>
    </header>
    <NSpin :show="loading">
      <p v-if="error" class="warning">历史效果暂不可用；主图与当前观察不受影响。</p>
      <p v-else-if="!result">正在读取全历史策略效果…</p>
      <template v-else>
        <div class="panel-toolbar">
          <NButtonGroup size="small" aria-label="效果视图">
            <NButton
              data-testid="subing-performance-tab-trend"
              :type="activeTab === 'trend' ? 'primary' : 'default'"
              @click="activeTab = 'trend'"
            >走势</NButton>
            <NButton
              data-testid="subing-performance-tab-analysis"
              :type="activeTab === 'analysis' ? 'primary' : 'default'"
              @click="activeTab = 'analysis'"
            >收益分析</NButton>
          </NButtonGroup>
          <p class="coverage">
            {{ result.coverage.since }} 至 {{ result.coverage.through }} ·
            {{ result.coverage.segment_count }} 个主力区间 ·
            {{ result.coverage.bar_count_15m }} 根 15m Bar ·
            {{ result.summary.open_episodes }} 个持仓中 Episode ·
            缓存 {{ result.cache_state === 'hit' ? '命中' : result.cache_state === 'refreshed' ? '已刷新' : '不可用' }}
          </p>
        </div>

        <section v-if="activeTab === 'trend'" class="trend" data-testid="subing-performance-trend">
          <div class="trend-head">
            <div class="trend-head__title">
              <h4>累计参考变动走势</h4>
              <strong :class="`tone-${cumulativeTone}`">{{ trend.kpis.cumulativeLabel }}</strong>
            </div>
            <NButton text size="small" data-testid="subing-performance-view-details" @click="showAnalysis">
              查看明细
            </NButton>
          </div>
          <NButtonGroup size="small" class="ranges" aria-label="统计区间">
            <NButton
              v-for="item in SUBING_PERFORMANCE_RANGE_OPTIONS"
              :key="item.id"
              :type="selectedRange === item.id ? 'primary' : 'default'"
              @click="selectedRange = item.id"
            >{{ item.label }}</NButton>
          </NButtonGroup>
          <SubingPerformanceTrendChart :points="trend.points" />
          <div class="kpis" data-testid="subing-performance-kpis">
            <article>
              <strong :class="`tone-${cumulativeTone}`">{{ trend.kpis.cumulativeLabel }}</strong>
              <span>累计参考变动</span>
            </article>
            <article>
              <strong>{{ trend.kpis.winRateLabel }}</strong>
              <span>正向率</span>
            </article>
            <article>
              <strong>{{ trend.kpis.bestWorstLabel }}</strong>
              <span>最好 / 最差</span>
            </article>
            <article>
              <strong>{{ trend.kpis.completedLabel }}</strong>
              <span>已完成</span>
            </article>
          </div>
        </section>

        <template v-else>
          <div class="stats" data-testid="subing-performance-analysis">
            <article v-for="item in [row('全部', result.summary.overall), row('多向', result.summary.long), row('空向', result.summary.short)]" :key="item.label">
              <strong>{{ item.label }}</strong>
              <dl>
                <div><dt>已完成</dt><dd>{{ item.stats.completed }}</dd></div>
                <div><dt>正向 / 负向 / 持平</dt><dd>{{ item.stats.positive }} / {{ item.stats.negative }} / {{ item.stats.flat }}</dd></div>
                <div><dt>正向率</dt><dd>{{ percent(item.stats.positive_rate_percent) }}</dd></div>
                <div><dt>平均参考变动</dt><dd>{{ percent(item.stats.mean_reference_change_percent) }}</dd></div>
                <div><dt>中位参考变动</dt><dd>{{ percent(item.stats.median_reference_change_percent) }}</dd></div>
                <div><dt>最好 / 最差</dt><dd>{{ percent(item.stats.best_reference_change_percent) }} / {{ percent(item.stats.worst_reference_change_percent) }}</dd></div>
                <div><dt>平均持有</dt><dd>{{ formatSubingMeanHoldingBars(item.stats.mean_holding_15m_bars) }} 根</dd></div>
              </dl>
            </article>
          </div>
          <section class="exit-reasons" data-testid="subing-performance-exit-reasons">
            <strong>退出原因</strong>
            <p v-if="exitReasonRows.length === 0">暂无已完成 Episode 的退出原因</p>
            <dl v-else>
              <div v-for="reason in exitReasonRows" :key="reason.code">
                <dt>{{ reason.label }}</dt><dd>{{ reason.count }}</dd>
              </div>
            </dl>
          </section>
        </template>

        <p class="disclaimer">统计仅基于策略参考价变动，不代表账户收益、资金曲线或交易指令。</p>
        <SubingStrategyRecords
          :episodes="visibleEpisodes"
          :current-episode="null"
          :latest-completed-episode="null"
          :current-loading="false"
          :current-error="null"
          :loading="false"
          :error="null"
        />
        <NButton
          v-if="hasMoreEpisodes"
          data-testid="subing-performance-show-more"
          secondary
          @click="showMoreEpisodes"
        >再显示 20 条</NButton>
      </template>
    </NSpin>
  </section>
</template>

<style scoped>
.performance { display: grid; gap: 12px; padding: 14px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); }
header { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
header span, .coverage, .disclaimer { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
header h3, p, h4 { margin: 0; }
.panel-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.coverage { margin: 0; }
.trend { display: grid; gap: 10px; }
.trend-head { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.trend-head__title { display: flex; align-items: baseline; gap: 8px; }
.trend-head h4 { font-size: var(--gy-font-size-sm); font-weight: 600; }
.trend-head strong { font-family: var(--gy-font-mono); font-size: var(--gy-font-size-lg); }
.ranges { justify-self: center; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; border-top: 1px solid var(--gy-border); }
.kpis article { display: grid; gap: 4px; padding: 12px 8px; text-align: center; border-right: 1px solid var(--gy-border); }
.kpis article:last-child { border-right: 0; }
.kpis strong { font-family: var(--gy-font-mono); font-size: var(--gy-font-size-lg); }
.kpis span { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.tone-up { color: var(--gy-up); }
.tone-down { color: var(--gy-down); }
.tone-neutral { color: var(--gy-text-primary); }
.stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 12px 0; }
.stats article { padding: 10px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); }
.exit-reasons { display: grid; gap: 8px; }
.exit-reasons p { color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
dl { display: grid; gap: 5px; margin: 8px 0 0; }
dl div { display: flex; justify-content: space-between; gap: 8px; }
dt { color: var(--gy-text-muted); } dd { margin: 0; font-family: var(--gy-font-mono); text-align: right; }
.warning { color: var(--gy-status-warning); }
@media (max-width: 760px) {
  .stats { grid-template-columns: 1fr; }
  .kpis { grid-template-columns: 1fr 1fr; }
  .kpis article:nth-child(2) { border-right: 0; }
}
</style>
