<script setup lang="ts">
/** 系统设置：本地 API/WebSocket 地址与显示偏好，写入 app store 持久化。 */
import { onMounted, ref } from 'vue'
import { NAlert, NButton, NCard, NForm, NFormItem, NInput, NSelect, NSwitch, useMessage } from 'naive-ui'
import { getRuntimeHealth } from '@/api/runtime'
import { useAppStore } from '@/stores/app'
import { loadAppSettings, type AppSettings } from '@/utils/settings'
import PageShell from '@/components/common/PageShell.vue'
import CapabilityBadge from '@/components/common/CapabilityBadge.vue'
import { toSafeApiError } from '@/utils/errorRedaction'

const message = useMessage()
const appStore = useAppStore()
const testingConnection = ref(false)

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

async function testConnection() {
  testingConnection.value = true
  try {
    const health = await getRuntimeHealth()
    message.success(`连接正常：runtime ${health.status} · ${health.generated_at || 'ok'}`)
  } catch (err) {
    message.error(toSafeApiError(err, '连接测试失败'))
  } finally {
    testingConnection.value = false
  }
}

onMounted(() => {
  form.value = loadAppSettings()
})
</script>

<template>
  <PageShell title="系统设置" subtitle="本地工作站连接与显示偏好；连接测试仅调用 /api/runtime/health">
    <template #badges>
      <CapabilityBadge kind="observation-only" label="无 Token 展示" />
    </template>
    <NCard class="settings-card">
      <NAlert type="info" :bordered="false" class="settings-note">
        本页不读取或展示 API Token / Webhook；连接测试只验证 health 可达性。
      </NAlert>
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
          <NButton :loading="testingConnection" @click="testConnection">测试连接</NButton>
          <NButton type="primary" style="margin-left: 12px" @click="save">保存设置</NButton>
        </NFormItem>
      </NForm>
    </NCard>
  </PageShell>
</template>

<style scoped>
.settings-card {
  max-width: 920px;
}

.settings-note {
  margin-bottom: 12px;
}

@media (max-width: 1199px) {
  .settings-card :deep(.n-form-item) {
    display: block;
  }
}
</style>
