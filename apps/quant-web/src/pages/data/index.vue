<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NButton, NCard, NDataTable, NGrid, NGridItem, NStatistic, NTabPane, NTabs, NTag } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  getContracts,
  getCoverage,
  getDataProfiles,
  getDataSources,
  getDownloadTasks,
  getExchanges,
  getInstruments,
  getQualityReports,
} from '@/api/data'
import type {
  ContractInfo,
  CoverageInfo,
  DataDownloadTaskInfo,
  DataProfileInfo,
  DataQualityReportInfo,
  DataSourceInfo,
  ExchangeInfo,
  InstrumentInfo,
} from '@/types/data'

const activeTab = ref('instruments')
const loading = ref(false)
const sources = ref<DataSourceInfo[]>([])
const exchanges = ref<ExchangeInfo[]>([])
const instruments = ref<InstrumentInfo[]>([])
const contracts = ref<ContractInfo[]>([])
const tasks = ref<DataDownloadTaskInfo[]>([])
const qualityReports = ref<DataQualityReportInfo[]>([])
const coverage = ref<CoverageInfo[]>([])
const profiles = ref<DataProfileInfo[]>([])

const statusType = (status: string) => {
  if (['success', 'passed', 'enabled', 'active', 'research'].includes(status)) return 'success'
  if (['warning', 'running', 'pending'].includes(status)) return 'warning'
  if (['failed', 'disabled'].includes(status)) return 'error'
  return 'default'
}

const renderStatus = (status: string) => h(NTag, { type: statusType(status), size: 'small' }, { default: () => status })
const rowKey = (row: { id: number }) => row.id
const formatDateTime = (value: string | null | undefined) => (value ? value.replace('T', ' ').slice(0, 16) : '-')
const formatInteger = (value: number | null | undefined) => (value === null || value === undefined ? '-' : value.toLocaleString('zh-CN'))
const isContinuousContract = (contract: string | null | undefined) => String(contract || '').toUpperCase().endsWith('.MAIN')
const coverageViewRole = (row: CoverageInfo) => row.view_role || (isContinuousContract(row.contract_code) ? 'continuous' : 'actual_contract')
const coverageViewLabel = (row: CoverageInfo) => (coverageViewRole(row) === 'continuous' ? '主连研究' : '真实合约')
const coverageViewType = (row: CoverageInfo) => (coverageViewRole(row) === 'continuous' ? 'info' : 'success')
const renderCoverageView = (row: CoverageInfo) =>
  h(NTag, { type: coverageViewType(row), size: 'small' }, { default: () => coverageViewLabel(row) })

const instrumentColumns: DataTableColumns<InstrumentInfo> = [
  { title: '品种代码', key: 'symbol', width: 110 },
  { title: '品种名称', key: 'name', width: 140 },
  { title: '交易所', key: 'exchange_code', width: 110 },
  { title: '板块', key: 'sector', width: 120 },
  { title: '类型', key: 'category', width: 120 },
  {
    title: '状态',
    key: 'is_active',
    width: 90,
    render: (row) => renderStatus(row.is_active ? 'active' : 'disabled'),
  },
]

const contractColumns: DataTableColumns<ContractInfo> = [
  { title: '合约代码', key: 'contract_code', width: 140 },
  { title: '名称', key: 'name', width: 180 },
  { title: '品种', key: 'instrument_symbol', width: 100 },
  { title: '交易所', key: 'exchange_code', width: 100 },
  { title: '月份', key: 'contract_month', width: 100 },
  { title: '来源', key: 'provider', width: 150 },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => renderStatus(row.status),
  },
]

const taskColumns: DataTableColumns<DataDownloadTaskInfo> = [
  { title: '任务号', key: 'task_no', width: 180 },
  { title: '来源', key: 'provider', width: 150 },
  { title: '数据类型', key: 'data_type', width: 180 },
  { title: '品种', key: 'instrument_symbol', width: 100 },
  { title: '周期', key: 'period', width: 90 },
  { title: '进度', key: 'progress', width: 90 },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => renderStatus(row.status),
  },
  { title: '错误', key: 'error_message', ellipsis: { tooltip: true } },
]

const qualityColumns: DataTableColumns<DataQualityReportInfo> = [
  { title: '来源', key: 'provider', width: 150 },
  { title: '品种', key: 'instrument_symbol', width: 100 },
  { title: '合约', key: 'contract_code', width: 130 },
  { title: '周期', key: 'period', width: 90 },
  {
    title: '质量',
    key: 'status',
    width: 100,
    render: (row) => renderStatus(row.status),
  },
  { title: '重复', key: 'duplicated_bars', width: 80 },
  { title: '异常价', key: 'abnormal_price_count', width: 90 },
  { title: '异常量', key: 'abnormal_volume_count', width: 90 },
]

const coverageColumns: DataTableColumns<CoverageInfo> = [
  { title: '来源', key: 'provider', width: 130 },
  { title: '数据类型', key: 'data_type', width: 110 },
  { title: '品种', key: 'instrument_symbol', width: 90 },
  { title: '合约', key: 'contract_code', width: 130 },
  {
    title: '视图',
    key: 'view_role',
    width: 110,
    render: (row) => renderCoverageView(row),
  },
  { title: '周期', key: 'period', width: 80 },
  {
    title: '质量',
    key: 'quality_status',
    width: 100,
    render: (row) => renderStatus(row.quality_status),
  },
  {
    title: '行数',
    key: 'row_count',
    width: 110,
    align: 'right',
    render: (row) => formatInteger(row.row_count),
  },
  { title: '数据版本', key: 'data_version', width: 260, ellipsis: { tooltip: true } },
  {
    title: 'Profile',
    key: 'active_profile_ids',
    width: 180,
    render: (row) => (row.active_profile_ids?.length ? row.active_profile_ids.join(', ') : '-'),
  },
  {
    title: 'Active',
    key: 'binding_status',
    width: 100,
    render: (row) => (row.binding_status ? renderStatus(row.binding_status) : h('span', '-'))
  },
  {
    title: '更新时间',
    key: 'updated_at',
    width: 150,
    render: (row) => formatDateTime(row.updated_at),
  },
  {
    title: '开始时间',
    key: 'start_time',
    width: 150,
    render: (row) => formatDateTime(row.start_time),
  },
  {
    title: '结束时间',
    key: 'end_time',
    width: 150,
    render: (row) => formatDateTime(row.end_time),
  },
  {
    title: '最新边界',
    key: 'latest_bar_time',
    width: 150,
    render: (row) => formatDateTime(row.latest_bar_time || row.end_time),
  },
  { title: '文件路径', key: 'file_path', minWidth: 320, ellipsis: { tooltip: true } },
]

async function fetchData() {
  loading.value = true
  try {
    const [sourceRows, exchangeRows, instrumentRows, contractRows, taskRows, qualityRows, coverageRows, profileRows] =
      await Promise.all([
        getDataSources(),
        getExchanges(),
        getInstruments(),
        getContracts(),
        getDownloadTasks(),
        getQualityReports(),
        getCoverage(),
        getDataProfiles(),
      ])
    sources.value = sourceRows
    exchanges.value = exchangeRows
    instruments.value = instrumentRows
    contracts.value = contractRows
    tasks.value = taskRows
    qualityReports.value = qualityRows
    coverage.value = coverageRows
    profiles.value = profileRows
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="data-page">
    <NGrid :cols="4" :x-gap="12" :y-gap="12" responsive="screen">
      <NGridItem>
        <NCard>
          <NStatistic label="数据源" :value="sources.length" />
        </NCard>
      </NGridItem>
      <NGridItem>
        <NCard>
          <NStatistic label="品种" :value="instruments.length" />
        </NCard>
      </NGridItem>
      <NGridItem>
        <NCard>
          <NStatistic label="合约" :value="contracts.length" />
        </NCard>
      </NGridItem>
      <NGridItem>
        <NCard>
          <NStatistic label="数据文件" :value="coverage.length" />
        </NCard>
      </NGridItem>
    </NGrid>

    <NCard title="数据中心" class="data-card">
      <template #header-extra>
        <NButton :loading="loading" @click="fetchData">刷新</NButton>
      </template>

      <NTabs v-model:value="activeTab" type="line" default-value="instruments">
        <NTabPane name="instruments" tab="品种">
          <NDataTable
            :columns="instrumentColumns"
            :data="instruments"
            :loading="loading"
            :bordered="false"
            :pagination="{ pageSize: 12 }"
            :row-key="rowKey"
          />
        </NTabPane>
        <NTabPane name="contracts" tab="合约">
          <NDataTable
            :columns="contractColumns"
            :data="contracts"
            :loading="loading"
            :bordered="false"
            :pagination="{ pageSize: 12 }"
            :row-key="rowKey"
          />
        </NTabPane>
        <NTabPane name="tasks" tab="数据任务">
          <NDataTable
            :columns="taskColumns"
            :data="tasks"
            :loading="loading"
            :bordered="false"
            :pagination="{ pageSize: 12 }"
            :row-key="rowKey"
          />
        </NTabPane>
        <NTabPane name="quality" tab="质量报告">
          <NDataTable
            :columns="qualityColumns"
            :data="qualityReports"
            :loading="loading"
            :bordered="false"
            :pagination="{ pageSize: 12 }"
            :row-key="rowKey"
          />
        </NTabPane>
        <NTabPane name="coverage" tab="数据文件">
          <NDataTable
            :columns="coverageColumns"
            :data="coverage"
            :loading="loading"
            :bordered="false"
            :pagination="{ pageSize: 12 }"
            :row-key="rowKey"
            :scroll-x="1840"
          />
        </NTabPane>
      </NTabs>
    </NCard>
  </div>
</template>

<style scoped>
.data-page {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-4);
}

.data-card {
  min-height: 560px;
  overflow: hidden;
}

@media (max-width: 1199px) {
  .data-card { min-height: 480px; }
}
</style>
