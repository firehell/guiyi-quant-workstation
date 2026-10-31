<script setup lang="ts">
defineProps<{state:'active'|'gone'}>()
</script>
<template><i class="newow-tr-badge" :class="{gone:state==='gone'}" aria-hidden="true" /></template>
<style scoped>
.newow-tr-badge{position:absolute;right:3px;top:3px;width:6px;height:6px;box-sizing:border-box;border-radius:50%;background:#FF453A;pointer-events:none}.newow-tr-badge.gone{background:transparent;border:1.5px solid #FF453A}
</style>
