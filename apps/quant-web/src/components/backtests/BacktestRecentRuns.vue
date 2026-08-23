<script setup lang="ts">
import { NEmpty, NTag } from 'naive-ui'
import type { BacktestRunSummary } from '@/types/backtest'

defineProps<{
  runs: BacktestRunSummary[]
  selectedRunId: string | null
}>()

const emit = defineEmits<{
  select: [run: BacktestRunSummary]
}>()

const STATUS_LABELS = {
  running: '运行中',
  succeeded: '已成功',
  failed: '失败',
  timed_out: '已超时',
  interrupted: '已中断',
} as const
</script>

<template>
  <section class="recent-runs" data-testid="recent-runs" aria-labelledby="recent-runs-heading">
    <h3 id="recent-runs-heading">最近运行</h3>
    <NEmpty v-if="!runs.length" description="暂无回测记录" size="small" />
    <div v-else class="recent-runs__list">
      <button
        v-for="run in runs"
        :key="run.run_id"
        type="button"
        class="recent-runs__item"
        :class="{ 'recent-runs__item--selected': selectedRunId === run.run_id }"
        @click="emit('select', run)"
      >
        <span><strong>{{ run.strategy_name }}</strong><small>{{ run.started_at }}</small></span>
        <NTag size="small" :type="run.status === 'succeeded' ? 'success' : run.status === 'running' ? 'info' : 'error'">
          {{ STATUS_LABELS[run.status] }}
        </NTag>
      </button>
    </div>
  </section>
</template>

<style scoped>
.recent-runs {
  padding: var(--gy-panel-padding);
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  box-shadow: var(--gy-shadow-panel);
}
h3 { margin: 0 0 12px; font-size: var(--gy-font-size-lg); }
.recent-runs__list { display: grid; gap: 8px; }
.recent-runs__item {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px; text-align: left; color: var(--gy-text-primary); background: var(--gy-bg-panel-strong);
  border: 1px solid transparent; border-radius: var(--gy-radius-md); cursor: pointer;
}
.recent-runs__item:hover, .recent-runs__item--selected { border-color: var(--gy-accent); background: var(--gy-accent-soft); }
.recent-runs__item span { display: grid; min-width: 0; }
.recent-runs__item strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-runs__item small { color: var(--gy-text-muted); font-family: var(--gy-font-mono); }
</style>
