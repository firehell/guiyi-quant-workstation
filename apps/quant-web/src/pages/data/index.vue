<script setup lang="ts">
/**
 * 数据中心 V1：首屏摘要 + Tab lazy load；coverage/quality/tasks 服务端有界分页；不展示物理路径。
 */
import { h, onMounted, reactive, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
} from 'naive-ui'
import type { DataTableColumns, PaginationProps } from 'naive-ui'
import {
  getContracts,
  getCoverage,
  getDataCenterSummary,
  getDataProfiles,
  getDownloadTasks,
  getInstruments,
  getQualityReports,
} from '@/api/data'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PageShell from '@/components/common/PageShell.vue'
import type {
  ContractInfo,
  CoverageInfo,
  CoveragePage,
  DataCenterSummary,
  DataDownloadTaskInfo,
  DataDownloadTaskPage,
  DataProfileInfo,
  DataQualityReportInfo,
  DataQualityReportPage,
  InstrumentInfo,
} from '@/types/data'
import { toSafeApiError } from '@/utils/errorRedaction'
import { redactSensitiveText } from '@/utils/errorRedaction'

type TabName = 'instruments' | 'contracts' | 'tasks' | 'quality' | 'coverage' | 'profiles'

const PAGE_SIZE = 12
const activeTab = ref<TabName>('instruments')
const summary = ref<DataCenterSummary | null>(null)
const summaryLoading = ref(false)
const summaryError = ref<string | null>(null)

const instruments = ref<InstrumentInfo[]>([])
const contracts = ref<ContractInfo[]>([])
const profiles = ref<DataProfileInfo[]>([])
const tasks = ref<DataDownloadTaskInfo[]>([])
const qualityReports = ref<DataQualityReportInfo[]>([])
const coverage = ref<CoverageInfo[]>([])

const tabLoading = reactive<Record<TabName, boolean>>({
  instruments: false,
  contracts: false,
  tasks: false,
  quality: false,
  coverage: false,
  profiles: false,
})
const tabError = reactive<Record<TabName, string | null>>({
  instruments: null,
  contracts: null,
  tasks: null,
  quality: null,
  coverage: null,
  profiles: null,
})
const tabLoaded = reactive<Record<TabName, boolean>>({
  instruments: false,
  contracts: false,
  tasks: false,
  quality: false,
  coverage: false,
  profiles: false,
})

const taskTotal = ref(0)
const qualityTotal = ref(0)
const coverageTotal = ref(0)
const taskPage = ref(1)
const qualityPage = ref(1)
const coveragePage = ref(1)

const coverageFilters = reactive({
  symbol: '',
  contract: '',
  period: '',
  quality: '',
  provider: '',
  binding_status: '',
})

const statusType = (status: string) => {
  if (['success', 'passed', 'enabled', 'active', 'research'].includes(status)) return 'success'
  if (['warning', 'running', 'pending'].includes(status)) return 'warning'
  if (['failed', 'disabled'].includes(status)) return 'error'
  return 'default'
}

const renderStatus = (status: string) =>
  h(NTag, { type: statusType(status), size: 'small' }, { default: () => status })
const rowKey = (row: { id: number }) => row.id
const formatDateTime = (value: string | null | undefined) =>
  value ? value.replace('T', ' ').slice(0, 16) : '-'
const formatInteger = (value: number | null | undefined) =>
  value === null || value === undefined ? '-' : value.toLocaleString('zh-CN')
const isContinuousContract = (contract: string | null | undefined) =>
  String(contract || '').toUpperCase().endsWith('.MAIN')
const coverageViewRole = (row: CoverageInfo) =>
  row.view_role || (isContinuousContract(row.contract_code) ? 'continuous' : 'actual_contract')
const coverageViewLabel = (row: CoverageInfo) =>
  coverageViewRole(row) === 'continuous' ? '主连研究' : '真实合约'
const coverageViewType = (row: CoverageInfo) =>
  coverageViewRole(row) === 'continuous' ? 'info' : 'success'
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
  {
    title: '错误',
    key: 'error_message',
    ellipsis: { tooltip: true },
    render: (row) => redactSensitiveText(String(row.error_message || '-')),
  },
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
  { title: '资产 ID', key: 'id', width: 90 },
  { title: '来源', key: 'provider', width: 120 },
  { title: '角色', key: 'data_role', width: 100 },
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
  { title: '数据版本', key: 'data_version', width: 220, ellipsis: { tooltip: true } },
  {
    title: '覆盖',
    key: 'start_time',
    width: 220,
    render: (row) => `${formatDateTime(row.start_time)} → ${formatDateTime(row.end_time)}`,
  },
  {
    title: 'Active Profile',
    key: 'active_profile_ids',
    width: 180,
    render: (row) => (row.active_profile_ids?.length ? row.active_profile_ids.join(', ') : '—'),
  },
  {
    title: 'Binding',
    key: 'binding_status',
    width: 110,
    render: (row) => renderStatus(row.binding_status || 'unbound'),
  },
]

const profileColumns: DataTableColumns<DataProfileInfo> = [
  { title: 'Profile ID', key: 'profile_id', width: 200 },
  { title: '名称', key: 'label', width: 160 },
  { title: 'Provider', key: 'provider', width: 120 },
  { title: '质量策略', key: 'quality_policy', width: 120 },
  {
    title: '状态',
    key: 'is_active',
    width: 100,
    render: (row) => renderStatus(row.is_active ? 'active' : 'disabled'),
  },
  {
    title: '周期',
    key: 'periods',
    render: (row) => row.periods.join(', '),
  },
]

function serverPagination(page: number, itemCount: number, onChange: (p: number) => void): PaginationProps {
  return {
    page,
    pageSize: PAGE_SIZE,
    itemCount,
    pageSizes: [PAGE_SIZE],
    showSizePicker: false,
    onUpdatePage: onChange,
  }
}

function onTaskPageChange(p: number) {
  taskPage.value = p
  tabLoaded.tasks = false
  void loadTasks(true)
}

function onQualityPageChange(p: number) {
  qualityPage.value = p
  tabLoaded.quality = false
  void loadQuality(true)
}

function onCoveragePageChange(p: number) {
  coveragePage.value = p
  void loadCoverage(true)
}

async function loadSummary() {
  summaryLoading.value = true
  summaryError.value = null
  try {
    summary.value = await getDataCenterSummary()
  } catch (err) {
    summaryError.value = toSafeApiError(err, '加载数据中心摘要失败')
  } finally {
    summaryLoading.value = false
  }
}

async function loadInstruments(force = false) {
  if (tabLoaded.instruments && !force) return
  tabLoading.instruments = true
  tabError.instruments = null
  try {
    instruments.value = await getInstruments()
    tabLoaded.instruments = true
  } catch (err) {
    tabError.instruments = toSafeApiError(err, '加载品种失败')
  } finally {
    tabLoading.instruments = false
  }
}

async function loadContracts(force = false) {
  if (tabLoaded.contracts && !force) return
  tabLoading.contracts = true
  tabError.contracts = null
  try {
    contracts.value = await getContracts()
    tabLoaded.contracts = true
  } catch (err) {
    tabError.contracts = toSafeApiError(err, '加载合约失败')
  } finally {
    tabLoading.contracts = false
  }
}

async function loadProfiles(force = false) {
  if (tabLoaded.profiles && !force) return
  tabLoading.profiles = true
  tabError.profiles = null
  try {
    profiles.value = await getDataProfiles()
    tabLoaded.profiles = true
  } catch (err) {
    tabError.profiles = toSafeApiError(err, '加载 Profile 失败')
  } finally {
    tabLoading.profiles = false
  }
}

async function loadTasks(force = false) {
  if (tabLoaded.tasks && !force) return
  tabLoading.tasks = true
  tabError.tasks = null
  try {
    const offset = (taskPage.value - 1) * PAGE_SIZE
    const page = (await getDownloadTasks({
      paged: true,
      limit: PAGE_SIZE,
      offset,
    })) as DataDownloadTaskPage
    tasks.value = page.items
    taskTotal.value = page.total
    tabLoaded.tasks = true
  } catch (err) {
    tabError.tasks = toSafeApiError(err, '加载数据任务失败')
  } finally {
    tabLoading.tasks = false
  }
}

async function loadQuality(force = false) {
  if (tabLoaded.quality && !force) return
  tabLoading.quality = true
  tabError.quality = null
  try {
    const offset = (qualityPage.value - 1) * PAGE_SIZE
    const page = (await getQualityReports({
      paged: true,
      limit: PAGE_SIZE,
      offset,
    })) as DataQualityReportPage
    qualityReports.value = page.items
    qualityTotal.value = page.total
    tabLoaded.quality = true
  } catch (err) {
    tabError.quality = toSafeApiError(err, '加载质量报告失败')
  } finally {
    tabLoading.quality = false
  }
}

async function loadCoverage(force = true) {
  if (tabLoaded.coverage && !force) return
  tabLoading.coverage = true
  tabError.coverage = null
  try {
    const offset = (coveragePage.value - 1) * PAGE_SIZE
    const page = (await getCoverage({
      paged: true,
      limit: PAGE_SIZE,
      offset,
      symbol: coverageFilters.symbol || undefined,
      contract: coverageFilters.contract || undefined,
      period: coverageFilters.period || undefined,
      quality: coverageFilters.quality || undefined,
      provider: coverageFilters.provider || undefined,
      binding_status: coverageFilters.binding_status || undefined,
      include_paths: false,
    })) as CoveragePage
    coverage.value = page.items
    coverageTotal.value = page.total
    tabLoaded.coverage = true
  } catch (err) {
    tabError.coverage = toSafeApiError(err, '加载 coverage 失败')
  } finally {
    tabLoading.coverage = false
  }
}

async function ensureTab(tab: TabName, force = false) {
  if (tab === 'instruments') return loadInstruments(force)
  if (tab === 'contracts') return loadContracts(force)
  if (tab === 'tasks') {
    if (force) tabLoaded.tasks = false
    return loadTasks(force)
  }
  if (tab === 'quality') {
    if (force) tabLoaded.quality = false
    return loadQuality(force)
  }
  if (tab === 'coverage') return loadCoverage(true)
  if (tab === 'profiles') return loadProfiles(force)
}

function retryActiveTab() {
  tabLoaded[activeTab.value] = false
  void ensureTab(activeTab.value, true)
}

function applyCoverageFilters() {
  coveragePage.value = 1
  tabLoaded.coverage = false
  void loadCoverage(true)
}

watch(activeTab, (tab) => {
  void ensureTab(tab)
})

onMounted(async () => {
  await loadSummary()
  await ensureTab(activeTab.value)
})
</script>

<template>
  <PageShell
    title="数据中心"
    subtitle="有界加载 · Profile 只读观察 · 不展示物理路径"
    :error="summaryError"
    :loading="summaryLoading && !summary"
    @retry="loadSummary"
  >
    <template #badges>
      <CapabilityBadge kind="formal-research" />
      <CapabilityBadge kind="research-only" label="Profile 只读" />
    </template>
    <template #actions>
      <NButton
        size="small"
        :loading="summaryLoading"
        aria-label="刷新数据中心摘要"
        @click="loadSummary"
      >
        刷新摘要
      </NButton>
      <NButton size="small" secondary aria-label="重试当前 Tab" @click="retryActiveTab">
        重试当前 Tab
      </NButton>
    </template>

    <div class="data-page">
      <NGrid v-if="summary" :cols="4" :x-gap="12" :y-gap="12" responsive="screen">
        <NGridItem>
          <NCard><NStatistic label="数据源" :value="summary.source_count" /></NCard>
        </NGridItem>
        <NGridItem>
          <NCard><NStatistic label="品种" :value="summary.instrument_count" /></NCard>
        </NGridItem>
        <NGridItem>
          <NCard><NStatistic label="合约" :value="summary.contract_count" /></NCard>
        </NGridItem>
        <NGridItem>
          <NCard><NStatistic label="数据文件" :value="summary.coverage_count" /></NCard>
        </NGridItem>
      </NGrid>

      <NCard title="资产与任务" class="data-card">
        <NTabs v-model:value="activeTab" type="line">
          <NTabPane name="instruments" tab="品种">
            <NAlert v-if="tabError.instruments" type="error" :bordered="false" class="tab-alert">
              {{ tabError.instruments }}
              <NButton size="tiny" secondary class="tab-retry" @click="retryActiveTab">重试</NButton>
            </NAlert>
            <NDataTable
              v-else
              :columns="instrumentColumns"
              :data="instruments"
              :loading="tabLoading.instruments"
              :bordered="false"
              :pagination="{ pageSize: PAGE_SIZE }"
              :row-key="rowKey"
            />
            <EmptyState v-if="!tabLoading.instruments && !tabError.instruments && !instruments.length" />
          </NTabPane>

          <NTabPane name="contracts" tab="合约">
            <NAlert v-if="tabError.contracts" type="error" :bordered="false" class="tab-alert">
              {{ tabError.contracts }}
              <NButton size="tiny" secondary class="tab-retry" @click="retryActiveTab">重试</NButton>
            </NAlert>
            <NDataTable
              v-else
              :columns="contractColumns"
              :data="contracts"
              :loading="tabLoading.contracts"
              :bordered="false"
              :pagination="{ pageSize: PAGE_SIZE }"
              :row-key="rowKey"
            />
          </NTabPane>

          <NTabPane name="tasks" tab="数据任务">
            <NAlert v-if="tabError.tasks" type="error" :bordered="false" class="tab-alert">
              {{ tabError.tasks }}
              <NButton size="tiny" secondary class="tab-retry" @click="retryActiveTab">重试</NButton>
            </NAlert>
            <NDataTable
              v-else
              :columns="taskColumns"
              :data="tasks"
              :loading="tabLoading.tasks"
              :bordered="false"
              :pagination="serverPagination(taskPage, taskTotal, onTaskPageChange)"
              :row-key="rowKey"
            />
          </NTabPane>

          <NTabPane name="quality" tab="质量报告">
            <NAlert v-if="tabError.quality" type="error" :bordered="false" class="tab-alert">
              {{ tabError.quality }}
              <NButton size="tiny" secondary class="tab-retry" @click="retryActiveTab">重试</NButton>
            </NAlert>
            <NDataTable
              v-else
              :columns="qualityColumns"
              :data="qualityReports"
              :loading="tabLoading.quality"
              :bordered="false"
              :pagination="serverPagination(qualityPage, qualityTotal, onQualityPageChange)"
              :row-key="rowKey"
            />
          </NTabPane>

          <NTabPane name="coverage" tab="数据文件">
            <NForm inline :show-feedback="false" class="coverage-filters">
              <NFormItem label="品种">
                <NInput v-model:value="coverageFilters.symbol" clearable placeholder="symbol" style="width: 100px" />
              </NFormItem>
              <NFormItem label="合约">
                <NInput v-model:value="coverageFilters.contract" clearable placeholder="contract" style="width: 120px" />
              </NFormItem>
              <NFormItem label="周期">
                <NInput v-model:value="coverageFilters.period" clearable placeholder="5m" style="width: 80px" />
              </NFormItem>
              <NFormItem label="质量">
                <NInput v-model:value="coverageFilters.quality" clearable placeholder="passed" style="width: 100px" />
              </NFormItem>
              <NFormItem label="Provider">
                <NInput v-model:value="coverageFilters.provider" clearable placeholder="rqdata" style="width: 110px" />
              </NFormItem>
              <NFormItem label="Binding">
                <NSelect
                  v-model:value="coverageFilters.binding_status"
                  clearable
                  placeholder="全部"
                  style="width: 120px"
                  :options="[
                    { label: 'active', value: 'active' },
                    { label: 'unbound', value: 'unbound' },
                  ]"
                />
              </NFormItem>
              <NFormItem>
                <NSpace>
                  <NButton type="primary" size="small" @click="applyCoverageFilters">筛选</NButton>
                </NSpace>
              </NFormItem>
            </NForm>
            <NAlert v-if="tabError.coverage" type="error" :bordered="false" class="tab-alert">
              {{ tabError.coverage }}
              <NButton size="tiny" secondary class="tab-retry" @click="retryActiveTab">重试</NButton>
            </NAlert>
            <NDataTable
              v-else
              :columns="coverageColumns"
              :data="coverage"
              :loading="tabLoading.coverage"
              :bordered="false"
              :pagination="serverPagination(coveragePage, coverageTotal, onCoveragePageChange)"
              :row-key="rowKey"
              :scroll-x="1680"
            />
          </NTabPane>

          <NTabPane name="profiles" tab="Profile（只读）">
            <NAlert type="info" :bordered="false" class="tab-alert">
              Profile 仅观察，不提供 apply / switch。
            </NAlert>
            <NAlert v-if="tabError.profiles" type="error" :bordered="false" class="tab-alert">
              {{ tabError.profiles }}
              <NButton size="tiny" secondary class="tab-retry" @click="retryActiveTab">重试</NButton>
            </NAlert>
            <NDataTable
              v-else
              :columns="profileColumns"
              :data="profiles"
              :loading="tabLoading.profiles"
              :bordered="false"
              :pagination="{ pageSize: PAGE_SIZE }"
              :row-key="(row: DataProfileInfo) => row.profile_id"
            />
          </NTabPane>
        </NTabs>
      </NCard>
    </div>
  </PageShell>
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

.tab-alert {
  margin-bottom: 12px;
}

.tab-retry {
  margin-left: 12px;
}

.coverage-filters {
  margin-bottom: 12px;
  flex-wrap: wrap;
}

@media (max-width: 1199px) {
  .data-card {
    min-height: 480px;
  }
}
</style>
