<script setup lang="ts">
/** 仪表盘：聚合 V1-B 研究闭环指标与最近任务状态。 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NTag } from 'naive-ui'
import { getDashboardSummary } from '@/api/dashboard'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageShell from '@/components/common/PageShell.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import type { DashboardSummary } from '@/types/dashboard'
import { toSafeApiError } from '@/utils/errorRedaction'
import { useRuntimePulseStore } from '@/stores/runtimePulse'
import {
  buildDashboardActions,
  formatDashboardTimestamp,
  type DashboardAction,
} from '@/utils/dashboardAction'

const router = useRouter()
const runtimePulse = useRuntimePulseStore()
const { health: runtimeHealth, status: runtimeStatus } = storeToRefs(runtimePulse)
const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<DashboardSummary | null>(null)

const actions = computed(() =>
  buildDashboardActions({
    runtimeStatus: runtimeStatus.value,
    afterMarketStatus: runtimeHealth.value?.components.after_market_scheduler?.status,
    dataStatus: summary.value?.data_status,
    latestLiveSignalEvent: summary.value?.latest_live_signal_event,
    unfinishedReviewCount: summary.value?.unfinished_review_count ?? 0,
  }),
)

function openAction(action: DashboardAction) {
  void router.push({ name: action.to.name, query: action.to.query })
}

/** 拉取仪表盘汇总；失败时写入 error 供 PageShell 展示。 */
async function load() {
  loading.value = true
  error.value = null
  try {
    summary.value = await getDashboardSummary()
  } catch (err) {
    error.value = toSafeApiError(err, '加载仪表盘失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <PageShell title="今日工作台" subtitle="按明确事实排序的个人研究行动入口" :error="error" :loading="loading" @retry="load">
    <template #badges>
      <CapabilityBadge kind="formal-research" />
      <CapabilityBadge kind="research-only" label="非自动交易" />
    </template>
    <template #actions>
      <NButton size="small" :loading="loading" aria-label="刷新仪表盘" @click="load">刷新</NButton>
    </template>

    <template #status>
      <div v-if="summary" class="gy-status-strip dashboard-status-strip">
        <span class="gy-status-strip__item">
          数据状态
          <StatusTag :status="summary.data_status" domain="quality" />
        </span>
        <span class="gy-status-strip__item">
          Live Target
          <StatusTag :status="summary.live_target_readiness || 'unknown'" domain="system" />
        </span>
        <span class="gy-status-strip__item">
          Runtime
          <StatusTag :status="runtimeStatus" domain="system" />
        </span>
        <span class="gy-status-strip__item">数据至 {{ formatDashboardTimestamp(summary.latest_data_time) }}</span>
        <span class="gy-status-strip__item">确认 Bar {{ formatDashboardTimestamp(summary.latest_confirmed_bar_time)
        }}</span>
        <strong class="dashboard-boundary">仅供研究与复盘，不自动下单</strong>
      </div>
    </template>

    <template v-if="summary">
      <section class="dashboard-main-grid">
        <section aria-label="建议动作">
          <NCard title="建议动作" size="small" class="dashboard-card">
            <div class="dashboard-action-list">
              <article v-for="(action, index) in actions" :key="action.kind" class="dashboard-action-item">
                <span class="dashboard-action-item__rank">{{ String(index + 1).padStart(2, '0') }}</span>
                <div>
                  <strong>{{ action.title }}</strong>
                  <small>{{ action.detail }}</small>
                </div>
                <NButton :type="index === 0 ? 'primary' : 'default'" size="small" :aria-label="action.title"
                  @click="openAction(action)">
                  打开
                </NButton>
              </article>
            </div>
          </NCard>
        </section>

        <NCard title="最近研究事实" size="small" class="dashboard-card">
          <div class="recent-list recent-list--flush">
            <div v-if="summary.latest_live_signal_event" class="recent-item">
              <div>
                <span class="recent-item__label">最新 live-confirmed event</span>
                <strong>#{{ summary.latest_live_signal_event.event_id }} · {{ summary.latest_live_signal_event.contract
                }}</strong>
                <small>{{ summary.latest_live_signal_event.period }} · {{
                  formatDashboardTimestamp(summary.latest_live_signal_event.signal_time) }}</small>
              </div>
              <StatusTag :status="summary.latest_live_signal_event.lifecycle_status" domain="task" />
            </div>
            <div v-if="summary.latest_review" class="recent-item">
              <div>
                <span class="recent-item__label">最近复盘</span>
                <strong>#{{ summary.latest_review.review_id }} · {{ summary.latest_review.source_type }}</strong>
                <small>{{ summary.latest_review.contract || '-' }} · {{
                  formatDashboardTimestamp(summary.latest_review.updated_at) }}</small>
              </div>
              <NTag size="small" type="warning">待复盘 {{ summary.unfinished_review_count || 0 }}</NTag>
            </div>
            <div v-if="!summary.latest_live_signal_event && !summary.latest_review"
              class="recent-empty" role="status">
              暂无最近研究事实；可从 JM 15m 快捷入口开始浏览。
            </div>
          </div>
        </NCard>
      </section>

      <section class="dashboard-metrics" aria-label="研究闭环指标">
        <MetricCard label="今日信号" :value="summary.signals_today" :meta="`近 7 日 ${summary.signals_week}`" />
        <MetricCard label="策略数" :value="summary.strategies" :meta="`Registry ${summary.v1b_strategies} 条 V1-B 样板`">
          <template #badge>
            <CapabilityBadge kind="research-only" label="Registry≠validated" size="small" />
          </template>
        </MetricCard>
        <MetricCard label="Primary 合约" :value="summary.data_contracts"
          :meta="`JM passed 资产 ${summary.jm_primary_passed_assets}`" />
      </section>

      <NAlert type="info" :bordered="false" class="dashboard-note">
        unknown 不等于 failed；历史 replay 不参与 live 优先级；全部入口仅供研究与复盘。
      </NAlert>
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--gy-space-4);
  margin-top: var(--gy-space-4);
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

.dashboard-action-list {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-2);
}

.dashboard-action-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gy-space-3);
  padding: 11px 12px;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border-subtle);
  border-radius: var(--gy-radius-md);
}

.dashboard-action-item__rank {
  color: var(--gy-accent-hover);
  font-family: var(--gy-font-mono);
  font-size: var(--gy-font-size-xs);
}

.dashboard-action-item>div {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 3px;
}

.dashboard-action-item small {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-2);
  margin-top: var(--gy-space-4);
}

.recent-list--flush {
  margin-top: 0;
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

.recent-item>div:first-child,
.recent-item__actions {
  display: flex;
}

.recent-item>div:first-child {
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

.dashboard-note {
  margin-top: var(--gy-space-3);
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
