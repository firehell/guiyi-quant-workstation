<script setup lang="ts">
import { NCard, NGrid, NGridItem, NStatistic } from 'naive-ui'
</script>

<template>
  <div>
    <NGrid :cols="4" :x-gap="16" :y-gap="16">
      <NGridItem>
        <NCard>
          <NStatistic label="今日信号" :value="12" />
        </NCard>
      </NGridItem>
      <NGridItem>
        <NCard>
          <NStatistic label="活跃策略" :value="3" />
        </NCard>
      </NGridItem>
      <NGridItem>
        <NCard>
          <NStatistic label="回测任务" :value="5" />
        </NCard>
      </NGridItem>
      <NGridItem>
        <NCard>
          <NStatistic label="数据合约" :value="48" />
        </NCard>
      </NGridItem>
    </NGrid>

    <NCard title="快速概览" style="margin-top: 16px">
      <p>仪表盘首页 — 待对接后端 API 后填充实时数据。</p>
    </NCard>
  </div>
</template>
