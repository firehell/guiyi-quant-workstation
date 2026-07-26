<script setup lang="ts">
import { computed } from 'vue'
import MarketQualificationSummary from './MarketQualificationSummary.vue'
import type { MarketAccessMode } from '@/types/market'
import { summarizeDataVersion } from '@/utils/marketEvidencePresentation'

const props = defineProps<{
  accessMode: MarketAccessMode
  qualityStatus: string
  strictResearchReady: boolean
  dataVersion: string
  dataVersions: string[]
  assetCount: number
  latestTime: string
  period: string
  profileId: string | null
  profileLabel: string | null
}>()

const emit = defineEmits<{
  evidence: []
}>()

const versionSummary = computed(() =>
  summarizeDataVersion(props.dataVersion, props.dataVersions, props.assetCount),
)
</script>

<template>
  <div class="market-evidence-strip" aria-label="Market 数据证据">
    <MarketQualificationSummary
      :access-mode="accessMode"
      :strict-research-ready="strictResearchReady"
      :quality-status="qualityStatus"
      :profile-id="profileId"
      :profile-label="profileLabel"
      :latest-time="latestTime"
      :period="period"
      :version-summary="versionSummary"
      @evidence="emit('evidence')"
    />
  </div>
</template>

<style scoped>
.market-evidence-strip {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--gy-space-2);
  min-width: 0;
  overflow: hidden;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}

@media (max-width: 1199px) {
  .market-evidence-strip {
    width: 100%;
    flex: 1 1 100%;
    flex-wrap: wrap;
  }
}
</style>
