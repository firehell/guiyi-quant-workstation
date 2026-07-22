<script setup lang="ts">
/** 运行状态页：只读消费 /api/runtime/health，展示 DB/Redis/RQ/Checkpoint 等组件健康度。 */
import { computed, h, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NGrid,
  NGridItem,
  NStatistic,
  NTag,
  type DataTableColumns,
} from 'naive-ui'
import PageShell from '@/components/common/PageShell.vue'
import MarketRuntimeObservationPanel from '@/components/market/MarketRuntimeObservationPanel.vue'
import type { RuntimeCheckpointRow, RuntimeRqQueueHealth, RuntimeRqWorkerHealth } from '@/types/runtime'
import {
  formatCountMap,
  formatDateTime,
  formatLagSeconds,
  formatLatencyMs,
  readonlyFlagSummary,
  runtimeStatusType,
} from '@/utils/runtimeHealth'
import { buildMarketRuntimeObservation } from '@/utils/marketRuntimeObservation'
import { buildRuntimeHealthObservationInput } from '@/utils/runtimeObservationAdapter'
import type { MarketRuntimeObservationContext } from '@/types/marketRuntimeObservation'
import { useRuntimePulseStore } from '@/stores/runtimePulse'

const runtimePulse = useRuntimePulseStore()
const { loading, error, health } = storeToRefs(runtimePulse)

const overviewCards = computed(() => {
  if (!health.value) return []
  const components = health.value.components
  return [
    {
      label: 'PostgreSQL',
      status: components.db.status,
      detail: `latency ${formatLatencyMs(components.db.latency_ms)}`,
    },
    {
      label: 'Redis',
      status: components.redis.status,
      detail: `latency ${formatLatencyMs(components.redis.latency_ms)}`,
    },
    {
      label: 'RQ',
      status: components.rq.status,
      detail: `${components.rq.worker_count} workers`,
    },
    {
      label: 'Checkpoint',
      status: components.live_checkpoints.status,
      detail: `${components.live_checkpoints.ingest_count} ingest / ${components.live_checkpoints.aggregation_count} aggregation`,
    },
    {
      label: 'Notification Retry',
      status: components.notification_retry.status,
      detail: `${components.notification_retry.due_retry_count} due retry`,
    },
  ]
})

const readonlyFlags = computed(() => (health.value ? readonlyFlagSummary(health.value) : []))

const afterMarketScheduler = computed(() => health.value?.components.after_market_scheduler ?? null)

const observationContext = computed<MarketRuntimeObservationContext | null>(() => {
  if (!health.value) return null
  return buildMarketRuntimeObservation(buildRuntimeHealthObservationInput(health.value))
})

const latestErrorEntries = computed(() => {
  const latestError = health.value?.components.live_checkpoints.latest_error
  if (!latestError) return []
  return Object.entries(latestError).map(([key, value]) => ({ key, value: String(value ?? '-') }))
})

const queueColumns: DataTableColumns<RuntimeRqQueueHealth> = [
  { title: 'Queue', key: 'name', minWidth: 160 },
  {
    title: 'Status',
    key: 'status',
    width: 110,
    render: (row) => h(NTag, { size: 'small', type: runtimeStatusType(row.status) }, { default: () => row.status }),
  },
  { title: 'Queued', key: 'queued_count', width: 90 },
  { title: 'Started', key: 'started_count', width: 90 },
  { title: 'Failed', key: 'failed_count', width: 90 },
  { title: 'Deferred', key: 'deferred_count', width: 96 },
  { title: 'Scheduled', key: 'scheduled_count', width: 104 },
  { title: 'Error Type', key: 'error_type', minWidth: 140, render: (row) => row.error_type || '-' },
]

const workerColumns: DataTableColumns<RuntimeRqWorkerHealth> = [
  { title: 'Worker', key: 'name', minWidth: 180 },
  { title: 'State', key: 'state', width: 120, render: (row) => row.state || '-' },
  { title: 'Queues', key: 'queues', minWidth: 220, render: (row) => row.queues.join(', ') || '-' },
]

const checkpointColumns: DataTableColumns<RuntimeCheckpointRow> = [
  { title: 'Contract', key: 'contract_code', width: 110 },
  { title: 'Period', key: 'period', width: 84 },
  { title: 'Mode', key: 'source_mode', minWidth: 180 },
  {
    title: 'Status',
    key: 'status',
    width: 110,
    render: (row) => h(NTag, { size: 'small', type: runtimeStatusType(row.status) }, { default: () => row.status }),
  },
  { title: 'Lag', key: 'lag_seconds', width: 90, render: (row) => formatLagSeconds(row.lag_seconds) },
  { title: 'Errors', key: 'consecutive_error_count', width: 88 },
  { title: 'Last Bar', key: 'last_bar_at', minWidth: 172, render: (row) => formatDateTime(row.last_bar_at) },
  { title: 'Last Success', key: 'last_success_at', minWidth: 172, render: (row) => formatDateTime(row.last_success_at) },
  { title: 'Error Type', key: 'last_error_type', minWidth: 132, render: (row) => row.last_error_type || '-' },
]

/** 拉取运行时健康快照；失败 fail-closed 展示 error。 */
async function load() {
  await runtimePulse.refresh(true)
}

onMounted(() => {
  void runtimePulse.refresh()
})
</script>

<template>
  <PageShell title="运行状态" subtitle="只读消费 /api/runtime/health，不启动服务、不入队任务、不发送提醒" :error="error" :loading="loading">
    <template #actions>
      <NButton size="small" :loading="loading" @click="load">刷新</NButton>
    </template>

    <template v-if="health">
      <NAlert class="runtime-boundary" type="info" :bordered="false">
        <div class="runtime-boundary__inner">
          <span>运行态观察页</span>
          <NTag
            v-for="flag in readonlyFlags"
            :key="flag.label"
            size="small"
            :type="flag.value === flag.expected ? 'success' : 'error'"
          >
            {{ flag.label }}={{ String(flag.value) }}
          </NTag>
        </div>
      </NAlert>

      <NCard v-if="observationContext" size="small" class="runtime-section" title="Observation Foundation">
        <MarketRuntimeObservationPanel :context="observationContext" />
      </NCard>

      <NGrid :cols="6" :x-gap="12" :y-gap="12" responsive="screen">
        <NGridItem :span="1">
          <NCard size="small">
            <NStatistic label="Overall" :value="health.status">
              <template #suffix>
                <NTag size="small" :type="runtimeStatusType(health.status)">{{ health.status }}</NTag>
              </template>
            </NStatistic>
            <div class="runtime-card-note">{{ formatDateTime(health.generated_at) }}</div>
          </NCard>
        </NGridItem>
        <NGridItem v-for="item in overviewCards" :key="item.label" :span="1">
          <NCard size="small">
            <div class="runtime-overview">
              <span>{{ item.label }}</span>
              <NTag size="small" :type="runtimeStatusType(item.status)">{{ item.status }}</NTag>
            </div>
            <div class="runtime-card-note">{{ item.detail }}</div>
          </NCard>
        </NGridItem>
      </NGrid>

      <div class="runtime-grid runtime-grid--two">
        <NCard title="DB / Redis" size="small">
          <NDescriptions :column="1" size="small" label-placement="left">
            <NDescriptionsItem label="DB Status">
              <NTag size="small" :type="runtimeStatusType(health.components.db.status)">{{ health.components.db.status }}</NTag>
            </NDescriptionsItem>
            <NDescriptionsItem label="DB Latency">{{ formatLatencyMs(health.components.db.latency_ms) }}</NDescriptionsItem>
            <NDescriptionsItem label="DB Error Type">{{ health.components.db.error_type || '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="Redis Status">
              <NTag size="small" :type="runtimeStatusType(health.components.redis.status)">{{ health.components.redis.status }}</NTag>
            </NDescriptionsItem>
            <NDescriptionsItem label="Redis Latency">{{ formatLatencyMs(health.components.redis.latency_ms) }}</NDescriptionsItem>
            <NDescriptionsItem label="Redis Error Type">{{ health.components.redis.error_type || '-' }}</NDescriptionsItem>
          </NDescriptions>
        </NCard>

        <NCard title="Notification Retry" size="small">
          <NDescriptions :column="2" size="small" label-placement="top">
            <NDescriptionsItem label="Status">
              <NTag size="small" :type="runtimeStatusType(health.components.notification_retry.status)">
                {{ health.components.notification_retry.status }}
              </NTag>
            </NDescriptionsItem>
            <NDescriptionsItem label="Channel">{{ health.components.notification_retry.channel }}</NDescriptionsItem>
            <NDescriptionsItem label="Total">{{ health.components.notification_retry.total_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Retry Pending">{{ health.components.notification_retry.retry_pending_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Due Retry">{{ health.components.notification_retry.due_retry_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Failed">{{ health.components.notification_retry.failed_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Sent">{{ health.components.notification_retry.sent_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Skipped">{{ health.components.notification_retry.skipped_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Pending">{{ health.components.notification_retry.pending_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Next Retry">{{ formatDateTime(health.components.notification_retry.next_retry_at) }}</NDescriptionsItem>
          </NDescriptions>
          <div class="runtime-muted">
            last_error_type_counts: {{ formatCountMap(health.components.notification_retry.last_error_type_counts) }}
          </div>
        </NCard>
      </div>

      <NCard title="RQ Queue / Worker" size="small" class="runtime-section">
        <div class="runtime-section-head">
          <span>worker_count={{ health.components.rq.worker_count }}</span>
          <NTag size="small" :type="runtimeStatusType(health.components.rq.status)">{{ health.components.rq.status }}</NTag>
          <span>error_type={{ health.components.rq.error_type || '-' }}</span>
        </div>
        <NDataTable size="small" :columns="queueColumns" :data="health.components.rq.queues" :pagination="false" />
        <div class="runtime-subtitle">Workers</div>
        <NDataTable
          v-if="health.components.rq.workers.length"
          size="small"
          :columns="workerColumns"
          :data="health.components.rq.workers"
          :pagination="false"
        />
        <NEmpty v-else description="暂无 RQ worker；这会按 runtime health 契约显示为 degraded。" />
      </NCard>

      <div class="runtime-grid runtime-grid--two">
        <NCard title="Scheduler" size="small">
          <template v-if="health.components.scheduler">
            <NDescriptions :column="1" size="small" label-placement="left">
              <NDescriptionsItem label="Status">
                <NTag size="small" :type="runtimeStatusType(health.components.scheduler.status)">
                  {{ health.components.scheduler.status }}
                </NTag>
              </NDescriptionsItem>
              <NDescriptionsItem label="Enabled">{{ health.components.scheduler.enabled ?? '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Heartbeat">{{ formatDateTime(health.components.scheduler.heartbeat_at) }}</NDescriptionsItem>
              <NDescriptionsItem label="Age (s)">{{ health.components.scheduler.heartbeat_age_seconds ?? '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Last Cycle">{{ health.components.scheduler.last_cycle_status || '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Error Type">{{ health.components.scheduler.error_type || '-' }}</NDescriptionsItem>
            </NDescriptions>
          </template>
          <NEmpty v-else description="runtime health 未返回 scheduler 组件。" />
        </NCard>

        <NCard title="After-Market Archive" size="small">
          <template v-if="health.components.archive">
            <NDescriptions :column="1" size="small" label-placement="left">
              <NDescriptionsItem label="Status">
                <NTag size="small" :type="runtimeStatusType(health.components.archive.status)">
                  {{ health.components.archive.status }}
                </NTag>
              </NDescriptionsItem>
              <NDescriptionsItem label="Enabled">{{ health.components.archive.enabled ?? '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Latest Task">{{ health.components.archive.latest_task_no || '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Task Status">{{ health.components.archive.latest_task_status || '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Contract">{{ health.components.archive.latest_contract || '-' }}</NDescriptionsItem>
              <NDescriptionsItem label="Finished">{{ formatDateTime(health.components.archive.latest_finished_at) }}</NDescriptionsItem>
              <NDescriptionsItem label="Error Type">{{ health.components.archive.latest_error_type || health.components.archive.error_type || '-' }}</NDescriptionsItem>
            </NDescriptions>
          </template>
          <NEmpty v-else description="runtime health 未返回 archive 组件。" />
        </NCard>

        <NCard title="After-Market Scheduler" size="small">
          <NDescriptions v-if="afterMarketScheduler" :column="1" size="small" label-placement="left">
            <NDescriptionsItem label="Status">
              <NTag size="small" :type="runtimeStatusType(afterMarketScheduler.status)">
                {{ afterMarketScheduler.status }}
              </NTag>
            </NDescriptionsItem>
            <NDescriptionsItem label="Enabled">{{ afterMarketScheduler.enabled }}</NDescriptionsItem>
            <NDescriptionsItem label="Last Successful Day">
              {{ afterMarketScheduler.last_successful_trading_day || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Latest Completed Day">
              {{ afterMarketScheduler.latest_completed_trading_day || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Latest Eligible Day">
              {{ afterMarketScheduler.latest_eligible_trading_day || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Archive Lag (trading days)">
              {{ afterMarketScheduler.archive_lag_trading_days ?? '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Current Task">
              {{ afterMarketScheduler.current_task || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Retry Count">{{ afterMarketScheduler.retry_count }}</NDescriptionsItem>
            <NDescriptionsItem label="Next Retry">
              {{ formatDateTime(afterMarketScheduler.next_retry_at) }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Heartbeat">
              {{ formatDateTime(afterMarketScheduler.scheduler_heartbeat?.heartbeat_at) }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Heartbeat Age (s)">
              {{ afterMarketScheduler.scheduler_heartbeat?.heartbeat_age_seconds ?? '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Lock Status">
              {{ afterMarketScheduler.lock_status || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Active Binding End">
              {{ afterMarketScheduler.active_binding_end || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Required Bindings">
              {{ afterMarketScheduler.active_binding_ends.length }}
            </NDescriptionsItem>
            <NDescriptionsItem label="Last Error">
              {{ afterMarketScheduler.last_error_type || afterMarketScheduler.error_type || '-' }}
            </NDescriptionsItem>
          </NDescriptions>
          <NEmpty v-else description="runtime health 未返回 after-market scheduler 组件。" />
        </NCard>
      </div>

      <NCard title="Live Checkpoints" size="small" class="runtime-section">
        <div class="runtime-section-head">
          <NTag size="small" :type="runtimeStatusType(health.components.live_checkpoints.status)">
            {{ health.components.live_checkpoints.status }}
          </NTag>
          <span>ingest={{ health.components.live_checkpoints.ingest_count }}</span>
          <span>aggregation={{ health.components.live_checkpoints.aggregation_count }}</span>
          <span>market_phase={{ health.components.live_checkpoints.market_phase || 'unknown' }}</span>
          <span>polling_expected={{ health.components.live_checkpoints.polling_expected ?? false }}</span>
          <span>status_counts={{ formatCountMap(health.components.live_checkpoints.status_counts) }}</span>
          <span>latest_success_at={{ formatDateTime(health.components.live_checkpoints.latest_success_at) }}</span>
        </div>
        <div v-if="latestErrorEntries.length" class="runtime-error-strip">
          <span v-for="item in latestErrorEntries" :key="item.key">{{ item.key }}={{ item.value }}</span>
        </div>
        <div class="runtime-subtitle">Recent Ingest</div>
        <NDataTable
          v-if="health.components.live_checkpoints.recent_ingest.length"
          size="small"
          :columns="checkpointColumns"
          :data="health.components.live_checkpoints.recent_ingest"
          :pagination="false"
        />
        <NEmpty v-else description="暂无 live ingest checkpoint 记录。" />
        <div class="runtime-subtitle">Recent Aggregation</div>
        <NDataTable
          v-if="health.components.live_checkpoints.recent_aggregation.length"
          size="small"
          :columns="checkpointColumns"
          :data="health.components.live_checkpoints.recent_aggregation"
          :pagination="false"
        />
        <NEmpty v-else description="暂无 live aggregation checkpoint 记录。" />
      </NCard>
    </template>
  </PageShell>
</template>

<style scoped>
.runtime-boundary {
  margin-bottom: 12px;
}

.runtime-boundary__inner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.runtime-overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.runtime-card-note,
.runtime-muted {
  margin-top: 8px;
  color: var(--gy-text-muted);
  font-size: 12px;
}

.runtime-grid {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.runtime-grid--two {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}

.runtime-section {
  margin-top: 12px;
}

.runtime-section-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  color: var(--gy-text-muted);
  font-size: 12px;
}

.runtime-subtitle {
  margin: 14px 0 8px;
  color: var(--gy-text-primary);
  font-size: 13px;
  font-weight: 600;
}

.runtime-error-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-bottom: 10px;
  padding: 8px 10px;
  border: 1px solid var(--gy-border);
  border-radius: 8px;
  color: var(--gy-text-muted);
  background: var(--gy-bg-elevated);
  font-size: 12px;
}
</style>
