<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { ProductOption } from '@/utils/productSearch'
import { searchProductOptions } from '@/utils/productSearch'

const props = withDefaults(defineProps<{
  options: readonly ProductOption[]
  selectedSymbol?: string | null
  status?: 'ready' | 'loading' | 'error'
  label?: string
}>(), {
  selectedSymbol: null,
  status: 'ready',
  label: '搜索品种',
})

const emit = defineEmits<{ select: [option: ProductOption] }>()
const rootRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const query = ref('')
const open = ref(false)
const activeIndex = ref(0)
const listboxId = `product-selector-${Math.random().toString(36).slice(2)}`
let previousFocus: HTMLElement | null = null

const matches = computed(() => searchProductOptions(props.options, query.value))
const selected = computed(() => props.options.find((item) => item.symbol === props.selectedSymbol?.toLowerCase()) ?? null)
const activeOption = computed(() => matches.value[activeIndex.value] ?? null)
const activeId = computed(() => activeOption.value ? `${listboxId}-${activeOption.value.symbol}` : undefined)

watch(matches, (items) => {
  if (activeIndex.value >= items.length) activeIndex.value = Math.max(0, items.length - 1)
})
watch(() => props.selectedSymbol, () => { query.value = '' })

function show() {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  open.value = true
  activeIndex.value = Math.max(0, matches.value.findIndex((item) => item.symbol === props.selectedSymbol?.toLowerCase()))
}

function close(restoreFocus = true) {
  open.value = false
  activeIndex.value = 0
  if (restoreFocus) void nextTick(() => inputRef.value?.focus() ?? previousFocus?.focus())
}

function move(delta: number) {
  if (!open.value) show()
  if (!matches.value.length) return
  activeIndex.value = (activeIndex.value + delta + matches.value.length) % matches.value.length
}

function choose(option: ProductOption | null) {
  if (!option) return
  emit('select', option)
  query.value = ''
  close()
}

function handleDocumentPointer(event: PointerEvent) {
  if (open.value && !rootRef.value?.contains(event.target as Node)) close(false)
}

defineExpose({ focus: () => inputRef.value?.focus() })
onMounted(() => document.addEventListener('pointerdown', handleDocumentPointer))
onBeforeUnmount(() => document.removeEventListener('pointerdown', handleDocumentPointer))
</script>

<template>
  <div ref="rootRef" class="product-selector" :data-open="open">
    <label class="product-selector__label">
      <span class="product-selector__sr-only">{{ label }}</span>
      <input
        ref="inputRef"
        v-model="query"
        role="combobox"
        type="search"
        autocomplete="off"
        :placeholder="selected ? `${selected.name} ${selected.symbol.toUpperCase()}` : label"
        :aria-label="label"
        :aria-expanded="open"
        :aria-controls="listboxId"
        :aria-activedescendant="activeId"
        @focus="show"
        @input="show"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.enter.prevent="choose(activeOption)"
        @keydown.esc.prevent="close()"
      >
    </label>
    <div v-if="open" :id="listboxId" class="product-selector__popover" role="listbox" :aria-label="label">
      <p v-if="status === 'loading'" class="product-selector__state" role="status">正在读取品种目录…</p>
      <p v-else-if="status === 'error'" class="product-selector__state" role="alert">目录加载失败，无法安全切换品种。</p>
      <p v-else-if="matches.length === 0" class="product-selector__state" role="status">没有匹配品种</p>
      <button
        v-for="(option, index) in status === 'ready' ? matches : []"
        :id="`${listboxId}-${option.symbol}`"
        :key="option.symbol"
        type="button"
        role="option"
        :aria-selected="option.symbol === selectedSymbol?.toLowerCase()"
        :class="{ 'is-active': index === activeIndex }"
        @mousemove="activeIndex = index"
        @click="choose(option)"
      >
        <span>{{ option.name }}</span>
        <strong>{{ option.symbol.toUpperCase() }}</strong>
        <small>{{ option.contract ?? '当前合约待读取' }}</small>
      </button>
    </div>
  </div>
</template>

<style scoped>
.product-selector { position: relative; min-width: min(280px, 42vw); }
.product-selector__label { display: block; }
.product-selector input { width: 100%; min-height: 36px; padding: 0 12px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); font: inherit; }
.product-selector input:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.product-selector__popover { position: absolute; z-index: 30; top: calc(100% + 6px); left: 0; width: min(360px, calc(100vw - 24px)); max-height: min(420px, 60vh); overflow-y: auto; padding: 6px; border: 1px solid var(--gy-border); border-radius: var(--gy-radius-md); background: var(--gy-bg-panel); box-shadow: var(--gy-shadow-md); }
.product-selector__popover button { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 10px; width: 100%; min-height: 44px; padding: 7px 10px; border: 0; border-radius: var(--gy-radius-sm); color: var(--gy-text-primary); background: transparent; font: inherit; text-align: left; cursor: pointer; }
.product-selector__popover button:hover, .product-selector__popover button.is-active { background: var(--gy-bg-hover); }
.product-selector__popover button[aria-selected="true"] { box-shadow: inset 3px 0 var(--gy-accent); }
.product-selector__popover strong { color: var(--gy-text-secondary); font-family: var(--gy-font-mono); }
.product-selector__popover small { grid-column: 1 / -1; color: var(--gy-text-muted); }
.product-selector__state { margin: 0; padding: 12px; color: var(--gy-text-muted); }
.product-selector__sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 640px) { .product-selector { min-width: 0; width: 100%; } .product-selector input { min-height: 44px; } }
</style>
