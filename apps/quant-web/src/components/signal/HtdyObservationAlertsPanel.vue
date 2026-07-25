<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NDataTable, NTag, type DataTableColumns } from 'naive-ui'
import { listHtdyObservationAlerts } from '@/api/observation'
import type { HtdyObservationAlertRecord } from '@/types/observation'
import { buildHtdyAlertMarketQuery, htdyDirectionLabel } from '@/utils/htdyObservation'
import { toSafeApiError } from '@/utils/errorRedaction'

const router = useRouter()
const alerts = ref<HtdyObservationAlertRecord[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const columns: DataTableColumns<HtdyObservationAlertRecord> = [
  { title: '时间', key: 'bar_end', render: (row) => row.bar_end.replace('T', ' ').slice(0, 16) },
  { title: '合约', key: 'actual_contract' },
  {
    title: '观察',
    key: 'direction',
    render: (row) => h(NTag, { type: row.direction === 'long' ? 'error' : row.direction === 'short' ? 'success' : 'warning', size: 'small' }, { default: () => htdyDirectionLabel(row.direction) }),
  },
  { title: '价格', key: 'trigger_price' },
  { title: 'bar revision', key: 'live_bar_revision' },
  {
    title: '重绘风险',
    key: 'repainting_risk',
    render: () => h(NTag, { type: 'warning', size: 'small' }, { default: () => '未来函数 / 可能重绘' }),
  },
  { title: '通知', key: 'notification_status' },
  {
    title: '操作',
    key: 'actions',
    render: (row) => h(NButton, { size: 'small', secondary: true, onClick: () => openMarket(row) }, { default: () => '打开 15m K线' }),
  },
]

async function loadAlerts() {
  loading.value = true
  error.value = null
  try {
    alerts.value = (await listHtdyObservationAlerts({ limit: 100, offset: 0 })).items
  } catch (caught) {
    error.value = toSafeApiError(caught, '加载火天大有观察预警失败')
  } finally {
    loading.value = false
  }
}

function openMarket(alert: HtdyObservationAlertRecord) {
  void router.push({ name: 'market-chart', query: buildHtdyAlertMarketQuery(alert) })
}

onMounted(loadAlerts)
</script>

<template>
  <section class="panel">
    <div class="panel__header">
      <div>
        <h2>火天大有原版 XMA 实时观察预警</h2>
        <p>JM 当前实际主力 · confirmed 15m · 独立观察记录，不是正式 SignalEvent</p>
      </div>
      <NButton size="small" :loading="loading" @click="loadAlerts">刷新</NButton>
    </div>
    <NAlert type="warning" :bordered="false">
      原版 XMA 含未来函数且可能重绘；首次预警后不撤回、不更正。同一 bar 后续 revision 不重复预警。仅供观察，不是交易指令，不自动下单。
    </NAlert>
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <NDataTable
      :columns="columns"
      :data="alerts"
      :loading="loading"
      :bordered="false"
      :single-line="false"
      :pagination="{ pageSize: 10 }"
      :scroll-x="1100"
      size="small"
    />
  </section>
</template>
