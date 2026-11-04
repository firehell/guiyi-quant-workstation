<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { volumeScores, type VolumeBar } from '@/utils/volumeDisplay'
const props = withDefaults(defineProps<{ bars: readonly (VolumeBar & { time: string })[]; top: number; scoring?: boolean }>(), { scoring: true })
const selectedTime = ref<string | null>(null)
const index = computed(() => props.bars.findIndex(bar => bar.time === selectedTime.value))
const bar = computed(() => props.bars[index.value])
const scores = computed(() => props.scoring === false ? [] : volumeScores(props.bars, index.value))
const latestYellow = computed(() => props.scoring === false ? undefined : props.bars.filter((_, i) => volumeScores(props.bars, i).some(score => score.total >= 4)).at(-1))
watch(() => props.bars, () => { selectedTime.value = null })
function showAt(time: string) { selectedTime.value = time }
defineExpose({ showAt })
</script>
<template>
  <div class="volume-explanation" :style="{ top: `${top}px` }">
    <span>成交量 <button type="button" @click="selectedTime = latestYellow?.time ?? bars.at(-1)?.time ?? null">黄色柱说明</button></span>
    <section v-if="selectedTime" role="dialog" aria-label="成交量展示评分">
      <header><strong>成交量展示评分</strong><button type="button" aria-label="关闭成交量评分" @click="selectedTime = null">×</button></header>
      <p v-if="bar">{{ bar.time }} · {{ bar.physicalContract ?? '物理合约待确认' }} · 成交量 {{ bar.volume ?? '缺失' }}</p>
      <article v-for="score in scores" :key="score.side">
        <strong>{{ score.side === 'lower' ? '下沿' : '上沿' }} {{ score.reference.toFixed(2) }} · {{ score.total }}/6 分</strong>
        <p>量比 {{ score.volumeRatio.toFixed(2) }} 倍（{{ score.volumeScore }}分） · 实体 {{ (score.bodyRatio * 100).toFixed(2) }}%（{{ score.bodyScore }}分） · 穿透 {{ (score.penetrationRatio * 100).toFixed(2) }}%（{{ score.penetrationScore }}分）</p>
      </article>
      <p v-if="!scores.length">预览、身份或有效数据不足，当前柱不参与黄色评分。</p>
      <details><summary>查看计算依据</summary><p>近10根同合约、同计算段均量包含本根。量比≥1.5得2分、≥1得1分；实体占比严格&gt;60%得2分、&gt;30%得1分；距通道沿比例严格&gt;3%得2分、&gt;1%得1分，其余0分。上沿或下沿总分≥4标黄。</p></details>
      <small>归一统一展示规则 · 独立于策略动作，与旧牛哇动作限定着色不同。仅作展示，非策略信号或成交确认。</small>
    </section>
  </div>
</template>
<style scoped>
.volume-explanation{position:absolute;left:12px;right:12px;z-index:8;font-size:11px;color:var(--gy-text-muted);pointer-events:none}.volume-explanation>span{background:var(--gy-bg-panel);padding-right:4px}.volume-explanation button{pointer-events:auto;min-height:24px;color:#b77900}.volume-explanation section{position:absolute;right:64px;bottom:24px;width:min(360px,calc(100% - 76px));max-height:340px;overflow:auto;pointer-events:auto;padding:12px;border:1px solid #efce68;border-radius:8px;background:var(--gy-bg-panel);box-shadow:0 4px 16px #00000014;font-size:12px}.volume-explanation header{display:flex;justify-content:space-between;align-items:center}.volume-explanation p,.volume-explanation small{line-height:1.7;margin:6px 0}.volume-explanation article{border-top:1px solid var(--gy-border);padding-top:8px}
</style>
