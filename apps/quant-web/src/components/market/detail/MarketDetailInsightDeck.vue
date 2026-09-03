<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { MarketDetailDisclosureSection } from '@/types/marketDetail'
import MarketDetailDisclosure from './MarketDetailDisclosure.vue'

const props = withDefaults(defineProps<{
  identityKey: string
  sections: readonly MarketDetailDisclosureSection[]
  defaultOpen?: boolean
}>(), { defaultOpen: true })

const openIds = ref<string[]>(props.defaultOpen && props.sections[0] ? [props.sections[0].id] : [])
const mobile = ref(false)
let media: MediaQueryList | null = null

function syncMedia(event: MediaQueryListEvent | MediaQueryList) {
  mobile.value = event.matches
  if (mobile.value && openIds.value.length > 1) openIds.value = openIds.value.slice(0, 1)
}

function toggle(id: string) {
  if (openIds.value.includes(id)) {
    openIds.value = openIds.value.filter((item) => item !== id)
    return
  }
  openIds.value = mobile.value ? [id] : [...openIds.value, id]
}

function reset() {
  openIds.value = props.defaultOpen && props.sections[0] ? [props.sections[0].id] : []
}

watch(() => props.identityKey, reset)
watch(() => props.sections.map((section) => section.id).join('|'), reset)

onMounted(() => {
  media = window.matchMedia('(max-width: 480px)')
  syncMedia(media)
  media.addEventListener('change', syncMedia)
})
onBeforeUnmount(() => media?.removeEventListener('change', syncMedia))
</script>

<template>
  <div class="detail-insight-deck" data-detail-section="insights">
    <MarketDetailDisclosure
      v-for="section in sections"
      :key="section.id"
      :section="section"
      :open="openIds.includes(section.id)"
      @toggle="toggle(section.id)"
    />
  </div>
</template>

<style scoped>
.detail-insight-deck { display: grid; gap: var(--gy-space-2); padding-bottom: var(--gy-space-4); }
</style>
