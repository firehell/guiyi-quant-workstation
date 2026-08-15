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

  function tokenValue(name: string): string {
    const match = css.match(new RegExp(`${name}:\\s*(.+);`))
    assert.ok(match, `expected ${name} to be defined in tokens.css`)
    return match[1].trim()
  }

  it('declares a fixed light color scheme', () => {
    assert.match(css, /color-scheme:\s*light/)
    assert.doesNotMatch(css, /color-scheme:\s*dark/)
  })

  it('uses the approved light surface and text palette', () => {
    assert.match(css, /--gy-bg-app:\s*#f4f7fb/i)
    assert.match(css, /--gy-bg-canvas:\s*#fff(?:fff)?/i)
    assert.match(css, /--gy-bg-panel:\s*#fff(?:fff)?/i)
    assert.match(css, /--gy-text-primary:\s*#0f1f38/i)
    assert.match(css, /--gy-border:\s*#dbe3ee/i)
  })

  it('keeps China futures direction colors: red up, green down', () => {
    assert.match(css, /--gy-up:\s*var\(--gy-red-600\)/)
    assert.match(css, /--gy-down:\s*var\(--gy-green-600\)/)
    assert.match(css, /--gy-red-600:\s*#dc2626/i)
    assert.match(css, /--gy-green-600:\s*#16a34a/i)
  })

  it('keeps accent and warning non-directional', () => {
    assert.match(css, /--gy-accent:\s*#1d4ed8/i)
    assert.match(css, /--gy-status-warning:\s*var\(--gy-orange-500\)/)
    assert.notEqual(tokenValue('--gy-accent'), tokenValue('--gy-up'))
  })

  it('defines the deep navy brand shell with readable shell text', () => {
    assert.match(css, /--gy-shell-bg:\s*#0b1d3a/i)
    assert.match(css, /--gy-shell-text:\s*#8ca8cf/i)
    assert.match(css, /--gy-shell-text-active:\s*#bfdbfe/i)
    assert.match(css, /--gy-shell-accent:\s*#60a5fa/i)
    assert.ok(
      contrastRatio(tokenValue('--gy-shell-text'), tokenValue('--gy-shell-bg')) >= 4.5,
      'shell text must meet WCAG AA on the navy shell',
    )
    assert.ok(
      contrastRatio(tokenValue('--gy-shell-text-active'), tokenValue('--gy-shell-bg')) >= 4.5,
      'active shell text must meet WCAG AA on the navy shell',
    )
    assert.ok(
      contrastRatio('#FFFFFF', tokenValue('--gy-accent')) >= 4.5,
      'white text on the brand accent must meet WCAG AA',
    )
  })
})
