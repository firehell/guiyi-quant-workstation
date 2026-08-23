<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NAlert, NButton, NSpin, NTag } from 'naive-ui'
import PageShell from '@/components/common/PageShell.vue'
import BacktestRunForm from '@/components/backtests/BacktestRunForm.vue'
import BacktestRecentRuns from '@/components/backtests/BacktestRecentRuns.vue'
import BacktestRunDetail from '@/components/backtests/BacktestRunDetail.vue'
import { backtestClient, mapBacktestError } from '@/api/backtests'
import {
  BacktestPoller,
  isLocalBacktestHostname,
  probeBacktestCapability,
} from '@/utils/backtestCapability'
import type {
  ArtifactKind,
  BacktestCapability,
  BacktestRunDetail as BacktestRunDetailValue,
  BacktestRunForm as BacktestRunFormValue,
  BacktestRunSummary,
  BacktestSafeError,
  BacktestStrategy,
} from '@/types/backtest'

const hostname = window.location.hostname
const localBrowser = isLocalBacktestHostname(hostname)
const capability = ref<BacktestCapability | null>(localBrowser ? null : {
  kind: 'remote_blocked',
  showMenu: false,
  canStart: false,
  health: null,
  error: null,
})
const loading = ref(localBrowser)
const submitting = ref(false)
const strategies = ref<BacktestStrategy[]>([])
const runs = ref<BacktestRunSummary[]>([])
const selectedRunId = ref<string | null>(null)
const selectedRun = ref<BacktestRunDetailValue | null>(null)
const pageError = ref<BacktestSafeError | null>(null)
const downloadingKind = ref<ArtifactKind | null>(null)

const poller = new BacktestPoller(
  (runId) => backtestClient.getRun(runId),
  (run) => {
    selectedRun.value = run
    const index = runs.value.findIndex(({ run_id }) => run_id === run.run_id)
    if (index >= 0) runs.value[index] = run
    else runs.value.unshift(run)
  },
  { onError: (error) => { pageError.value = error } },
)

const equityImageUrl = computed(() => {
  const run = selectedRun.value
  if (!run?.result?.artifacts.equity_png) return null
  return backtestClient.artifactUrl(run.run_id, 'equity_png')
})

async function loadCapability() {
  if (!localBrowser) return
  loading.value = true
  pageError.value = null
  poller.stop()
  capability.value = await probeBacktestCapability(hostname, () => backtestClient.health())
  if (capability.value.kind !== 'ready') {
    loading.value = false
    return
  }
  try {
    const [strategyRows, runRows] = await Promise.all([
      backtestClient.listStrategies(),
      backtestClient.listRuns(20),
    ])
    strategies.value = strategyRows
    runs.value = runRows
    if (runRows[0]) selectRun(runRows[0])
  } catch (error) {
    pageError.value = mapBacktestError(error)
  } finally {
    loading.value = false
  }
}

function selectRun(run: BacktestRunSummary) {
  pageError.value = null
  selectedRunId.value = run.run_id
  selectedRun.value = null
  poller.start(run.run_id)
}

async function startRun(form: BacktestRunFormValue) {
  if (!capability.value?.canStart || submitting.value) return
  submitting.value = true
  pageError.value = null
  try {
    const run = await backtestClient.startRun(form)
    runs.value = [run, ...runs.value.filter(({ run_id }) => run_id !== run.run_id)]
    selectRun(run)
  } catch (error) {
    pageError.value = mapBacktestError(error)
  } finally {
    submitting.value = false
  }
}

async function downloadArtifact(kind: ArtifactKind) {
  const run = selectedRun.value
  if (!run || !localBrowser || downloadingKind.value) return
  downloadingKind.value = kind
  pageError.value = null
  try {
    const response = await fetch(backtestClient.artifactUrl(run.run_id, kind))
    if (!response.ok) throw new Error('artifact unavailable')
    const blobUrl = URL.createObjectURL(await response.blob())
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0)
    const anchor = document.createElement('a')
    anchor.href = blobUrl
    anchor.download = artifactFilename(run.run_id, kind)
    anchor.hidden = true
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } catch (error) {
    pageError.value = mapBacktestError(error)
  } finally {
    downloadingKind.value = null
  }
}

function artifactFilename(runId: string, kind: ArtifactKind) {
  const safeRunId = runId.replace(/[^A-Za-z0-9_-]/g, '_')
  const suffixes: Record<ArtifactKind, string> = {
    report_zip: 'report.zip',
    result_pickle: 'result.pkl',
    equity_png: 'equity.png',
    stdout_log: 'stdout.log',
    stderr_log: 'stderr.log',
    run_json: 'run.json',
  }
  return `${safeRunId}-${suffixes[kind]}`
}

onMounted(() => { void loadCapability() })
onUnmounted(() => poller.dispose())
</script>

<template>
  <PageShell
    class="backtests-page"
    title="RQAlpha 研究回测"
    subtitle="本机外部研究工具；结果不进入 Canonical、OOS 或候选晋升链。"
    data-testid="backtests-page"
  >
    <template #badges>
      <NTag size="small" type="warning">本机研究工具·不是正式证据</NTag>
      <NTag size="small" :bordered="false">auto_order=false</NTag>
    </template>

    <NAlert
      v-if="capability?.kind === 'remote_blocked'"
      data-testid="backtest-remote-blocked"
      type="warning"
      title="仅本机可用"
    >
      当前页面不是 localhost 或 127.0.0.1，回测菜单、探测和启动功能已关闭。
    </NAlert>

    <div v-else-if="loading" class="backtests-page__loading" role="status">
      <NSpin size="small" />
      <span>正在检查本机回测服务…</span>
    </div>

    <NAlert
      v-else-if="capability?.kind === 'local_unavailable'"
      data-testid="backtest-unavailable"
      type="warning"
      title="仅本机可用，当前服务未就绪"
    >
      <p>{{ capability.error?.message ?? '本机回测服务不可用。' }}</p>
      <p>检查 <code>VITE_BACKTEST_API_BASE_URL=http://127.0.0.1:8011/api/v1/backtests</code> 及 Git 外运行配置。</p>
      <p>由 operator 在 quant-api 目录执行 <code>python -m app.backtest.local_app</code> 后重试。</p>
      <NButton data-testid="retry-backtest-capability" size="small" type="warning" @click="loadCapability">重试检查</NButton>
    </NAlert>

    <template v-else-if="capability?.kind === 'ready'">
      <NAlert v-if="pageError" type="error" :bordered="false" class="backtests-page__error">
        {{ pageError.message }}
      </NAlert>
      <div class="backtests-page__top">
        <BacktestRunForm
          :strategies="strategies"
          :can-start="capability.canStart"
          :submitting="submitting"
          @start="startRun"
        />
        <BacktestRecentRuns
          :runs="runs"
          :selected-run-id="selectedRunId"
          @select="selectRun"
        />
      </div>
      <BacktestRunDetail
        :run="selectedRun"
        :equity-image-url="equityImageUrl"
        :downloading-kind="downloadingKind"
        @download="downloadArtifact"
      />
    </template>
  </PageShell>
</template>

<style scoped>
.backtests-page { padding: var(--gy-content-padding); }
.backtests-page__loading { display: flex; align-items: center; gap: 8px; color: var(--gy-text-muted); }
.backtests-page__error { margin-bottom: 12px; }
.backtests-page__top { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 14px; margin-bottom: 14px; align-items: start; }
code { font-family: var(--gy-font-mono); overflow-wrap: anywhere; }

@media (max-width: 1100px) {
  .backtests-page__top { grid-template-columns: 1fr; }
}
</style>
