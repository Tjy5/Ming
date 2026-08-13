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
})
