<script setup lang="ts">
/** 研究面板数据表：ColumnSpec → Naive 列定义，空值显示为 '-' */
import { computed, h } from 'vue'
import { NDataTable } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import type { ColumnSpec } from '@/types/futuresResearch'

const props = defineProps<{
  columns: ColumnSpec[]
  rows: Record<string, unknown>[]
  loading?: boolean
}>()

/** 将后端列规格映射为 DataTable columns */
const tableColumns = computed<DataTableColumns<Record<string, unknown>>>(() =>
  props.columns.map((column) => ({
    title: column.title,
    key: column.key,
    width: column.width || undefined,
    ellipsis: { tooltip: true },
    render: (row) => {
      const value = row[column.key]
      if (value === null || value === undefined || value === '') return '-'
      return h('span', String(value))
    },
  })),
)
</script>

<template>
  <NDataTable
    :columns="tableColumns"
    :data="rows"
    :loading="loading"
    :bordered="false"
    size="small"
    :pagination="rows.length > 20 ? { pageSize: 20 } : false"
    :scroll-x="960"
    max-height="320"
  />
</template>
