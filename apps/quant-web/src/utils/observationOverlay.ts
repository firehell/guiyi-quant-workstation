/** Freeze chart-adjacent DOM labels/layers at the same instant as the native canvas.
 * The browser paints the frozen SVG/XHTML snapshot, including selected callouts and local canvases.
 */
const SVG = 'http://www.w3.org/2000/svg'
const allowedTags = new Set(('div span b strong i em small p button aside header section details summary label code img canvas '
  + 'svg g line rect polyline polygon circle path text tspan title').split(' '))
const svgGeometry = new Set('viewBox preserveAspectRatio x y cx cy r rx ry x1 x2 y1 y2 width height points d transform'.split(' '))
const supportedStyle = /^(?:align-|background(?:-|$)|border(?:-|$)|bottom$|box-|clip(?:-|$)|color$|column-gap$|display$|fill(?:-|$)|filter$|flex(?:-|$)|font(?:-|$)|gap$|grid(?:-|$)|height$|justify-|left$|letter-spacing$|line-height$|margin(?:-|$)|max-|min-|opacity$|outline(?:-|$)|overflow(?:-|$)|padding(?:-|$)|position$|right$|rotate$|row-gap$|scale$|stroke(?:-|$)|text(?:-|$)|top$|transform(?:-|$)|translate$|vertical-align$|visibility$|white-space$|width$|word(?:-|$)|writing-mode$|z-index$)/

function styleCopy(element: HTMLElement | SVGElement, style: CSSStyleDeclaration) {
  for (const name of Array.from(style)) {
    if (!supportedStyle.test(name)) continue
    const value = style.getPropertyValue(name)
    if (/url\s*\(/i.test(value)) throw new Error('图表有外部样式资源，无法冻结完整原图。')
    element.style.setProperty(name, value)
  }
  element.style.animation = 'none'
}

export function freezeChartOverlays(surface: HTMLElement): string | null {
  const container = surface.parentElement
  const parent = container?.parentElement
  if (!container || !parent) return null
  const frame = surface.getBoundingClientRect()
  const svg = document.createElementNS(SVG, 'svg')
  svg.setAttribute('width', String(frame.width))
  svg.setAttribute('height', String(frame.height))
  const foreign = document.createElementNS(SVG, 'foreignObject')
  foreign.setAttribute('width', '100%')
  foreign.setAttribute('height', '100%')
  const plane = document.createElement('div')
  Object.assign(plane.style, { width: frame.width + 'px', height: frame.height + 'px', position: 'relative', overflow: 'hidden' })
  let count = 0
  function freeze(node: Element): HTMLElement | SVGElement | null {
    const style = getComputedStyle(node)
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return null
    const tag = node.localName
    if (++count > 1500 || !allowedTags.has(tag)) throw new Error('可见图表标签无法完整保存。')
    const clone = tag === 'canvas' ? document.createElement('img')
      : node.namespaceURI === SVG ? document.createElementNS(SVG, tag) : document.createElement(tag)
    styleCopy(clone, style)
    if (node instanceof HTMLCanvasElement && clone instanceof HTMLImageElement) {
      clone.src = node.toDataURL('image/png')
    } else if (node instanceof HTMLImageElement && clone instanceof HTMLImageElement) {
      if (!node.src.startsWith('data:image/png;base64,')) throw new Error('图表含外部图片，无法冻结完整原图。')
      clone.src = node.src
    } else {
      if (node instanceof SVGElement) {
        for (const attr of node.attributes) if (svgGeometry.has(attr.name)) clone.setAttribute(attr.name, attr.value)
      }
      // The closed details body is not painted by the browser.
      if (node instanceof HTMLDetailsElement && clone instanceof HTMLDetailsElement) clone.open = node.open
      for (const child of node.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) clone.append(document.createTextNode(child.textContent ?? ''))
        else if (child instanceof Element) {
          const frozen = freeze(child)
          if (frozen) clone.append(frozen)
        }
      }
    }
    return clone
  }
  // Only painted siblings in the chart crop are included. Ordinary navigation stays outside the image.
  for (const sibling of parent.children) {
    if (sibling === container) continue
    const box = sibling.getBoundingClientRect()
    if (!box.width || !box.height || box.right <= frame.left || box.left >= frame.right ||
      box.bottom <= frame.top || box.top >= frame.bottom) continue
    const clone = freeze(sibling)
    if (!clone) continue
    Object.assign(clone.style, { position: 'absolute', margin: '0', left: (box.left - frame.left) + 'px',
      top: (box.top - frame.top) + 'px', right: 'auto', bottom: 'auto', width: box.width + 'px',
      height: box.height + 'px', boxSizing: 'border-box', transform: 'none', translate: 'none' })
    plane.append(clone)
  }
  if (!plane.childElementCount) return null
  foreign.append(plane)
  svg.append(foreign)
  return new XMLSerializer().serializeToString(svg)
}

export async function paintFrozenOverlays(canvas: HTMLCanvasElement, serialized: string | null) {
  if (!serialized) return
  const layer = new Image()
  // Data URL keeps same-origin canvas readback in Chromium; blob SVGs with foreignObject taint it.
  layer.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(serialized)
  await layer.decode()
  const context = canvas.getContext('2d')
  if (!context) throw new Error('无法合成图表标签。')
  context.drawImage(layer, 0, 0, canvas.width, canvas.height)
}
