<script setup lang="ts">
import { NButton, NRadioButton, NRadioGroup } from 'naive-ui'
import type { MarketAccessMode } from '@/types/market'
import type { ContractViewMode } from '@/utils/marketChartWindow'

export type MarketDataMode = 'historical' | 'live'

defineProps<{
  title: string
  subtitle: string
  busy: boolean
  isLiveMode: boolean
  contractView: ContractViewMode
  dataMode: MarketDataMode
  accessMode: MarketAccessMode
}>()

const emit = defineEmits<{
  back: []
  'update:contractView': [value: ContractViewMode]
  'update:dataMode': [value: MarketDataMode]
  'update:accessMode': [value: MarketAccessMode]
}>()
</script>

<template>
  <div class="market-context-bar" aria-label="Market 上下文">
    <NButton quaternary size="small" @click="emit('back')">← 返回列表</NButton>
    <div class="market-context-bar__title">
      <strong>{{ title }}</strong>
      <span>{{ subtitle }}</span>
    </div>
    <div class="market-context-bar__modes">
      <NRadioGroup aria-label="合约角色" :value="contractView" size="small" :disabled="busy" @update:value="(value) => emit('update:contractView', value)">
        <NRadioButton value="actual">真实主力</NRadioButton>
        <NRadioButton value="continuous">主连研究</NRadioButton>
      </NRadioGroup>
      <NRadioGroup aria-label="行情模式" :value="dataMode" size="small" :disabled="busy" @update:value="(value) => emit('update:dataMode', value)">
        <NRadioButton value="historical">历史</NRadioButton>
        <NRadioButton value="live">Live</NRadioButton>
      </NRadioGroup>
      <NRadioGroup aria-label="研究访问模式" :value="accessMode" size="small" :disabled="isLiveMode || busy" @update:value="(value) => emit('update:accessMode', value)">
        <NRadioButton value="browser">浏览</NRadioButton>
        <NRadioButton value="research">严格研究</NRadioButton>
      </NRadioGroup>
    </div>
  </div>
</template>

<style scoped>
.market-context-bar,
.market-context-bar__modes {
  display: flex;
  align-items: center;
  min-width: 0;
}

.market-context-bar {
  width: 100%;
  gap: var(--gy-space-3);
}

.market-context-bar__title {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.market-context-bar__title strong {
  color: var(--gy-text-primary);
}

.market-context-bar__title span {
  overflow: hidden;
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.market-context-bar__modes {
  flex: 0 0 auto;
  gap: var(--gy-space-2);
}

@media (max-width: 1199px) {
  .market-context-bar {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .market-context-bar__modes {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
