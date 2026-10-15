import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, h } from 'vue'
import { compileCurveComponent } from './helpers/compileCurveComponent.ts'

interface TestNode { type: string; props: Record<string, unknown>; parent: TestNode | null; children: TestNode[]; text: string; style: Record<string,unknown> }
function element(type: string): TestNode { return { type, props: {}, parent: null, children: [], text: '', style:{} } }
function findNode(node: TestNode, match: (candidate: TestNode) => boolean): TestNode | undefined {
  if (match(node)) return node
  for (const child of node.children) { const found = findNode(child, match); if (found) return found }
  return undefined
}
function findNodes(node: TestNode, match: (candidate: TestNode) => boolean): TestNode[] {
  return [match(node) ? node : null, ...node.children.flatMap((child) => findNodes(child, match))].filter((item): item is TestNode => item !== null)
}
function nodeText(node: TestNode): string { return [node.text, ...node.children.map(nodeText)].join(' ') }
function nodeOperations() {
  return {
    patchProp(node: TestNode, key: string, _previous: unknown, next: unknown) { node.props[key] = next },
    insert(child: TestNode, parent: TestNode, anchor: TestNode | null = null) { if (child.parent) child.parent.children = child.parent.children.filter(node => node !== child); child.parent = parent; const index = anchor === null ? -1 : parent.children.indexOf(anchor); if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
    remove(child: TestNode) { if (child.parent === null) return; child.parent.children = child.parent.children.filter((item) => item !== child); child.parent = null },
    createElement: (type: string) => element(type), createText(text: string) { const node = element('#text'); node.text = text; return node }, createComment(text: string) { const node = element('#comment'); node.text = text; return node },
    setText(node: TestNode, text: string) { node.text = text }, setElementText(node: TestNode, text: string) { node.text = text; node.children = [] },
    parentNode(node: TestNode) { return node.parent }, nextSibling(node: TestNode) { if (node.parent === null) return null; const index = node.parent.children.indexOf(node); return node.parent.children[index + 1] ?? null }, querySelector() { return null }, setScopeId() {}, insertStaticContent() { return [element('#static'), element('#static')] as const },
  }
}

test('every detail view uses the same frequency labels and exact supported choices in navigation', async () => {
  const Nav = (await import(await compileCurveComponent(new URL('../src/components/market/detail/MarketDetailViewNav.vue', import.meta.url)))).default
  for (const view of ['newow', 'subing', 'free', 'htdy'] as const) {
    const root = element('root'), selected: any[] = []
    const identity = { view, symbol:'jm', strategy:'trend', seriesKind:'actual_dominant', frequency:'1d' }
    const restore = { newow:{ strategy:'trend', frequency:'1d' }, free:{ seriesKind:'actual_dominant',frequency:'15m'},htdy:{ seriesKind:'actual_dominant',frequency:'15m'} }
    const app = createRenderer(nodeOperations()).createApp({ render: () => h(Nav, {identity,restore,seriesKinds:['actual_dominant','continuous'],newowFrequencies:['60m','1d','1w'],onSelect:(value:any)=>selected.push(value)}) })
    app.mount(root)
    const controls = findNode(root, n=>n.props['aria-label']==='周期')!
    assert.ok(controls, view)
    const labels = findNodes(controls,n=>n.type==='button').map(nodeText)
    assert.ok(labels.includes('日线')); assert.ok(labels.includes('周线'))
    assert.equal(labels.includes('日K'),false)
    if (view==='newow') assert.deepEqual(labels,['60分钟','日线','周线'])
    const week = findNode(controls,n=>n.type==='button'&&nodeText(n)==='周线')!
    ;(week.props.onClick as Function)()
    assert.equal(selected.at(-1).frequency,'1w')
    assert.equal(selected.at(-1).symbol,'jm')
    app.unmount()
  }
})
