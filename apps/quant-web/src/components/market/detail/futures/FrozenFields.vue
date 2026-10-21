<script setup lang="ts">
import { frozenText } from '@/utils/newowFuturesSnapshot'
import type { FrozenRecord } from '@/types/newowFutures'
defineProps<{ value: FrozenRecord }>()
const labels:Record<string,string>={initial_cash:'初始资金',account_return_pct:'账户净收益率（%）',reference_return_pct:'参考收益率（%）',max_drawdown_pct:'最大回撤（%）',total_fees:'总费用',closed_trades:'已完成交易数',initial_equity:'初始权益',final_equity:'期末权益',net_pnl:'净盈亏',total_return:'净收益率',return_pct:'收益率（%）',max_drawdown:'最大回撤',trade_count:'交易数',status:'状态',reason:'原因',reason_code:'原因代码',side:'方向',holding_frequency:'持有周期',entry_reference_price:'参考入场价',stop_reference_price:'参考保护价',target_reference_price:'参考目标价',cash:'现金',equity:'权益',margin:'保证金',realized_pnl:'已实现盈亏',unrealized_pnl:'浮动盈亏',fees:'费用',rejections:'拒绝原因',funding_rejections:'资金拒绝',executable:'可执行',auto_order:'自动下单'}
</script>
<template><dl class="frozen-fields"><div v-for="(item,key) in value" :key="key"><dt>{{ labels[key] ?? key }}</dt><dd>{{ frozenText(item) }}</dd></div></dl></template>
<style scoped>.frozen-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px;margin:8px 0}.frozen-fields div{border-bottom:1px solid var(--gy-border-subtle);padding:8px;min-width:0}.frozen-fields dt{font-size:12px;color:var(--gy-text-muted)}.frozen-fields dd{margin:4px 0 0;overflow-wrap:anywhere;font-size:13px}</style>
