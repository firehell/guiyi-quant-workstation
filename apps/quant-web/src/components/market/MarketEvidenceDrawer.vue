<script setup lang="ts">
import { computed } from 'vue'
import { NDrawer, NDrawerContent, NTag } from 'naive-ui'
import type { MarketBarsCoverage, MarketReadLineage } from '@/types/market'

const props = defineProps<{
  show: boolean
  lineage: MarketReadLineage | null
  coverage: MarketBarsCoverage | null
  qualityStatus: string
  crossFileConflictCount: number
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const rawVersions = computed(() => {
  const values = [
    props.lineage?.data_version,
    ...(props.lineage?.data_versions || []),
    props.coverage?.data_version,
  ].filter((value): value is string => Boolean(value))
  return [...new Set(values)]
})

function list(values: Array<string | number | null | undefined>) {
  const present = values.filter((value) => value !== null && value !== undefined && value !== '')
  return present.length ? present.join('、') : '未提供'
}

function tokenSummary(value: string | null | undefined) {
  if (!value) return '未提供'
  return value.length > 20 ? `${value.slice(0, 12)}…${value.slice(-6)}` : value
}

function readableTime(value: string | null | undefined) {
  return value ? value.replace('T', ' ').slice(0, 19) : '未提供'
}
</script>

<template>
  <NDrawer
    :show="show"
    :width="520"
    placement="right"
    aria-label="数据证据"
    @update:show="(value) => emit('update:show', value)"
  >
    <NDrawerContent title="数据证据" closable>
      <div class="market-evidence-drawer">
        <p class="market-evidence-drawer__intro">
          当前图表读取证据，仅用于审计与排障；不包含物理路径或凭据。
        </p>

        <section>
          <h3>资格与来源</h3>
          <dl>
            <dt>访问模式</dt><dd>{{ lineage?.access_mode || '未提供' }}</dd>
            <dt>严格研究资格</dt><dd>{{ lineage?.strict_research_ready ? '通过' : '未通过' }}</dd>
            <dt>质量</dt><dd><NTag size="small">{{ qualityStatus }}</NTag></dd>
            <dt>provider</dt><dd>{{ lineage?.provider || coverage?.provider || '未提供' }}</dd>
            <dt>data_role</dt><dd>{{ lineage?.data_role || coverage?.data_role || '未提供' }}</dd>
            <dt>Profile ID</dt><dd>{{ lineage?.profile_id || coverage?.profile_id || '未绑定' }}</dd>
            <dt>quality policy</dt><dd>{{ lineage?.quality_policy || coverage?.quality_policy || '未提供' }}</dd>
          </dl>
        </section>

        <section>
          <h3>版本与 lineage</h3>
          <dl>
            <dt>raw data version</dt><dd class="market-evidence-drawer__raw">{{ list(rawVersions) }}</dd>
            <dt>file IDs</dt><dd>{{ list(lineage?.market_data_file_ids || [coverage?.market_data_file_id]) }}</dd>
            <dt>asset count</dt><dd>{{ lineage?.asset_evidence?.length || lineage?.market_data_file_ids?.length || 0 }}</dd>
            <dt>source interval</dt><dd>{{ list(lineage?.source_intervals || [lineage?.source_interval]) }}</dd>
            <dt>interval basis</dt><dd>{{ lineage?.source_interval_basis || '未提供' }}</dd>
            <dt>lineage token</dt><dd>{{ tokenSummary(lineage?.lineage_token) }}</dd>
            <dt>跨文件冲突</dt><dd>{{ crossFileConflictCount.toLocaleString('zh-CN') }}</dd>
          </dl>
        </section>

        <section>
          <h3>覆盖范围</h3>
          <dl>
            <dt>连续合约</dt><dd>{{ lineage?.continuous_contract || coverage?.continuous_contract || '未提供' }}</dd>
            <dt>实际合约</dt><dd>{{ lineage?.actual_contract || coverage?.actual_contract || coverage?.contract || '未提供' }}</dd>
            <dt>开始</dt><dd>{{ readableTime(coverage?.start_time) }}</dd>
            <dt>结束</dt><dd>{{ readableTime(coverage?.end_time) }}</dd>
            <dt>最新 Bar</dt><dd>{{ readableTime(coverage?.latest_bar_time) }}</dd>
            <dt>行数</dt><dd>{{ (coverage?.row_count || 0).toLocaleString('zh-CN') }}</dd>
          </dl>
        </section>

        <section v-if="lineage?.asset_evidence?.length">
          <h3>资产摘要</h3>
          <article
            v-for="asset in lineage.asset_evidence"
            :key="asset.market_data_file_id"
            class="market-evidence-drawer__asset"
          >
            <strong>File #{{ asset.market_data_file_id }}</strong>
            <span>{{ asset.provider }} · {{ asset.data_role }} · {{ asset.quality_status }}</span>
            <span>checksum {{ tokenSummary(asset.checksum) }}</span>
            <span>{{ readableTime(asset.start_time) }} → {{ readableTime(asset.end_time) }}</span>
          </article>
        </section>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.market-evidence-drawer {
  display: grid;
  gap: var(--gy-space-4);
  color: var(--gy-text-secondary);
}

.market-evidence-drawer__intro {
  margin: 0;
  color: var(--gy-text-muted);
}

.market-evidence-drawer section {
  padding: var(--gy-space-3);
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-md);
}

.market-evidence-drawer h3 {
  margin: 0 0 var(--gy-space-3);
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-md);
}

.market-evidence-drawer dl {
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr);
  gap: var(--gy-space-2) var(--gy-space-3);
  margin: 0;
}

.market-evidence-drawer dt {
  color: var(--gy-text-muted);
}

.market-evidence-drawer dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--gy-text-primary);
}

.market-evidence-drawer__raw {
  font-family: var(--gy-font-mono);
  font-size: var(--gy-font-size-xs);
}

.market-evidence-drawer__asset {
  display: grid;
  gap: 3px;
  padding: var(--gy-space-2) 0;
  border-top: 1px solid var(--gy-border-subtle);
}

.market-evidence-drawer__asset:first-of-type {
  border-top: 0;
}

.market-evidence-drawer__asset span {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}
</style>
