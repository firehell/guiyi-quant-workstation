<script setup lang="ts">
import { NCard, NDataTable, NButton, NTag, NSpace } from 'naive-ui'

const columns = [
  { title: '策略名称', key: 'name' },
  { title: '类型', key: 'type' },
  { title: '状态', key: 'status' },
  { title: '创建时间', key: 'createdAt' },
  { title: '操作', key: 'actions' },
]
</script>

<template>
  <NCard title="策略管理">
    <template #header-extra>
      <NButton type="primary">新建策略</NButton>
    </template>
    <NDataTable :columns="columns" :data="[]" :bordered="false" />
  </NCard>
</template>
