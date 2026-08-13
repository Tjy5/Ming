import { describe, expect, it } from 'vitest'
import { CHINA_REFERENCE_BASEMAP } from '../data/map/chinaReferenceBasemap'
import { joinRegionsToMap, YUANMING_STRATEGIC_OVERLAY, featureForLegacyName, normalizeRegionName } from '../data/map/geography'
import type { Region } from '../types/game'

const makeRegion = (name: string): Region => ({
  name, stability: 50, garrison: 1, control: '朝廷', threat: 'none',
  tax_contribution: 'medium', civil_morale: 50, rebellion_risk: 20,
  tax_rate: 0.5, tax_collected: 1, disaster_level: 0,
})

describe('map geography adapter', () => {
  it('loads the attributed modern reference basemap without gameplay ids', () => {
    expect(CHINA_REFERENCE_BASEMAP).toMatchObject({
      viewBox: '0 0 774 569',
      sourcePackage: '@svg-maps/china',
      sourceVersion: '2.0.0',
      license: 'CC-BY-4.0',
    })
    expect(CHINA_REFERENCE_BASEMAP.features).toHaveLength(33)
    expect(new Set(CHINA_REFERENCE_BASEMAP.features.map((feature) => feature.id)).size).toBe(33)
    const gameplayIds = new Set(YUANMING_STRATEGIC_OVERLAY.map((feature) => feature.mapRegionId))
    expect(CHINA_REFERENCE_BASEMAP.features.every((feature) => !gameplayIds.has(feature.id))).toBe(true)
  })

  it('defines exactly eight explicit strategic overlay entries', () => {
    expect(YUANMING_STRATEGIC_OVERLAY.map((feature) => feature.mapRegionId)).toEqual([
      'dadu', 'lianghuai', 'wuchang', 'taiping', 'yingtian', 'zhenjiang', 'pingjiang', 'hangzhou',
    ])
    expect(YUANMING_STRATEGIC_OVERLAY.every((feature) => feature.path.length > 0)).toBe(true)
    expect(YUANMING_STRATEGIC_OVERLAY.every((feature) => Number.isFinite(feature.anchor.x) && Number.isFinite(feature.anchor.y))).toBe(true)
    const labelsOverlap = (first: typeof YUANMING_STRATEGIC_OVERLAY[number], second: typeof YUANMING_STRATEGIC_OVERLAY[number]) => (
      first.label.x < second.label.x + second.label.width
      && first.label.x + first.label.width > second.label.x
      && first.label.y < second.label.y + second.label.height
      && first.label.y + first.label.height > second.label.y
    )
    expect(YUANMING_STRATEGIC_OVERLAY.flatMap((feature, index) => (
      YUANMING_STRATEGIC_OVERLAY.slice(index + 1).map((other) => labelsOverlap(feature, other))
    ))).not.toContain(true)
  })

  it('maps all eight canonical regions to stable feature ids', () => {
    const result = joinRegionsToMap(YUANMING_STRATEGIC_OVERLAY.map((feature) => makeRegion(feature.displayName)))
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
