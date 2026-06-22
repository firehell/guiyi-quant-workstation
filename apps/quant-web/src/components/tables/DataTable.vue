<script setup lang="ts">
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
