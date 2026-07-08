<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NGrid, NGridItem, NStatistic, NTag, NAlert } from 'naive-ui'
import { getDashboardSummary } from '@/api/dashboard'
import PageShell from '@/components/common/PageShell.vue'
import LiveTargetPanel from '@/components/market/LiveTargetPanel.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import type { DashboardSummary } from '@/types/dashboard'

const router = useRouter()
const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<DashboardSummary | null>(null)

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
    <template v-if="summary">
      <NGrid :cols="4" :x-gap="16" :y-gap="16">
        <NGridItem>
          <NCard size="small">
            <NStatistic label="今日信号" :value="summary.signals_today" />
          </NCard>
        </NGridItem>
        <NGridItem>
          <NCard size="small">
            <NStatistic label="策略数" :value="summary.strategies">
              <template #suffix>
                <NTag size="tiny" type="info">V1-B {{ summary.v1b_strategies }}</NTag>
              </template>
            </NStatistic>
          </NCard>
        </NGridItem>
        <NGridItem>
          <NCard size="small">
            <NStatistic label="回测任务" :value="summary.backtests" />
          </NCard>
        </NGridItem>
        <NGridItem>
          <NCard size="small">
            <NStatistic label="数据合约" :value="summary.data_contracts" />
          </NCard>
        </NGridItem>
      </NGrid>

      <div class="dashboard-grid">
        <NCard title="快捷操作" size="small">
          <div class="dashboard-actions">
            <NButton type="primary" @click="router.push({ name: 'backtest' })">JM V1-B 回测</NButton>
            <NButton @click="router.push({ name: 'signal' })">信号监控</NButton>
            <NButton @click="router.push({ name: 'market' })">行情看板</NButton>
            <NButton @click="router.push({ name: 'data' })">数据中心</NButton>
          </div>
          <div v-if="summary.latest_jm_report" class="dashboard-meta">
            最新 JM 报告：
            <NButton
              text
              type="primary"
              @click="router.push({ name: 'backtest', query: { report_id: String(summary.latest_jm_report?.report_id) } })"
            >
              #{{ summary.latest_jm_report.report_id }}
            </NButton>
          </div>
          <div v-if="summary.latest_scan_task" class="dashboard-meta">
            最近扫描：{{ summary.latest_scan_task.task_no }} · {{ summary.latest_scan_task.status }}
          </div>
        </NCard>

        <NCard title="系统状态" size="small">
          <div class="dashboard-status">
            <span>数据状态 <StatusTag :status="summary.data_status" /></span>
            <span>风控 <NTag size="small">{{ summary.risk_status }}</NTag></span>
            <span>Live Target <StatusTag :status="summary.live_target_readiness || 'unknown'" /></span>
            <span>JM primary passed 资产 {{ summary.jm_primary_passed_assets }}</span>
          </div>
          <NAlert type="info" :bordered="false" style="margin-top: 12px">
            本工作站仅用于研究与复盘，不自动下单。
          </NAlert>
        </NCard>

        <LiveTargetPanel compact />
      </div>
    </template>
  </PageShell>
</template>

<style scoped>
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.dashboard-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dashboard-meta {
  margin-top: 10px;
  font-size: 13px;
  color: var(--gy-text-muted);
}

.dashboard-status {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
}
</style>
