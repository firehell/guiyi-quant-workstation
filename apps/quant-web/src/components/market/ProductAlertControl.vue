<script setup lang="ts">
import { computed } from 'vue'
import { NSpin, NSwitch, NTag } from 'naive-ui'
import type { ProductAlertRuleState } from '@/api/alerts'
import { alertRuntimeLabel, type AlertRuntimeStatus } from '@/utils/alertControl'

const props = defineProps<{
  rule: ProductAlertRuleState | null
  runtimeStatus: AlertRuntimeStatus | null
  loading: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  toggle: [enabled: boolean]
}>()

const runtimeLabel = computed(() => alertRuntimeLabel(props.runtimeStatus))
const runtimeTagType = computed(() => props.runtimeStatus === 'ok'
  ? 'success'
  : props.runtimeStatus === 'disabled' ? 'default' : 'warning')
</script>

<template>
  <section class="product-alert-control" data-testid="product-alert-control">
    <NSpin :show="loading" size="small">
      <div class="product-alert-control__row">
        <span>{{ rule?.display_name || '火天大有' }} · 15m 实际主力</span>
        <NSwitch
          :value="rule?.enabled_for_product || false"
          :disabled="!rule || loading || saving"
          :loading="saving"
          @update:value="emit('toggle', $event)"
        />
      </div>
      <div class="product-alert-control__row">
        <span>Alert Runtime</span>
        <NTag size="small" :type="runtimeTagType">{{ runtimeLabel }}</NTag>
      </div>
    </NSpin>
  </section>
</template>

<style scoped>
.product-alert-control { display: grid; gap: 10px; }
.product-alert-control__row { display: flex; justify-content: space-between; gap: 12px; align-items: center; font-size: var(--gy-font-size-sm); }
.product-alert-control__row > span:first-child { color: var(--gy-text-muted); }
</style>
