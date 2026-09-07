import assert from 'node:assert/strict'
import test from 'node:test'
import { marketHomePercent, marketHomePrice, marketHomeDirection, marketHomeRatio } from '../src/utils/marketHomePresentation.ts'

test('percent distinguishes zero, missing and signed ratios', () => {
  for (const [input, expected] of [[null, '—'], [0, '0.00%'], [-0, '0.00%'], [0.0246, '+2.46%'], [-0.0072, '-0.72%'], [NaN, '—'], [Infinity, '—'], [-Infinity, '—']] as const) {
    assert.equal(marketHomePercent(input), expected)
  }
})

test('prices preserve numeric precision and do not turn absent values into zero', () => {
  for (const [input, expected] of [[1186.5, '1,186.5'], [0, '0'], [1.23456789123456, '1.23456789123456'], [0.0000001, '0.0000001'], [null, '—'], [NaN, '—'], [Infinity, '—']] as const) {
    assert.equal(marketHomePrice(input), expected)
  }
})

test('direction is determined only by finite nonzero values', () => {
  for (const [input, expected] of [[0.1, 'up'], [-0.1, 'down'], [0, 'flat'], [null, 'flat'], [NaN, 'flat'], [Infinity, 'flat']] as const) {
    assert.equal(marketHomeDirection(input), expected)
  }
})


test('volume ratios use two decimals without exposing binary arithmetic noise', () => {
  for (const [input, expected] of [[1.2000000000000002, '1.20'], [1.236, '1.24'], [0, '0.00'], [null, '—'], [NaN, '—'], [Infinity, '—']] as const) {
    assert.equal(marketHomeRatio(input), expected)
  }
})
