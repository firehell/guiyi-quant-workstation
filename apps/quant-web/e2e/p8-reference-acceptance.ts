import { createApp, defineComponent, h } from 'vue'
import ReferenceTradePanel from '../src/components/market/detail/ReferenceTradePanel.vue'

const cases = [
  { id: 'subing-historical', title: '苏冰历史', strategy: 'subing-reference', product: 'RB', frequency: '60m', through: '2026-03-27', initialMode: 'historical_replay' },
  { id: 'subing-forward', title: '苏冰 Forward', strategy: 'subing-reference', product: 'RB', frequency: '60m', through: '2026-09-23', initialMode: 'forward_observation' },
  { id: 'newow-historical', title: '牛哇历史', strategy: 'newow-oscillation', product: 'rb', frequency: '1d', through: '2026-03-27', initialMode: 'historical_replay' },
  { id: 'newow-forward', title: '牛哇 Forward', strategy: 'newow-trend', product: 'rb', frequency: '1d', through: '2026-03-27', initialMode: 'forward_observation' },
  { id: 'htdy-forward', title: 'HTDY Forward', strategy: 'htdy', product: 'RB', frequency: '15m', through: '2026-09-23', initialMode: 'forward_observation' },
] as const

createApp(defineComponent({
  render() {
    return h('main', { style: 'max-width: 1100px; margin: 2rem auto; font-family: sans-serif' }, [
      h('h1', 'P8 隔离参考交易验收'),
      ...cases.map(item => h('section', { id: item.id, style: 'margin: 1.5rem 0' }, [
        h('h2', item.title),
        h(ReferenceTradePanel, item),
      ])),
    ])
  },
})).mount('#app')
