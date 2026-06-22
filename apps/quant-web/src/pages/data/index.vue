<script setup lang="ts">
import { NCard, NDataTable, NButton, NSpace } from 'naive-ui'

const columns = [
  { title: '合约代码', key: 'symbol' },
  { title: '交易所', key: 'exchange' },
  { title: '数据周期', key: 'period' },
  { title: '最新更新', key: 'updatedAt' },
  { title: '数据量', key: 'count' },
  { title: '操作', key: 'actions' },
]
</script>

<template>
  <NCard title="数据中心">
    <template #header-extra>
      <NSpace>
        <NButton type="primary">采集数据</NButton>
        <NButton>导出 Parquet</NButton>
      </NSpace>
    </template>
    <NDataTable :columns="columns" :data="[]" :bordered="false" />
  </NCard>
</template>
