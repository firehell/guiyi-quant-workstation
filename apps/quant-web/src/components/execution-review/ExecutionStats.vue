<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NCollapse, NCollapseItem, NSpin } from 'naive-ui'
import type { ExecutionReviewStatsResponse } from '@/types/executionReview'

const props = defineProps<{
  stats: ExecutionReviewStatsResponse | null
  loading: boolean
  error: string
}>()

const opportunityMetrics = computed(() => {
  if (!props.stats) return []
  const value = props.stats.opportunities
  return [
    ['符合机会', value.eligible_events],
    ['已决策', value.processed_events],
    ['待决策', value.pending_events],
    ['已执行', value.executed_decisions],
    ['未执行', value.not_executed_decisions],
    ['决策完成率', formatRate(value.decision_completion_rate)],
    ['执行率', formatRate(value.execution_rate)],
  ]
})

const episodeMetrics = computed(() => {
  if (!props.stats) return []
  const value = props.stats.episode_states
  return [
    ['进行中', value.open_episodes],
    ['待复盘', value.pending_review_episodes],
    ['已完成', value.done_episodes],
  ]
})

const issueGroups = computed(() => {
  if (!props.stats) return []
  return [
    ['Entry', props.stats.review_issue_top.entry],
    ['Holding', props.stats.review_issue_top.holding],
    ['Exit / Risk', props.stats.review_issue_top.exit_risk],
    ['Psychology', props.stats.review_issue_top.psychology],
  ] as const
})

function formatRate(value: string | null): string {
  if (value === null) return '—'
  const percent = Number(value) * 100
  return Number.isFinite(percent) ? `${Number(percent.toFixed(1))}%` : '—'
}

function counts(value: Record<string, number>): string {
  const entries = Object.entries(value)
  return entries.length ? entries.map(([label, count]) => `${label} ${count}`).join(' · ') : '无'
}
</script>

<template>
  <section data-testid="execution-stats">
    <NCollapse :default-expanded-names="['execution-stats']">
      <NCollapseItem name="execution-stats" title="ExecutionStats / 执行复盘统计">
        <NSpin :show="loading">
          <NAlert v-if="error" type="warning">统计暂不可用；交易记录工作区不受影响。</NAlert>
          <div v-else-if="stats" class="execution-stats__content">
            <div class="execution-stats__group">
              <strong>机会与决策</strong>
              <div class="execution-stats__metrics">
                <span v-for="([label, value]) in opportunityMetrics" :key="label"><small>{{ label }}</small><b>{{ value }}</b></span>
              </div>
            </div>
            <div class="execution-stats__group">
              <strong>Episode 状态</strong>
              <div class="execution-stats__metrics execution-stats__metrics--episodes">
                <span v-for="([label, value]) in episodeMetrics" :key="label"><small>{{ label }}</small><b>{{ value }}</b></span>
              </div>
            </div>
            <div class="execution-stats__group">
              <strong>复盘问题标签</strong>
              <div class="execution-stats__issues">
                <span v-for="([label, value]) in issueGroups" :key="label"><small>{{ label }}</small><b>{{ counts(value) }}</b></span>
              </div>
            </div>
          </div>
        </NSpin>
      </NCollapseItem>
    </NCollapse>
  </section>
</template>

<style scoped>
.execution-stats__content { display: grid; grid-template-columns: 1.3fr .7fr 1fr; gap: 16px; }.execution-stats__group { display: grid; align-content: start; gap: 8px; min-width: 0; }.execution-stats__metrics { display: grid; grid-template-columns: repeat(4, minmax(72px, 1fr)); gap: 6px; }.execution-stats__metrics--episodes { grid-template-columns: repeat(3, minmax(72px, 1fr)); }.execution-stats__metrics span, .execution-stats__issues span { display: grid; gap: 2px; padding: 8px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-sm); background: var(--gy-bg-panel); }.execution-stats__metrics small, .execution-stats__issues small { color: var(--gy-text-muted); }.execution-stats__metrics b { font-size: var(--gy-font-size-md); }.execution-stats__issues { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }.execution-stats__issues b { overflow-wrap: anywhere; font-size: var(--gy-font-size-xs); font-weight: 500; }
@media (max-width: 1180px) { .execution-stats__content { grid-template-columns: 1fr; }.execution-stats__metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 640px) { .execution-stats__metrics, .execution-stats__metrics--episodes, .execution-stats__issues { grid-template-columns: 1fr 1fr; } }
</style>
