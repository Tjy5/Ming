import { describe, expect, it } from 'vitest'
import { joinRegionsToMap, MAP_FEATURES, featureForLegacyName, normalizeRegionName } from '../data/map/geography'
import type { Region } from '../types/game'

const makeRegion = (name: string): Region => ({
  name, stability: 50, garrison: 1, control: '朝廷', threat: 'none',
  tax_contribution: 'medium', civil_morale: 50, rebellion_risk: 20,
  tax_rate: 0.5, tax_collected: 1, disaster_level: 0,
})

describe('map geography adapter', () => {
  it('maps all eight canonical regions to stable feature ids', () => {
    const result = joinRegionsToMap(MAP_FEATURES.map((feature) => makeRegion(feature.displayName)))
    expect(result.features.every((feature) => feature.state === 'mapped')).toBe(true)
    expect(result.unmapped).toHaveLength(0)
    expect(result.duplicates).toHaveLength(0)
  })

  it('normalizes whitespace and supports legacy aliases', () => {
    expect(normalizeRegionName('  应 天  ')).toBe('应天')
    expect(featureForLegacyName('集庆')?.mapRegionId).toBe('yingtian')
  })

  it('reports unknown and duplicate payload entries without guessing geometry', () => {
    const result = joinRegionsToMap([makeRegion('应天'), makeRegion('集庆'), makeRegion('不存在')])
    expect(result.duplicates.map((region) => region.name)).toEqual(['集庆'])
    expect(result.unmapped.map((region) => region.name)).toEqual(['不存在'])
    expect(result.features.find((feature) => feature.feature.mapRegionId === 'yingtian')?.region?.name).toBe('应天')
  })
})
