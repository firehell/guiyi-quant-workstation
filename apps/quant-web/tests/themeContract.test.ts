import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import { themeOverrides } from '../src/styles/theme.ts'

type ThemeRecord = Record<string, any>

function channelToLinear(channel: number) {
  const normalized = channel / 255
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4
}

function luminance(color: string) {
  const match = /^#([0-9a-f]{6})$/i.exec(color)
  assert.ok(match, `expected an opaque six-digit hex color, received ${color}`)
  const value = match[1]
  const channels = [0, 2, 4].map((offset) =>
    channelToLinear(Number.parseInt(value.slice(offset, offset + 2), 16)),
  )
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrastRatio(foreground: string, background: string) {
  const light = Math.max(luminance(foreground), luminance(background))
  const dark = Math.min(luminance(foreground), luminance(background))
  return (light + 0.05) / (dark + 0.05)
}

describe('theme control contract', () => {
  it('keeps RadioButton active text readable on its selected surface', () => {
    const radio = (themeOverrides as ThemeRecord).Radio
    assert.ok(radio, 'Radio overrides must define the selected control contract')
    assert.notEqual(radio.buttonColorActive, radio.buttonColor)
    assert.notEqual(radio.buttonTextColorActive, radio.textColorDisabled)
    assert.ok(
      contrastRatio(radio.buttonTextColorActive, radio.buttonColorActive) >= 4.5,
      'RadioButton active text must meet WCAG AA contrast',
    )
  })

  it('keeps primary buttons readable in active hover and disabled states', () => {
    const button = (themeOverrides as ThemeRecord).Button
    assert.ok(button.colorPrimary)
    assert.ok(contrastRatio(button.textColorPrimary, button.colorPrimary) >= 4.5)
    assert.ok(contrastRatio(button.textColorHoverPrimary, button.colorHoverPrimary) >= 4.5)
    assert.notEqual(button.colorDisabledPrimary, button.colorPrimary)
    assert.notEqual(button.textColorDisabledPrimary, button.textColorPrimary)
  })

  it('uses one explicit selected option contract for Select peers', () => {
    const select = (themeOverrides as ThemeRecord).Select
    const selection = select?.peers?.InternalSelection
    const menu = select?.peers?.InternalSelectMenu
    assert.ok(selection, 'Select must override its InternalSelection peer')
    assert.ok(menu, 'Select must override its InternalSelectMenu peer')
    assert.notEqual(selection.colorActive, selection.color)
    assert.ok(contrastRatio(menu.optionTextColorActive, menu.optionColorActive) >= 4.5)
    assert.notEqual(menu.optionTextColorActive, menu.optionTextColorDisabled)
  })

  it('keeps active tabs distinct from disabled tabs without direction colors', () => {
    const tabs = (themeOverrides as ThemeRecord).Tabs
    assert.notEqual(tabs.tabTextColorActiveLine, tabs.tabTextColorDisabledLine)
    assert.notEqual(tabs.tabTextColorActiveSegment, tabs.tabTextColorDisabledSegment)
    assert.match(tabs.tabTextColorActiveLine, /^#[0-9a-f]{6}$/i)
    assert.match(tabs.tabTextColorActiveSegment, /^#[0-9a-f]{6}$/i)
  })
})

describe('light theme token contract', () => {
  const css = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8')

  it('declares a fixed light color scheme', () => {
    assert.match(css, /color-scheme:\s*light/)
    assert.doesNotMatch(css, /color-scheme:\s*dark/)
  })

  it('uses the approved light surface and text palette', () => {
    assert.match(css, /--gy-bg-app:\s*var\(--gy-gray-50\)/)
    assert.match(css, /--gy-bg-canvas:\s*#fff(?:fff)?/i)
    assert.match(css, /--gy-bg-panel:\s*#fff(?:fff)?/i)
    assert.match(css, /--gy-text-primary:\s*var\(--gy-gray-900\)/)
    assert.match(css, /--gy-border:\s*var\(--gy-gray-200\)/)
  })

  it('keeps China futures direction colors: red up, green down', () => {
    assert.match(css, /--gy-up:\s*var\(--gy-red-600\)/)
    assert.match(css, /--gy-down:\s*var\(--gy-green-600\)/)
    assert.match(css, /--gy-red-600:\s*#dc2626/i)
    assert.match(css, /--gy-green-600:\s*#16a34a/i)
  })

  it('keeps accent and warning non-directional', () => {
    assert.match(css, /--gy-accent:\s*var\(--gy-blue-600\)/)
    assert.match(css, /--gy-status-warning:\s*var\(--gy-orange-500\)/)
    assert.notEqual(
      css.match(/--gy-accent:\s*(.+);/)?.[1],
      css.match(/--gy-up:\s*(.+);/)?.[1],
      'accent must not collide with direction colors',
    )
  })
})
