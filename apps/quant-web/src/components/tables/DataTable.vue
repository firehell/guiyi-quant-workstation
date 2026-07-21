<script setup lang="ts">
/** 通用数据表封装：固定分页与无边框样式 */
import { NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'

defineProps<{
  columns: DataTableColumns
  data: any[]
  loading?: boolean
}>()
</script>

<template>
  <NDataTable
    :columns="$props.columns"
    :data="$props.data"
    :loading="$props.loading"
    :bordered="false"
    :pagination="{ pageSize: 20 }"
    remote
  />
</template>
