import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatDecimalText,
  formatMarketDecimal,
  formatBeijingInstant,
  formatMarketPercent,
  formatMarketTime,
  marketChangeBasisLabel,
  marketQuoteBasisLabel,
  quoteAvailabilityLabel,
} from '../src/utils/marketDisplay.ts'

test('formats Decimal text without binary conversion or meaningless trailing zeroes', () => {
  assert.equal(formatMarketDecimal('718.000000000000000000'), '718')
  assert.equal(formatMarketDecimal('-0.070000'), '-0.07')
  assert.equal(formatMarketDecimal('12345678901234567890.1200'), '12345678901234567890.12')
  assert.equal(formatMarketDecimal('911.363333333333333333'), '911.3633')
  assert.equal(formatMarketDecimal('9.99995'), '10')
  assert.equal(formatMarketDecimal('4.4932e2'), '449.32')
  assert.equal(formatMarketDecimal(null), '—')
  assert.equal(formatMarketDecimal('not-a-decimal'), '—')
})

test('rounds display percentages by declared source unit without Number conversion', () => {
  assert.equal(formatMarketPercent('66.666666666666666666', 'percentage_points'), '66.67%')
  assert.equal(formatMarketPercent('0.123456', 'ratio'), '12.35%')
  assert.equal(formatMarketPercent('-0.00001', 'percentage_points'), '>-0.01%')
  assert.equal(formatMarketPercent('0.00001', 'percentage_points'), '<0.01%')
  assert.equal(formatMarketPercent('-0.0000', 'percentage_points'), '0%')
  assert.equal(formatMarketPercent('1.25e-1', 'ratio', true), '+12.5%')
  assert.equal(formatMarketPercent('not-a-decimal', 'ratio'), '—')
})

test('supports exact grouped and fixed precision display for huge Decimal lexemes', () => {
  assert.equal(formatDecimalText('12345678901234567890.995', { maximumFractionDigits: 2, minimumFractionDigits: 2, grouping: true }), '12,345,678,901,234,567,891.00')
  assert.equal(formatDecimalText('-0.004', { maximumFractionDigits: 2, minimumFractionDigits: 2, signed: true }), '0.00')
  assert.equal(formatDecimalText('1e-7', { maximumFractionDigits: 8 }), '0.0000001')
})

test('labels daily and current-period changes by their actual comparison basis', () => {
  assert.equal(marketQuoteBasisLabel('1d', true), '最近日线收盘')
  assert.equal(marketChangeBasisLabel('1d', true), '日涨跌（较前一日收盘）')
  assert.equal(marketQuoteBasisLabel('15m', false), '15分钟收盘')
  assert.equal(marketChangeBasisLabel('15m', false), '本周期涨跌（较前一根15分钟收盘）')
  assert.equal(marketChangeBasisLabel('1w', false), '本周期涨跌（较前一根周线收盘）')
})

test('formats market instants in Beijing time and keeps trading day separate', () => {
  assert.equal(formatBeijingInstant('2026-09-14T07:00:00Z'), '2026-09-14 15:00 北京时间')
  assert.equal(formatBeijingInstant('not-a-time'), '—')
  assert.equal(formatMarketTime('2026-12-31T16:15:00Z', '15m'), '2027-01-01 00:15 北京时间')
  assert.equal(formatMarketTime('2026-12-31T07:00:00Z', '1d', '2026-12-31'), '2026-12-31 · 交易日')
  assert.equal(formatMarketTime(null, '15m'), '—')
})

test('quote availability never endorses strategy or runtime readiness', () => {
  assert.equal(quoteAvailabilityLabel('fresh', false), '报价可用')
  assert.equal(quoteAvailabilityLabel('stale', false), '报价过时')
  assert.equal(quoteAvailabilityLabel('unavailable', false), '报价不可用')
  assert.equal(quoteAvailabilityLabel('fresh', true), '报价可用 · 盘后更新异常')
})
