import { createApp, defineComponent, h, nextTick, reactive } from 'vue'
import MarketFactsDialog from '../../src/components/market/detail/MarketFactsDialog.vue'
import NewowDetailDialog from '../../src/components/market/detail/newow/NewowDetailDialog.vue'
import MarketDetailDrawer from '../../src/components/market/detail/MarketDetailDrawer.vue'
import '../../src/styles/tokens.css'
const state = reactive({ open: false, drawer: false, identity: 'A', mounted: true, drawerMounted: true, variant: undefined as 'niuwa-indicator' | 'ai-analysis' | undefined, kind: 'facts', closes: 0 })
createApp(defineComponent({ setup: () => () => h('main', { style: 'height:2000px' }, [
  h('button', { id: 'opener', onClick: () => { state.open = true } }, '打开弹层'),
  h('button', { id: 'drawer-opener', onClick: () => { state.drawer = true } }, '打开抽屉'),
  state.drawerMounted ? h(MarketDetailDrawer, { open: state.drawer, title: '历史', onClose: () => { state.drawer = false } }, {
    default: () => h('button', { id: 'nested-opener', onClick: () => { state.open = true } }, '嵌套弹层'),
  }) : null,
  state.mounted ? h(state.kind === 'facts' ? MarketFactsDialog : NewowDetailDialog, {
    variant: state.variant, open: state.open, identityKey: state.identity, title: '详情标题', onClose: () => { state.open = false; state.closes++ },
  }, { default: () => [h('p', '独立浏览器行为测试'), h('button', { id: 'last-action' }, '末尾操作')] }) : null,
]) })).mount('#app')
Object.assign(window, { overlayHarness: { state, async reopen() { state.open = false; await nextTick(); state.open = true; await nextTick() } } })
