// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/react'
import RegionMap from '../components/RegionMap'
import type { Region } from '../types/game'

afterEach(cleanup)

function makeRegion(name: string): Region {
  return {
    name, stability: 50, garrison: 10000,
    control: '朝廷', threat: 'none', tax_contribution: 'medium',
    civil_morale: 50, rebellion_risk: 20, tax_rate: 0.5,
    tax_collected: 30, disaster_level: 10,
  }
}

describe('RegionMap onRegionClick', () => {
  it('renders a decorative modern basemap below the strategic controls and shows the accuracy note', () => {
    const { container } = render(<RegionMap regions={[makeRegion('应天')]} />)
    expect(container.querySelectorAll('.china-reference-basemap path')).toHaveLength(33)
    expect(container.querySelector('.china-reference-basemap button')).toBeNull()
    expect(container.querySelector('.china-reference-basemap')?.getAttribute('aria-hidden')).toBe('true')
    expect(screen.getByText(/现代地理参考底图/)).toBeTruthy()
    expect(screen.getByText(/不等同于现代省界或精确的 1368 行政疆界/)).toBeTruthy()
  })

  it('keeps local atmosphere assets decorative, pointer-inert, and below authoritative map layers', () => {
    const { container } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const svg = container.querySelector('.geographic-map svg')
    const atmosphere = svg?.querySelector('.map-atmosphere')
    const basemap = svg?.querySelector('.china-reference-basemap')
    const strategicOverlay = svg?.querySelector('.yuanming-strategic-overlay')
    const images = atmosphere?.querySelectorAll('image')

    expect(atmosphere?.getAttribute('aria-hidden')).toBe('true')
    expect(atmosphere?.getAttribute('pointer-events')).toBe('none')
    expect(images).toHaveLength(2)
    expect(Array.from(images ?? []).map((image) => image.getAttribute('href'))).toEqual([
      '/map/atmosphere/v1/paper-water-wash-v1.webp',
      '/map/atmosphere/v1/terrain-drybrush-v1.webp',
    ])
    expect(svg && atmosphere && basemap && (atmosphere.compareDocumentPosition(basemap) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg && basemap && strategicOverlay && (basemap.compareDocumentPosition(strategicOverlay) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy()
    expect(svg?.querySelector('.map-water')).toBeTruthy()
  })

  it('calls onRegionClick with the clicked region', () => {
    const onClick = vi.fn()
    const regions = [makeRegion('应天'), makeRegion('集庆')]
    const { getByRole } = render(<RegionMap regions={regions} onRegionClick={onClick} />)
    const block = getByRole('button', { name: /应天，控制/ })
    fireEvent.click(block)
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ name: '应天' }))
  })

  it('does not call onRegionClick when prop omitted (backward compat)', () => {
    const regions = [makeRegion('应天')]
    // 不传 onRegionClick 时渲染不抛错、点击安全
    const { container } = render(<RegionMap regions={regions} />)
    const block = container.querySelector('.region-block')
    expect(block).toBeTruthy()
    if (block) fireEvent.click(block)
    expect(true).toBe(true)
  })

  it('supports keyboard activation on a mapped strategic region', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<RegionMap regions={[makeRegion('应天')]} onRegionClick={onClick} />)
    fireEvent.keyDown(getByRole('button', { name: /应天，控制/ }), { key: 'Enter' })
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ name: '应天' }))
  })

  it('supports Space activation on a mapped strategic region', () => {
    const onClick = vi.fn()
    const { getByRole } = render(<RegionMap regions={[makeRegion('应天')]} onRegionClick={onClick} />)
    fireEvent.keyDown(getByRole('button', { name: /应天，控制/ }), { key: ' ' })
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ name: '应天' }))
  })

  it('renders distinct mode context, legends, and region summaries for all six views', () => {
    const region = {
      ...makeRegion('应天'),
      stability: 47,
      disaster_level: 18,
      civil_morale: 63,
      rebellion_risk: 29,
      tax_rate: 0.74,
      tax_collected: 1234,
    }
    const { container, getByRole } = render(<RegionMap regions={[region]} />)
    const expected = [
      ['标准', '治势总览', '稳定 47'],
      ['灾情', '灾情态势', '灾情 18'],
      ['民心', '民心向背', '民心 63'],
      ['动乱', '动乱风险', '风险 29'],
      ['税率', '税赋完成', '完成 74%'],
      ['赋税', '实征赋税', '实征 1,234'],
    ]

    for (const [buttonLabel, title, value] of expected) {
      fireEvent.click(getByRole('button', { name: buttonLabel }))
      expect(getByRole('heading', { name: title })).toBeTruthy()
      expect(container.querySelectorAll('.map-legend [data-legend-level]')).toHaveLength(3)
      expect(container.querySelector('[data-map-region-id="yingtian"] .region-mode-value')?.textContent).toBe(value)
    }
  })

  it('exposes selected, threat, control, missing, unmapped, and duplicate states explicitly', () => {
    const threatened = { ...makeRegion('应天'), control: '沦陷' as const, threat: '元军' as const }
    const duplicate = makeRegion('集庆')
    const unmapped = makeRegion('不存在')
    const { container } = render(
      <RegionMap regions={[threatened, duplicate, unmapped]} highlightRegion="应天" />,
    )

    const selected = container.querySelector('[data-map-region-id="yingtian"]')
    expect(selected?.classList.contains('selected')).toBe(true)
    expect(selected?.classList.contains('has-threat')).toBe(true)
    expect(selected?.getAttribute('data-control')).toBe('沦陷')
    expect(selected?.getAttribute('data-threat')).toBe('元军')
    expect(container.querySelectorAll('[data-state="missing"]')).toHaveLength(7)
    expect(container.querySelector('[data-warning-kind="unmapped"]')?.textContent).toContain('不存在')
    expect(container.querySelector('[data-warning-kind="duplicate"]')?.textContent).toContain('集庆')
  })

  it('mirrors pointer and focus hover state onto the strategic path group', () => {
    const { container, getByRole } = render(<RegionMap regions={[makeRegion('应天')]} />)
    const button = getByRole('button', { name: /应天，控制：朝廷，治势总览/ })
    const feature = container.querySelector('[data-map-region-id="yingtian"]')

    fireEvent.mouseEnter(button)
    expect(feature?.classList.contains('hovered')).toBe(true)
    fireEvent.mouseLeave(button)
    expect(feature?.classList.contains('hovered')).toBe(false)
    fireEvent.focus(button)
    expect(feature?.classList.contains('hovered')).toBe(true)
    fireEvent.blur(button)
    expect(feature?.classList.contains('hovered')).toBe(false)
  })
})
