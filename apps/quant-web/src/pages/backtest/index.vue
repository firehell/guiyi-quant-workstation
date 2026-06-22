<script setup lang="ts">
import { NCard, NForm, NFormItem, NSelect, NDatePicker, NButton, NSpace, NDataTable } from 'naive-ui'

const columns = [
  { title: '回测ID', key: 'id' },
  { title: '策略', key: 'strategy' },
  { title: '区间', key: 'range' },
  { title: '收益', key: 'pnl' },
  { title: '最大回撤', key: 'maxDrawdown' },
  { title: '夏普比率', key: 'sharpe' },
  { title: '状态', key: 'status' },
]
</script>

<template>
  <NCard title="回测中心">
    <NForm inline label-placement="left">
      <NFormItem label="策略">
        <NSelect style="width: 200px" placeholder="选择策略" />
      </NFormItem>
      <NFormItem label="时间区间">
        <NDatePicker type="daterange" clearable />
      </NFormItem>
      <NFormItem>
        <NButton type="primary">开始回测</NButton>
      </NFormItem>
    </NForm>
    <NDataTable :columns="columns" :data="[]" :bordered="false" style="margin-top: 16px" />
  </NCard>
</template>
