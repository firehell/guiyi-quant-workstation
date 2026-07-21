<script setup lang="ts">
/** 系统设置：本地 API/WebSocket 地址与显示偏好，写入 app store 持久化。 */
import { onMounted, ref } from 'vue'
import { NButton, NCard, NForm, NFormItem, NInput, NSelect, NSwitch, useMessage } from 'naive-ui'
import { useAppStore } from '@/stores/app'
import { loadAppSettings, type AppSettings } from '@/utils/settings'
import PageShell from '@/components/common/PageShell.vue'

const message = useMessage()
const appStore = useAppStore()

const form = ref<AppSettings>(loadAppSettings())

const exchangeOptions = [
  { label: 'SHFE', value: 'SHFE' },
  { label: 'CFFEX', value: 'CFFEX' },
  { label: 'DCE', value: 'DCE' },
  { label: 'CZCE', value: 'CZCE' },
]

/** 保存设置到 store；后续请求自动使用新 baseUrl。 */
function save() {
  appStore.updateSettings({ ...form.value })
  message.success('设置已保存，API 请求将使用新地址')
}

onMounted(() => {
  form.value = loadAppSettings()
})
</script>

<template>
  <PageShell title="系统设置" subtitle="本地工作站连接与显示偏好">
    <NCard class="settings-card">
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
  </PageShell>
</template>

<style scoped>
.settings-card {
  max-width: 920px;
}

@media (max-width: 1199px) {
  .settings-card :deep(.n-form-item) {
    display: block;
  }
}
</style>
