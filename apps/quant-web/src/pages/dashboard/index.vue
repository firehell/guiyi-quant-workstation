<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NTag } from 'naive-ui'
import { getDashboardSummary } from '@/api/dashboard'
import LiveTargetPanel from '@/components/market/LiveTargetPanel.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageShell from '@/components/common/PageShell.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import type { DashboardSummary } from '@/types/dashboard'

const router = useRouter()
const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<DashboardSummary | null>(null)

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  loading.value = true
  error.value = null
  try {
    summary.value = await getDashboardSummary()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载仪表盘失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageShell title="仪表盘" subtitle="V1-B 研究闭环总览" :error="error" :loading="loading">
    <template #actions>
      <NButton size="small" :loading="loading" @click="load">刷新</NButton>
    </template>

    <template #status>
      <div v-if="summary" class="gy-status-strip dashboard-status-strip">
        <span class="gy-status-strip__item">
          <span class="gy-dot gy-dot--ok" />
          数据状态
          <StatusTag :status="summary.data_status" domain="quality" />
        </span>
        <span class="gy-status-strip__item">
          Live Target
          <StatusTag :status="summary.live_target_readiness || 'unknown'" domain="system" />
        </span>
        <span class="gy-status-strip__item">更新于 {{ formatDateTime(summary.generated_at) }}</span>
        <strong class="dashboard-boundary">仅供研究与复盘，不自动下单</strong>
      </div>
    </template>

    <template v-if="summary">
      <section class="dashboard-metrics" aria-label="研究闭环指标">
        <MetricCard label="今日信号" :value="summary.signals_today" :meta="`近 7 日 ${summary.signals_week}`" />
        <MetricCard label="策略数" :value="summary.strategies" :meta="`V1-B ${summary.v1b_strategies}`">
          <template #badge><NTag size="tiny" type="info">V1-B</NTag></template>
        </MetricCard>
        <MetricCard
          label="回测任务"
          :value="summary.backtests"
          :meta="`报告 ${summary.backtest_reports} · 成功 ${summary.backtest_reports_success}`"
        />
        <MetricCard
          label="Primary 合约"
          :value="summary.data_contracts"
          :meta="`JM passed 资产 ${summary.jm_primary_passed_assets}`"
        />
      </section>

      <section class="dashboard-main-grid">
        <NCard title="快捷入口与最近任务" size="small" class="dashboard-card">
          <div class="dashboard-actions">
            <NButton type="primary" @click="router.push({ name: 'backtest' })">JM V1-B 回测</NButton>
            <NButton @click="router.push({ name: 'signal' })">信号监控</NButton>
            <NButton @click="router.push({ name: 'market' })">行情看板</NButton>
            <NButton @click="router.push({ name: 'data' })">数据中心</NButton>
          </div>

          <div class="recent-list">
            <div v-if="summary.latest_jm_report" class="recent-item">
              <div>
                <span class="recent-item__label">最新 JM 回测报告</span>
                <strong>#{{ summary.latest_jm_report.report_id }} · {{ summary.latest_jm_report.report_no }}</strong>
                <small>{{ formatDateTime(summary.latest_jm_report.created_at) }}</small>
              </div>
              <div class="recent-item__actions">
                <StatusTag :status="summary.latest_jm_report.status" domain="task" />
                <NButton
                  text
                  type="primary"
                  @click="router.push({ name: 'backtest', query: { report_id: String(summary.latest_jm_report?.report_id) } })"
                >
                  查看报告
                </NButton>
              </div>
            </div>
            <div v-if="summary.latest_scan_task" class="recent-item">
              <div>
                <span class="recent-item__label">最近信号扫描</span>
                <strong>{{ summary.latest_scan_task.task_no }}</strong>
                <small>{{ summary.latest_scan_task.watchlist_code }} · {{ formatDateTime(summary.latest_scan_task.created_at) }}</small>
              </div>
              <div class="recent-item__actions">
                <StatusTag :status="summary.latest_scan_task.status" domain="task" />
                <span class="gy-number">{{ summary.latest_scan_task.progress }}%</span>
              </div>
            </div>
            <div v-if="!summary.latest_jm_report && !summary.latest_scan_task" class="recent-empty">暂无最近任务记录</div>
          </div>
        </NCard>

        <NCard title="系统与数据边界" size="small" class="dashboard-card">
          <div class="dashboard-state-list">
            <div><span>数据状态</span><StatusTag :status="summary.data_status" domain="quality" /></div>
            <div><span>当前用途标记</span><NTag size="small" type="info">{{ summary.risk_status }}</NTag></div>
            <div><span>Live Target</span><StatusTag :status="summary.live_target_readiness || 'unknown'" domain="system" /></div>
            <div><span>JM primary passed</span><strong class="gy-number">{{ summary.jm_primary_passed_assets }} 资产</strong></div>
          </div>
          <NAlert type="info" :bordered="false" class="dashboard-note">
            状态与方向分开表达；回测可信通过不代表策略盈利或可进入实盘。
          </NAlert>
        </NCard>
      </section>

      <section class="dashboard-live">
        <LiveTargetPanel compact />
      </section>
    </template>
  </PageShell>
</template>

<style scoped>
.dashboard-status-strip {
  justify-content: flex-start;
}

.dashboard-boundary {
  margin-left: auto;
  color: var(--gy-status-warning);
  font-size: var(--gy-font-size-sm);
  font-weight: 600;
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--gy-space-4);
}

.dashboard-main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
  gap: var(--gy-space-4);
  margin-top: var(--gy-space-4);
}

.dashboard-card {
  min-width: 0;
}

.dashboard-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gy-space-2);
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-2);
  margin-top: var(--gy-space-4);
}

.recent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gy-space-4);
  min-width: 0;
  padding: 11px 12px;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border-subtle);
  border-radius: var(--gy-radius-md);
}

.recent-item > div:first-child,
.recent-item__actions {
  display: flex;
}

.recent-item > div:first-child {
  flex-direction: column;
  min-width: 0;
  gap: 3px;
}

.recent-item strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-item small,
.recent-item__label,
.recent-empty {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.recent-item__actions {
  align-items: center;
  gap: var(--gy-space-3);
  flex: 0 0 auto;
}

.dashboard-state-list {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-2);
}

.dashboard-state-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gy-space-3);
  min-height: 35px;
  padding: 6px 9px;
  background: var(--gy-bg-panel-strong);
  border-radius: var(--gy-radius-sm);
}

.dashboard-state-list span {
  color: var(--gy-text-secondary);
}

.dashboard-note {
  margin-top: var(--gy-space-3);
}

.dashboard-live {
  margin-top: var(--gy-space-4);
}

@media (max-width: 1199px) {
  .dashboard-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-main-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-boundary {
    width: 100%;
    margin-left: 0;
  }
}
</style>
