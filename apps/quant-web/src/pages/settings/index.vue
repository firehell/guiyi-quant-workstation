<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NButton, NCard, NForm, NFormItem, NInput, NSelect, NSwitch, useMessage } from 'naive-ui'
import { useAppStore } from '@/stores/app'
import { loadAppSettings, type AppSettings } from '@/utils/settings'

const message = useMessage()
const appStore = useAppStore()

const form = ref<AppSettings>(loadAppSettings())

const exchangeOptions = [
  { label: 'SHFE', value: 'SHFE' },
  { label: 'CFFEX', value: 'CFFEX' },
  { label: 'DCE', value: 'DCE' },
  { label: 'CZCE', value: 'CZCE' },
]

function save() {
  appStore.updateSettings({ ...form.value })
  message.success('设置已保存，API 请求将使用新地址')
}

onMounted(() => {
  form.value = loadAppSettings()
})
</script>

<template>
  <NCard title="系统设置">
    <NForm label-placement="left" label-width="120">
      <NFormItem label="API 地址">
        <NInput v-model:value="form.apiBaseUrl" placeholder="留空则使用 Vite 代理 / 环境变量" />
      </NFormItem>
      <NFormItem label="WebSocket 地址">
        <NInput v-model:value="form.wsUrl" placeholder="留空则自动推断 ws(s)://host/ws" />
      </NFormItem>
      <NFormItem label="默认交易所">
        <NSelect v-model:value="form.defaultExchange" style="width: 200px" :options="exchangeOptions" />
      </NFormItem>
      <NFormItem label="涨跌颜色">
        <NSwitch v-model:value="form.redUpGreenDown" />
        <span style="margin-left: 12px; color: var(--gy-text-muted)">红涨绿跌（A股习惯）</span>
      </NFormItem>
      <NFormItem>
        <NButton type="primary" @click="save">保存设置</NButton>
      </NFormItem>
    </NForm>
  </NCard>
</template>
