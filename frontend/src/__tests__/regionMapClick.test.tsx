// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import RegionMap from '../components/RegionMap'
import type { Region } from '../types/game'

function makeRegion(name: string): Region {
  return {
    name, stability: 50, garrison: 10000,
    control: '朝廷', threat: 'none', tax_contribution: 'medium',
    civil_morale: 50, rebellion_risk: 20, tax_rate: 0.5,
    tax_collected: 30, disaster_level: 10,
  }
}

describe('RegionMap onRegionClick', () => {
  it('calls onRegionClick with the clicked region', () => {
    const onClick = vi.fn()
    const regions = [makeRegion('应天'), makeRegion('集庆')]
    render(<RegionMap regions={regions} onRegionClick={onClick} />)
    const block = screen.getByText('应天') // 省份块含 name
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
})
