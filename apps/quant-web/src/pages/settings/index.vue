<script setup lang="ts">
import { NCard, NForm, NFormItem, NInput, NSelect, NSwitch, NButton } from 'naive-ui'
</script>

<template>
  <NCard title="系统设置">
    <NForm label-placement="left" label-width="120">
      <NFormItem label="API 地址">
        <NInput placeholder="http://localhost:8000" />
      </NFormItem>
      <NFormItem label="WebSocket 地址">
        <NInput placeholder="ws://localhost:8000/ws" />
      </NFormItem>
      <NFormItem label="默认交易所">
        <NSelect style="width: 200px" :options="[{ label: 'SHFE', value: 'SHFE' }, { label: 'CFFEX', value: 'CFFEX' }, { label: 'DCE', value: 'DCE' }, { label: 'CZCE', value: 'CZCE' }]" />
      </NFormItem>
      <NFormItem label="涨跌颜色">
        <NSwitch />
        <span style="margin-left: 12px; color: #999">红涨绿跌（A股习惯）</span>
      </NFormItem>
      <NFormItem>
        <NButton type="primary">保存设置</NButton>
      </NFormItem>
    </NForm>
  </NCard>
</template>
