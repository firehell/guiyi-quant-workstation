<script setup lang="ts">
import BrandMark from './BrandMark.vue'

withDefaults(
  defineProps<{
    collapsed?: boolean
  }>(),
  {
    collapsed: false,
  },
)
</script>

<template>
  <div class="brand-logo" :class="{ 'brand-logo--collapsed': collapsed }">
    <BrandMark :size="collapsed ? 36 : 38" />
    <span v-if="!collapsed" class="brand-logo__copy">
      <strong>归一量化</strong>
      <small>GUIYI QUANT</small>
    </span>
  </div>
</template>

<style scoped>
.brand-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.brand-logo--collapsed {
  justify-content: center;
}

.brand-logo__copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.brand-logo__copy strong {
  color: #ffffff;
  font-size: 17px;
  letter-spacing: 0.06em;
  white-space: nowrap;
}

.brand-logo__copy small {
  margin-top: 2px;
  color: var(--gy-shell-text-muted);
  font-family: var(--gy-font-mono);
  font-size: 8px;
  letter-spacing: 0.12em;
  white-space: nowrap;
}
</style>
