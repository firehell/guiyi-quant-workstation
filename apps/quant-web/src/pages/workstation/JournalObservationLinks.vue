<script setup lang="ts">
import { onScopeDispose, ref, shallowRef, watch } from 'vue'
import { linkObservation, observationLinks, observationTargets, type ObservationLink, type ObservationLinkKind, type ObservationTarget } from '@/api/journalObservations'

const props = defineProps<{ observationId: string }>()
const kind = ref<ObservationLinkKind>('plan'), searching = ref(false), search = ref(''), submitted = ref('')
const linked = shallowRef<ObservationLink[]>([]), choices = shallowRef<ObservationTarget[]>([])
const linksPage = ref(0), choicesPage = ref(0), linksNext = ref<number | null>(null), choicesNext = ref<number | null>(null)
const linksError = ref(''), choicesError = ref(''), message = ref(''), revision = ref(0), searchRevision = ref(0)
const pending = ref(false), loading = ref(false), loadingLinks = ref(false), selected = ref('')
const targetKey = (target: ObservationTarget) => target.target_id + '/' + (target.version ?? '')
const requestKeys = new Map<string,string>()
let generation = 0
watch(() => props.observationId, () => {
  generation++
  requestKeys.clear()
  searching.value = pending.value = false
  search.value = submitted.value = message.value = selected.value = ''
  linksPage.value = choicesPage.value = 0
}, { flush:'sync' })
onScopeDispose(() => { generation++ })
watch([() => props.observationId, linksPage, revision], async (_, __, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  linksError.value = ''; linked.value = []; linksNext.value = null; loadingLinks.value = true
  try {
    const result = await observationLinks(props.observationId, linksPage.value, controller.signal)
    if (!controller.signal.aborted) { linked.value = result.items; linksNext.value = result.next_offset }
  } catch { if (!controller.signal.aborted) linksError.value = '关联记录暂时无法读取。' }
  finally { if (!controller.signal.aborted) loadingLinks.value = false }
}, { immediate:true })
watch(kind, () => { choicesPage.value = 0; submitted.value = search.value = '' }, { flush:'sync' })
watch([searching, () => props.observationId, kind, submitted, choicesPage, searchRevision], async (_, __, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  choicesError.value = selected.value = ''; choices.value = []; choicesNext.value = null
  loading.value = searching.value
  if (!searching.value) return
  try {
    const data = await observationTargets(props.observationId, kind.value, submitted.value, choicesPage.value, controller.signal)
    if (!controller.signal.aborted) { choices.value = data.items; choicesNext.value = data.next_offset }
  } catch { if (!controller.signal.aborted) choicesError.value = '可关联对象暂时无法读取。' }
  finally { if (!controller.signal.aborted) loading.value = false }
})
async function attach() {
  const choice = choices.value.find(t => targetKey(t) === selected.value)
  if (!choice || pending.value) return
  const run = generation, identity = kind.value + '/' + selected.value
  const key = requestKeys.get(identity) ?? crypto.randomUUID()
  requestKeys.set(identity, key)
  pending.value = true; message.value = ''
  try {
    await linkObservation(props.observationId, kind.value, choice, key)
    if (generation === run) { linksPage.value = 0; revision.value++; searching.value = false; message.value = '关联已保存。' }
  } catch { if (generation === run) message.value = '关联未确认，请重试。' }
  finally { if (generation === run) pending.value = false }
}
const planFields = { market: '行情判断', entry: '入场', stop: '止损', target: '目标', sizing: '仓位', scenarios: '情景' } as const
</script>
<template>
  <section class="links">
    <h4>关联计划与案例</h4>
    <p v-if="linksError" role="alert">{{ linksError }} <button type="button" @click="revision++">重试</button></p>
    <p v-else-if="loadingLinks">正在读取关联…</p>
    <p v-else-if="!linked.length">尚未关联计划或案例。</p>
    <ul v-else>
      <li v-for="t in linked" :key="t.kind + targetKey(t)">
        <RouterLink v-if="t.kind === 'case'" :to="{name:'trade-journal',params:{caseId:t.target_id},query:{day:t.trading_day}}">案例 · {{ t.title }}</RouterLink>
        <details v-else-if="t.plan"><summary>计划 · {{ t.title }} · v{{ t.version }}</summary>
          <p>{{ t.trading_day }} · {{ t.scope ?? '全品种' }} · {{ { WATCH:'观察',LONG:'多头',SHORT:'空头' }[t.plan.direction] }}</p>
          <template v-for="(label,key) in planFields" :key="key"><p v-if="t.plan[key]">{{ label }} · {{ t.plan[key] }}</p></template>
        </details>
      </li>
    </ul>
    <button v-if="linksPage" type="button" @click="linksPage -= 30">上一页关联</button>
    <button v-if="linksNext !== null" type="button" @click="linksPage = linksNext">下一页关联</button>
    <button v-if="!searching" type="button" @click="searching = true">关联已有计划或案例</button>
    <form v-else @submit.prevent="choicesPage = 0; submitted = search.trim(); searchRevision++">
      <label>对象<select v-model="kind" :disabled="pending"><option value="plan">计划版本</option><option value="case">交易案例</option></select></label>
      <label>按标题或 ID 搜索<input v-model="search" maxlength="160" :disabled="pending"></label>
      <button type="submit" :disabled="pending">查找</button>
      <p v-if="choicesError" role="alert">{{ choicesError }}</p><p v-else-if="loading">正在查找…</p>
      <p v-else-if="!choices.length">没有匹配的{{ kind === 'plan' ? '品种或全品种计划' : '同合约案例' }}。</p>
      <label v-else>选择要关联的{{ kind === 'plan' ? '计划版本' : '案例' }}<select v-model="selected" :disabled="pending">
        <option value="">请选择</option>
        <option v-for="t in choices" :key="targetKey(t)" :value="targetKey(t)">{{ t.trading_day }} · {{ t.scope ?? '全品种' }} · {{ t.title }}{{ t.version ? ' · v'+t.version : '' }}</option>
      </select></label>
      <button v-if="choicesPage" type="button" :disabled="pending" @click="choicesPage -= 30">上一页对象</button>
      <button v-if="choicesNext !== null" type="button" :disabled="pending" @click="choicesPage = choicesNext">下一页对象</button>
      <button type="button" :disabled="pending || !selected" @click="attach">保存关联</button>
      <button type="button" :disabled="pending" @click="searching = false">取消</button>
    </form>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.links { margin-top:16px; padding-top:10px; border-top:1px solid var(--gy-border); }
h4,p { margin:6px 0; } ul { padding-left:1rem; } label { display:grid; gap:4px; }
form { display:flex; align-items:end; flex-wrap:wrap; gap:8px; } form p { width:100%; }
button, input, select { font:inherit; color:var(--gy-text-primary); background:var(--gy-bg-panel-strong); border:1px solid var(--gy-border); border-radius:4px; padding:5px 8px; max-width:100%; }
button, summary { cursor:pointer; } a { color:var(--gy-link); } li { margin:4px 0; }
</style>
