<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NTag } from 'naive-ui'
import type { MarketAccessMode } from '@/types/market'
import {
  buildMarketQualificationPresentation,
  type MarketQualificationTone,
} from '@/utils/marketEvidencePresentation'

const props = defineProps<{
  accessMode: MarketAccessMode
  strictResearchReady: boolean
  qualityStatus: string
  profileId: string | null
  profileLabel: string | null
  latestTime: string
  period: string
  versionSummary: string
}>()

const emit = defineEmits<{
  evidence: []
}>()

const qualification = computed(() =>
  buildMarketQualificationPresentation({
    accessMode: props.accessMode,
    strictResearchReady: props.strictResearchReady,
    qualityStatus: props.qualityStatus,
    profileId: props.profileId,
  }),
)

function tagType(tone: MarketQualificationTone) {
  return tone
}

function readableTime(value: string) {
  if (!value || value === '-') return '时间未证明'
  return value.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="market-qualification-summary" aria-label="研究资格与数据新鲜度">
    <NTag size="small" :type="tagType(qualification.tone)" :title="qualification.summary">
      {{ qualification.label }}
    </NTag>
    <NTag size="small" :type="qualityStatus === 'passed' ? 'success' : qualityStatus === 'failed' ? 'error' : 'warning'">
      {{ qualityStatus === 'passed' ? 'Passed' : qualityStatus === 'failed' ? 'Failed' : qualityStatus === 'warning' ? '质量警告' : '质量未知' }}
    </NTag>
    <span>数据至 {{ readableTime(latestTime) }}</span>
    <span>{{ period || '周期未选择' }}</span>
    <span
      v-if="accessMode === 'research' && profileLabel"
      class="market-qualification-summary__profile"
      :title="profileLabel"
    >
      Profile: {{ profileLabel }}
    </span>
    <span class="market-qualification-summary__version">{{ versionSummary }}</span>
    <NButton size="tiny" secondary aria-label="数据证据" @click="emit('evidence')">数据证据</NButton>
  </div>
</template>

<style scoped>
.market-qualification-summary {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--gy-space-2);
  min-width: 0;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
}

.market-qualification-summary__version {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.market-qualification-summary__profile {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.market-qualification-summary > :not(.market-qualification-summary__version) {
  flex: 0 0 auto;
}

@media (max-width: 1199px) {
  .market-qualification-summary {
    flex-wrap: wrap;
  }
}
</style>
