// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/react'
import RegionMap from '../components/RegionMap'
import type { Region } from '../types/game'

afterEach(cleanup)

function makeMockRegions(overrides: Partial<Region>[] = []): Region[] {
  const baseRegions: Region[] = [
    {
      name: '两淮',
      garrison: 30000,
      stability: 80,
      disaster_level: 20,
      control: '朝廷',
      threat: 'none',
      rebellion_risk: 10,
      civil_morale: 75,
      tax_collected: 8000,
      tax_contribution: 'medium',
      tax_rate: 0.5,
    },
    {
      name: '应天',
      garrison: 50000,
      stability: 90,
      disaster_level: 10,
      control: '朝廷',
      threat: 'none',
      rebellion_risk: 5,
      civil_morale: 80,
      tax_collected: 12000,
      tax_contribution: 'high',
      tax_rate: 0.5,
    },
  ]

  if (overrides.length > 0) {
    return baseRegions.map((r, i) => (overrides[i] ? { ...r, ...overrides[i] } : r))
  }
  return baseRegions
}

describe('immersion HUD map tooltip and crisis detection', () => {
  it('detects crisis strictly at > 50 threshold (50 does not trigger, 51 triggers)', () => {
    // 1. Exactly 50 aggregated rebellion risk -> no crisis
    const regionsAt50 = makeMockRegions([
      { name: '两淮', rebellion_risk: 50, disaster_level: 50 },
      { name: '应天', rebellion_risk: 50, disaster_level: 50 },
    ])
    const { unmount } = render(<RegionMap regions={regionsAt50} />)

    const henanDivision50 = screen.getByRole('button', { name: /河南江北行省/ })
    expect(henanDivision50.getAttribute('data-crisis')).toBeNull()
    expect(henanDivision50.classList.contains('has-crisis')).toBe(false)
    unmount()

    // 2. 51 aggregated rebellion risk -> triggers crisis
    const regionsAt51 = makeMockRegions([
      { name: '两淮', rebellion_risk: 51, disaster_level: 20 },
      { name: '应天', rebellion_risk: 51, disaster_level: 20 },
    ])
    render(<RegionMap regions={regionsAt51} />)

    const henanDivision51 = screen.getByRole('button', { name: /河南江北行省/ })
    expect(henanDivision51.getAttribute('data-crisis')).toBe('true')
    expect(henanDivision51.classList.contains('has-crisis')).toBe(true)
    expect(henanDivision51.getAttribute('aria-label')).toContain('⚠️危机警示')
  })

  it('renders aggregated tooltip with canonical main threat and metrics on hover', () => {
    const regions = makeMockRegions([
      { name: '两淮', threat: '元军', disaster_level: 70, rebellion_risk: 30 },
      { name: '应天', threat: '汉军', disaster_level: 70, rebellion_risk: 30 },
    ])
    render(<RegionMap regions={regions} />)

    const henanDivision = screen.getByRole('button', { name: /河南江北行省/ })
    fireEvent.mouseEnter(henanDivision, { clientX: 200, clientY: 200 })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toBeTruthy()
    expect(tooltip.textContent).toContain('河南江北行省')
    expect(tooltip.textContent).toContain('元军')
    expect(tooltip.textContent).toContain('⚠️ 危机')
    expect(tooltip.textContent).toContain('等级70')
  })
})
