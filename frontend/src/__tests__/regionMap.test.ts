import { describe, it, expect } from 'vitest'
import { getTooltipText, getTaxCollectedRanks } from '../components/RegionMap'
import type { ViewMode } from '../components/RegionMap'
import type { Region } from '../types/game'

function makeRegion(overrides: Partial<Region> = {}): Region {
  return {
    name: '京畿', stability: 50, garrison: 10000,
    control: '朝廷', threat: 'none', tax_contribution: 'medium',
    civil_morale: 50, rebellion_risk: 20, tax_rate: 0.5,
    tax_collected: 30, disaster_level: 10, ...overrides,
  }
}

const ALL_VIEWS: ViewMode[] = ['standard', 'disaster', 'morale', 'rebellion', 'tax_rate', 'tax_collected']

describe('getTooltipText — field count <= 3', () => {
  ALL_VIEWS.forEach(view => {
    it(`${view} view has at most 3 fields`, () => {
      const r = makeRegion()
      const text = getTooltipText(view, r)
      const fields = text.split('|')
      expect(fields.length).toBeLessThanOrEqual(3)
    })
  })

  it('each field is non-empty after trim', () => {
    const r = makeRegion()
    ALL_VIEWS.forEach(view => {
      const text = getTooltipText(view, r)
      text.split('|').forEach(f => {
        expect(f.trim().length).toBeGreaterThan(0)
      })
    })
  })
})

describe('getTaxCollectedRanks — sort stability', () => {
  it('deterministic order for different tax_collected values', () => {
    const regions = [
      makeRegion({ name: 'a', tax_collected: 100, stability: 50 }),
      makeRegion({ name: 'b', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'c', tax_collected: 200, stability: 50 }),
      makeRegion({ name: 'd', tax_collected: 30, stability: 50 }),
      makeRegion({ name: 'e', tax_collected: 80, stability: 50 }),
      makeRegion({ name: 'f', tax_collected: 10, stability: 50 }),
      makeRegion({ name: 'g', tax_collected: 5, stability: 50 }),
      makeRegion({ name: 'h', tax_collected: 1, stability: 50 }),
    ]
    const ranks = getTaxCollectedRanks(regions)
    // top 2 by tax_collected: c(200), a(100)
    expect(ranks.get('c')).toBe('high')
    expect(ranks.get('a')).toBe('high')
    // bottom 2: g(5), h(1)
    expect(ranks.get('g')).toBe('low')
    expect(ranks.get('h')).toBe('low')
  })

  it('tied tax_collected breaks by stability desc', () => {
    const regions = [
      makeRegion({ name: 'a', tax_collected: 50, stability: 30 }),
      makeRegion({ name: 'b', tax_collected: 50, stability: 80 }),
      makeRegion({ name: 'c', tax_collected: 50, stability: 60 }),
      makeRegion({ name: 'd', tax_collected: 50, stability: 90 }),
      makeRegion({ name: 'e', tax_collected: 50, stability: 20 }),
      makeRegion({ name: 'f', tax_collected: 50, stability: 10 }),
      makeRegion({ name: 'g', tax_collected: 50, stability: 5 }),
      makeRegion({ name: 'h', tax_collected: 50, stability: 1 }),
    ]
    const ranks = getTaxCollectedRanks(regions)
    // all tied on tax_collected=50, sorted by stability desc: d(90), b(80) → high
    expect(ranks.get('d')).toBe('high')
    expect(ranks.get('b')).toBe('high')
    // g(5), h(1) → low
    expect(ranks.get('g')).toBe('low')
    expect(ranks.get('h')).toBe('low')
  })

  it('tied tax_collected and stability breaks by name asc', () => {
    const regions = [
      makeRegion({ name: 'h', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'g', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'f', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'e', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'd', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'c', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'b', tax_collected: 50, stability: 50 }),
      makeRegion({ name: 'a', tax_collected: 50, stability: 50 }),
    ]
    const r1 = getTaxCollectedRanks(regions)
    const r2 = getTaxCollectedRanks([...regions].reverse())
    // name asc: a,b → high; g,h → low
    expect(r1.get('a')).toBe('high')
    expect(r1.get('b')).toBe('high')
    expect(r1.get('g')).toBe('low')
    expect(r1.get('h')).toBe('low')
    expect(r2.get('a')).toBe('high')
    expect(r2.get('b')).toBe('high')
    expect(r2.get('g')).toBe('low')
    expect(r2.get('h')).toBe('low')
  })

  it('all zero tax_collected → all low', () => {
    const regions = [
      makeRegion({ name: 'a', tax_collected: 0 }),
      makeRegion({ name: 'b', tax_collected: 0 }),
      makeRegion({ name: 'c', tax_collected: 0 }),
    ]
    const ranks = getTaxCollectedRanks(regions)
    regions.forEach(r => {
      expect(ranks.get(r.name)).toBe('low')
    })
  })

  it('consistency across multiple invocations', () => {
    const regions = [
      makeRegion({ name: 'a', tax_collected: 100, stability: 50 }),
      makeRegion({ name: 'b', tax_collected: 100, stability: 50 }),
      makeRegion({ name: 'c', tax_collected: 50, stability: 80 }),
      makeRegion({ name: 'd', tax_collected: 50, stability: 80 }),
      makeRegion({ name: 'e', tax_collected: 10, stability: 30 }),
      makeRegion({ name: 'f', tax_collected: 10, stability: 30 }),
      makeRegion({ name: 'g', tax_collected: 10, stability: 20 }),
      makeRegion({ name: 'h', tax_collected: 10, stability: 10 }),
    ]
    const r1 = getTaxCollectedRanks(regions)
    const r2 = getTaxCollectedRanks(regions)
    regions.forEach(r => {
      expect(r1.get(r.name)).toBe(r2.get(r.name))
    })
  })
})
