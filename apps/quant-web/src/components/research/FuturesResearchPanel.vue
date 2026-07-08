<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NDrawer, NDrawerContent, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import { getFuturesResearchPanel, getFuturesResearchPanels, MEMBER_RANK_BY_OPTIONS } from '@/api/futuresResearch'
import ResearchChart from '@/components/research/ResearchChart.vue'
import ResearchDataTable from '@/components/research/ResearchDataTable.vue'
import type {
  FuturesResearchPanelId,
  FuturesResearchPanelMeta,
  FuturesResearchPanelResponse,
  MemberRankBy,
} from '@/types/futuresResearch'

const props = defineProps<{
  symbol: string | null
  contract: string | null
  dateRange: [number, number] | null
}>()

const message = useMessage()
const loadingCatalog = ref(false)
const loadingPanel = ref(false)
const drawerVisible = ref(false)
const activePanelId = ref<FuturesResearchPanelId | null>(null)
const panelCatalog = ref<FuturesResearchPanelMeta[]>([])
const panelData = ref<FuturesResearchPanelResponse | null>(null)
const error = ref<string | null>(null)
const memberRankBy = ref<MemberRankBy>('volume')

const queryRange = computed(() => {
  if (!props.dateRange) return { start: undefined, end: undefined }
  return {
    start: formatDate(props.dateRange[0]),
    end: formatDate(props.dateRange[1]),
  }
})

const activePanelMeta = computed(() =>
  panelCatalog.value.find((item) => item.panel_id === activePanelId.value) || null,
)

const coverageText = computed(() => {
  const coverage = panelData.value?.coverage
  if (!coverage) return '-'
  const local =
    coverage.local_min_date && coverage.local_max_date
      ? `${coverage.local_min_date} ~ ${coverage.local_max_date}`
      : '无本地覆盖'
  return `${local} / 请求 ${coverage.requested_start} ~ ${coverage.requested_end}`
})

const snapshotTradeDate = computed(() => {
  if (activePanelId.value !== 'member-rank' || !panelData.value?.rows?.length) return null
  const firstRow = panelData.value.rows[0] as { snapshot_trade_date?: string }
  return firstRow.snapshot_trade_date || null
})

watch(
  () => [props.symbol, props.contract],
  () => {
    void loadCatalog()
  },
  { immediate: true },
)

watch(
  () => [props.symbol, props.contract, props.dateRange, activePanelId.value, drawerVisible.value, memberRankBy.value],
  () => {
    if (!drawerVisible.value || !activePanelId.value) return
    void loadActivePanel()
  },
)

async function loadCatalog() {
  if (!props.symbol) {
    panelCatalog.value = []
    return
  }
  loadingCatalog.value = true
  error.value = null
  try {
    const response = await getFuturesResearchPanels({
      symbol: props.symbol,
      contract: props.contract,
    })
    panelCatalog.value = response.panels
  } catch (err) {
    panelCatalog.value = []
    error.value = apiError(err, '加载研究面板目录失败')
  } finally {
    loadingCatalog.value = false
  }
}

async function openPanel(panel: FuturesResearchPanelMeta) {
  if (!props.symbol || !panel.enabled) return
  activePanelId.value = panel.panel_id as FuturesResearchPanelId
  if (activePanelId.value !== 'member-rank') {
    memberRankBy.value = 'volume'
  }
  drawerVisible.value = true
  await loadActivePanel()
}

async function loadActivePanel() {
  if (!props.symbol || !activePanelId.value) return
  loadingPanel.value = true
  error.value = null
  try {
    panelData.value = await getFuturesResearchPanel(activePanelId.value, {
      symbol: props.symbol,
      contract: props.contract,
      start: queryRange.value.start,
      end: queryRange.value.end,
      ...(activePanelId.value === 'member-rank' ? { rank_by: memberRankBy.value } : {}),
    })
  } catch (err) {
    panelData.value = null
    error.value = apiError(err, '加载研究面板数据失败')
    message.error(error.value)
  } finally {
    loadingPanel.value = false
  }
}

function formatDate(value: number) {
  const item = new Date(value)
  const year = item.getFullYear()
  const month = String(item.getMonth() + 1).padStart(2, '0')
  const day = String(item.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function apiError(err: unknown, fallback: string) {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response
    return response?.data?.detail || fallback
  }
  return err instanceof Error ? err.message : fallback
}
</script>

<template>
  <section class="research-panel">
    <div class="research-panel__title">
      <span>品种研究</span>
      <NTag size="small" type="info">本地 PG</NTag>
    </div>
    <p v-if="!symbol" class="research-panel__hint">请选择品种后查看 RQData 结构化研究数据。</p>
    <NAlert v-else-if="error && !drawerVisible" type="warning" :bordered="false" size="small">{{ error }}</NAlert>
    <div v-else class="research-panel__buttons">
      <NSpin :show="loadingCatalog" size="small">
        <div class="button-grid">
          <NButton
            v-for="panel in panelCatalog"
            :key="panel.panel_id"
            size="tiny"
            secondary
            block
            :disabled="!panel.enabled || !symbol"
            :title="panel.reason || panel.description"
            @click="openPanel(panel)"
          >
            {{ panel.label }}
          </NButton>
        </div>
      </NSpin>
    </div>

    <NDrawer v-model:show="drawerVisible" :width="920" placement="right">
      <NDrawerContent
        closable
        :title="`${activePanelMeta?.label || '品种研究'} · ${symbol || '-'}${contract ? ` · ${contract}` : ''}`"
      >
        <div class="drawer-meta">
          <span>来源 {{ panelData?.source || 'local_postgresql' }} / {{ panelData?.provider || 'rqdata' }}</span>
          <span v-if="panelData?.data_version">版本 {{ panelData.data_version }}</span>
          <span>行数 {{ panelData?.row_count ?? 0 }}</span>
          <span v-if="activePanelId === 'member-rank'">品种会员排名</span>
          <span v-if="snapshotTradeDate">快照日 {{ snapshotTradeDate }}</span>
        </div>
        <div v-if="activePanelId === 'member-rank'" class="drawer-controls">
          <span class="drawer-controls__label">排名依据</span>
          <NSelect
            v-model:value="memberRankBy"
            size="small"
            :options="MEMBER_RANK_BY_OPTIONS"
            style="width: 160px"
          />
        </div>
        <div class="drawer-meta">{{ coverageText }}</div>

        <NAlert v-if="panelData?.empty_reason" type="warning" :bordered="false" class="drawer-alert">
          {{ panelData.empty_reason }}
        </NAlert>
        <NAlert v-if="error" type="error" :bordered="false" class="drawer-alert">{{ error }}</NAlert>

        <NSpin :show="loadingPanel">
          <ResearchChart v-if="panelData" :chart="panelData.chart" height="280px" />
          <ResearchDataTable
            v-if="panelData"
            class="drawer-table"
            :columns="panelData.columns"
            :rows="panelData.rows"
            :loading="loadingPanel"
          />
        </NSpin>
      </NDrawerContent>
    </NDrawer>
  </section>
</template>

<style scoped>
.research-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.research-panel__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
}

.research-panel__hint {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

.button-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.drawer-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 8px;
  color: #94a3b8;
  font-size: 12px;
}

.drawer-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.drawer-controls__label {
  color: #94a3b8;
  font-size: 12px;
}

.drawer-alert {
  margin-bottom: 12px;
}

.drawer-table {
  margin-top: 16px;
}
</style>
