<script setup lang="ts">
import { NCard, NList, NListItem, NThing } from 'naive-ui'
</script>

<template>
  <NCard title="信号监控">
    <NList bordered>
      <NListItem>
        <NThing title="暂无实时信号" description="对接 WebSocket 后，实时交易信号将推送至此页面" />
      </NListItem>
    </NList>
  </NCard>
</template>
