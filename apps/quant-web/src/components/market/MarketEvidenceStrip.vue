<script setup lang="ts">
import { NEllipsis, NTag } from 'naive-ui'

defineProps<{
  provider: string
  dataRole: string
  qualityStatus: string
  strictResearchReady: boolean
  dataVersion: string
  sourceInterval: string
  latestTime: string
}>()

function qualityType(status: string) {
  if (status === 'passed') return 'success' as const
  if (status === 'failed') return 'error' as const
  if (status === 'warning') return 'warning' as const
  return 'default' as const
}
</script>

<template>
  <div class="market-evidence-strip" aria-label="Market 数据证据">
    <NTag size="small" type="info">{{ provider }}</NTag>
    <NTag size="small">{{ dataRole }}</NTag>
    <NTag size="small" :type="qualityType(qualityStatus)">{{ qualityStatus }}</NTag>
    <NTag size="small" :type="strictResearchReady ? 'success' : 'warning'">
      {{ strictResearchReady ? '严格研究可用' : '仅浏览观察' }}
    </NTag>
    <NEllipsis class="market-evidence-strip__version" :tooltip="{ width: 420 }">
      数据版本 {{ dataVersion }}
    </NEllipsis>
    <span>来源周期 {{ sourceInterval }}</span>
    <span>最新 {{ latestTime.replace('T', ' ').slice(0, 16) }}</span>
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

.market-evidence-strip > span,
.market-evidence-strip__version {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.market-evidence-strip__version {
  flex: 1;
  max-width: 360px;
}

@media (max-width: 1199px) {
  .market-evidence-strip {
    width: 100%;
    flex: 1 1 100%;
    flex-wrap: wrap;
  }
}
</style>
