<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NEmpty, NTag } from 'naive-ui'
import {
  backtestRunStatusLabel,
  backtestRunStatusTagType,
  formatBacktestDuration,
  isBacktestFailureStatus,
  visibleBacktestArtifacts,
} from '@/utils/backtestPresentation'
import type { ArtifactKind, BacktestRunDetail } from '@/types/backtest'

const props = defineProps<{
  run: BacktestRunDetail | null
  equityImageUrl: string | null
  downloadingKind: ArtifactKind | null
}>()

const emit = defineEmits<{
  download: [kind: ArtifactKind]
}>()

const ARTIFACT_LABELS: Record<ArtifactKind, string> = {
  report_zip: '下载 report.zip',
  result_pickle: '下载 result.pkl',
  equity_png: '下载收益图',
  stdout_log: '下载 stdout',
  stderr_log: '下载 stderr',
  run_json: '下载 run.json',
}

const availableArtifacts = computed(() => {
  return props.run ? visibleBacktestArtifacts(props.run) : []
})

function percent(value: string) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(2)}%` : '—'
}

function configJson(run: BacktestRunDetail, effective: boolean) {
  return JSON.stringify(
    effective
      ? { config: run.effective_config, parameters: run.effective_parameters }
      : run.requested_config,
    null,
    2,
  )
}
</script>

<template>
  <section class="run-detail" data-testid="backtest-run-detail" aria-labelledby="run-detail-heading">
    <h3 id="run-detail-heading">运行详情</h3>
    <NEmpty v-if="!run" description="选择一次回测查看详情" />
    <template v-else>
      <header class="run-detail__header">
        <div>
          <strong>{{ run.strategy_name }}</strong>
          <small class="gy-number">{{ run.run_id }}</small>
        </div>
        <NTag :type="backtestRunStatusTagType(run.status)">
          {{ backtestRunStatusLabel(run.status) }}
        </NTag>
      </header>

      <div class="run-detail__metadata" data-testid="backtest-run-metadata">
        <article><span>耗时</span><strong>{{ formatBacktestDuration(run) }}</strong></article>
        <template v-if="isBacktestFailureStatus(run.status)">
          <article><span>失败代码</span><strong>{{ run.failure_code ?? '—' }}</strong></article>
          <article><span>退出码</span><strong>{{ run.exit_code ?? '—' }}</strong></article>
        </template>
      </div>

      <div v-if="run.result" class="run-detail__summary" data-testid="backtest-summary">
        <article><span>总收益</span><strong>{{ percent(run.result.summary.total_returns) }}</strong></article>
        <article><span>年化收益</span><strong>{{ percent(run.result.summary.annualized_returns) }}</strong></article>
        <article><span>最大回撤</span><strong>{{ percent(run.result.summary.max_drawdown) }}</strong></article>
        <article><span>Sharpe</span><strong>{{ run.result.summary.sharpe }}</strong></article>
        <article><span>Sortino</span><strong>{{ run.result.summary.sortino }}</strong></article>
        <article><span>成交数</span><strong>{{ run.result.trade_count }}</strong></article>
      </div>

      <figure v-if="equityImageUrl && run.result?.artifacts.equity_png" class="run-detail__equity">
        <figcaption>RQAlpha 生成的收益图</figcaption>
        <img data-testid="equity-image" :src="equityImageUrl" alt="RQAlpha 回测收益图">
      </figure>

      <div class="run-detail__configs">
        <section>
          <h4>请求配置</h4>
          <pre data-testid="requested-config">{{ configJson(run, false) }}</pre>
        </section>
        <section>
          <h4>实际配置</h4>
          <pre data-testid="effective-config">{{ configJson(run, true) }}</pre>
        </section>
      </div>

      <div class="run-detail__logs">
        <section><h4>stdout 尾部</h4><pre data-testid="stdout-tail">{{ run.stdout_tail || '（空）' }}</pre></section>
        <section><h4>stderr 尾部</h4><pre data-testid="stderr-tail">{{ run.stderr_tail || '（空）' }}</pre></section>
      </div>

      <div v-if="availableArtifacts.length" class="run-detail__downloads" aria-label="回测产物下载">
        <NButton
          v-for="kind in availableArtifacts"
          :key="kind"
          size="small"
          secondary
          :loading="downloadingKind === kind"
          :data-testid="`artifact-download-${kind}`"
          @click="emit('download', kind)"
        >
          {{ ARTIFACT_LABELS[kind] }}
        </NButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.run-detail {
  min-width: 0; padding: var(--gy-panel-padding); background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); box-shadow: var(--gy-shadow-panel);
}
h3 { margin: 0 0 12px; font-size: var(--gy-font-size-lg); }
h4 { margin: 0 0 6px; font-size: var(--gy-font-size-base); }
.run-detail__header { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.run-detail__header div { display: grid; }
.run-detail__header small { color: var(--gy-text-muted); }
.run-detail__metadata { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 14px; }
.run-detail__metadata article { display: flex; gap: 6px; }
.run-detail__metadata span { color: var(--gy-text-muted); }
.run-detail__metadata strong { font-family: var(--gy-font-mono); }
.run-detail__summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 16px; }
.run-detail__summary article { display: grid; gap: 4px; padding: 10px; background: var(--gy-bg-panel-strong); border-radius: var(--gy-radius-md); }
.run-detail__summary span { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.run-detail__summary strong { font-family: var(--gy-font-mono); font-size: var(--gy-font-size-lg); }
.run-detail__equity { margin: 0 0 16px; }
.run-detail__equity figcaption { margin-bottom: 6px; color: var(--gy-text-secondary); font-weight: 600; }
.run-detail__equity img { display: block; width: 100%; max-height: 420px; object-fit: contain; background: white; border: 1px solid var(--gy-border); }
.run-detail__configs, .run-detail__logs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
pre { min-height: 74px; max-height: 240px; margin: 0; padding: 10px; overflow: auto; color: var(--gy-text-secondary); background: var(--gy-gray-50); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); font: 11px/1.5 var(--gy-font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.run-detail__downloads { display: flex; flex-wrap: wrap; gap: 8px; }

@media (max-width: 900px) {
  .run-detail__summary, .run-detail__configs, .run-detail__logs { grid-template-columns: 1fr; }
}
</style>
