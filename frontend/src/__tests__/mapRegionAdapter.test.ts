import { describe, expect, it } from 'vitest'
import { EAST_ASIA_REFERENCE_BASEMAP } from '../data/map/eastAsiaReferenceBasemap'
import { EAST_ASIA_POLITICAL_GRID } from '../data/map/eastAsiaPoliticalGrid'
import {
  HISTORICAL_POLITY_PAINT_GROUPS,
  LEGACY_REGION_BINDINGS,
  administrativeDivisionForCountryId,
  administrativeDivisionForProvinceId,
  bindingForLegacyRegionName,
  joinRegionsToGovernanceDivisions,
  polityForCountryId,
  polityForProvinceId,
  reprojectLegacyMapX,
  YUAN_ADMINISTRATIVE_DIVISIONS,
  YUAN_END_POLITY_LABELS,
  normalizeRegionName,
} from '../data/map/geography'
import { layoutOutlineLabels } from '../data/map/outlineLabelLayout'
import type { Region } from '../types/game'

const makeRegion = (name: string): Region => ({
  name, stability: 50, garrison: 1, control: '朝廷', threat: 'none',
  tax_contribution: 'medium', civil_morale: 50, rebellion_risk: 20,
  tax_rate: 0.5, tax_collected: 1, disaster_level: 0,
})

describe('map geography adapter', () => {
  it('loads the attributed East Asia physical basemap without gameplay ids', () => {
    expect(EAST_ASIA_REFERENCE_BASEMAP).toMatchObject({
      viewBox: '0 0 1200 650',
      sourceRepository: 'nvkelso/natural-earth-vector',
      sourceCommit: 'ca96624a56bd078437bca8184e78163e5039ad19',
      sourceSha256: 'e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b',
      license: 'Public Domain',
    })
    expect(EAST_ASIA_REFERENCE_BASEMAP.features.length).toBe(EAST_ASIA_REFERENCE_BASEMAP.clippedFeatureCount)
    expect(EAST_ASIA_REFERENCE_BASEMAP.features.length).toBeGreaterThan(20)
    expect(new Set(EAST_ASIA_REFERENCE_BASEMAP.features.map((feature) => feature.id)).size).toBe(EAST_ASIA_REFERENCE_BASEMAP.features.length)
    const horizontalPixelsPerDegree = EAST_ASIA_REFERENCE_BASEMAP.width
      / (EAST_ASIA_REFERENCE_BASEMAP.bounds.maxLongitude - EAST_ASIA_REFERENCE_BASEMAP.bounds.minLongitude)
    const verticalPixelsPerDegree = EAST_ASIA_REFERENCE_BASEMAP.height
      / (EAST_ASIA_REFERENCE_BASEMAP.bounds.maxLatitude - EAST_ASIA_REFERENCE_BASEMAP.bounds.minLatitude)
    expect(horizontalPixelsPerDegree / verticalPixelsPerDegree).toBeCloseTo(1, 2)
    const gameplayIds = new Set(LEGACY_REGION_BINDINGS.map((binding) => binding.id))
    expect(EAST_ASIA_REFERENCE_BASEMAP.features.every((feature) => !gameplayIds.has(feature.id))).toBe(true)
  })

  it('loads the pinned Natural Earth country and China province paint grid', () => {
    expect(EAST_ASIA_POLITICAL_GRID).toMatchObject({
      viewBox: '0 0 1200 650',
      sourceRepository: 'nvkelso/natural-earth-vector',
      sourceCommit: 'ca96624a56bd078437bca8184e78163e5039ad19',
      license: 'Public Domain',
      sources: {
        countries: { sha256: '3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb' },
        provinces: { sha256: '69a0e06e640b2d505858ae1cb63034e4677f3000b35a98e16312932b98c426b9' },
      },
    })
    expect(EAST_ASIA_POLITICAL_GRID.countries).toHaveLength(33)
    expect(EAST_ASIA_POLITICAL_GRID.chinaProvinces).toHaveLength(31)
    expect(EAST_ASIA_POLITICAL_GRID.countries.some((country) => country.id === 'JPN')).toBe(true)
    expect(EAST_ASIA_POLITICAL_GRID.chinaProvinces.some((province) => province.id === 'CN-XJ')).toBe(true)
  })

  it('maps surrounding mid-14th-century polity labels onto current geographic paint units', () => {
    expect(YUAN_END_POLITY_LABELS.map((label) => label.name)).toEqual([
      '元廷', '察合台汗国', '吐蕃诸部', '高丽', '日本', '琉球', '缅甸诸邦', '大越', '占城',
    ])
    expect(YUAN_END_POLITY_LABELS.every((label) => label.x > 0 && label.x < 1200 && label.y > 0 && label.y < 650)).toBe(true)
    expect(HISTORICAL_POLITY_PAINT_GROUPS.map((group) => group.id)).toEqual(YUAN_END_POLITY_LABELS.map((label) => label.id))
    expect(new Set(HISTORICAL_POLITY_PAINT_GROUPS.map((group) => group.id)).size).toBe(HISTORICAL_POLITY_PAINT_GROUPS.length)
    expect(polityForCountryId('JPN')?.id).toBe('japan')
    expect(polityForProvinceId('CN-XJ')?.id).toBe('chagatai-khanate')
    expect(HISTORICAL_POLITY_PAINT_GROUPS.find((group) => group.id === 'tibetan-polities')?.prominence).toBe('local')
  })

  it('uses Yuan-era administrative divisions instead of present-day provinces', () => {
    expect(YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => division.name)).toEqual([
      '岭北行省', '辽阳行省', '中书省', '甘肃行省', '陕西行省', '河南江北行省',
      '四川行省', '云南行省', '湖广行省', '江西行省', '江浙行省', '宣政院辖地',
    ])
    expect(YUAN_ADMINISTRATIVE_DIVISIONS.every((division) => division.countryIds.length + division.provinceIds.length > 0)).toBe(true)
    expect(new Set(YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => division.id)).size).toBe(YUAN_ADMINISTRATIVE_DIVISIONS.length)
    expect(YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => division.name).join('')).not.toMatch(/河北省|河南省|湖北省|广东省/)
    expect(administrativeDivisionForCountryId('MNG')?.id).toBe('lingbei')
    expect(administrativeDivisionForProvinceId('CN-SD')?.id).toBe('zhongshu')
    const assignedProvinceIds = YUAN_ADMINISTRATIVE_DIVISIONS.flatMap((division) => division.provinceIds)
    expect(new Set(assignedProvinceIds).size).toBe(assignedProvinceIds.length)
    const countryIds = new Set<string>(EAST_ASIA_POLITICAL_GRID.countries.map((country) => country.id))
    const provinceIds = new Set<string>(EAST_ASIA_POLITICAL_GRID.chinaProvinces.map((province) => province.id))
    expect(YUAN_ADMINISTRATIVE_DIVISIONS.flatMap((division) => division.countryIds).every((id) => countryIds.has(id))).toBe(true)
    expect(assignedProvinceIds.every((id) => provinceIds.has(id))).toBe(true)
    expect(HISTORICAL_POLITY_PAINT_GROUPS.flatMap((group) => group.countryIds).every((id) => countryIds.has(id))).toBe(true)
    expect(HISTORICAL_POLITY_PAINT_GROUPS.flatMap((group) => group.provinceIds).every((id) => provinceIds.has(id))).toBe(true)
  })

  it('binds all eight legacy records to historical administrative divisions', () => {
    expect(LEGACY_REGION_BINDINGS.map((binding) => binding.id)).toEqual([
      'dadu', 'lianghuai', 'yingtian', 'taiping', 'zhenjiang', 'pingjiang', 'wuchang', 'hangzhou',
    ])
    expect(LEGACY_REGION_BINDINGS.filter((binding) => binding.governanceDivisionId === 'henan-jiangbei')).toHaveLength(5)
    expect(new Set(LEGACY_REGION_BINDINGS.map((binding) => binding.governanceDivisionId))).toEqual(
      new Set(['zhongshu', 'henan-jiangbei', 'huguang', 'jiangzhe']),
    )
  })

  it('derives Yuan administrative label positions from their assigned outlines', () => {
    const layouts = layoutOutlineLabels(YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => ({
      id: division.id,
      text: division.name,
      countryIds: division.countryIds,
      provinceIds: division.provinceIds,
      preferred: { x: reprojectLegacyMapX(division.label.x), y: division.label.y },
      baseFontSize: division.kind === 'central' ? 13 : 12,
      minimumFontSize: 8,
    })))

    expect(layouts).toHaveLength(YUAN_ADMINISTRATIVE_DIVISIONS.length)
    expect(layouts.every((layout) => layout.outlineIds.length > 0)).toBe(true)
    expect(layouts.every((layout) => layout.fit !== 'fallback')).toBe(true)
  })

  it('aggregates all eight canonical regions into four mapped administrative divisions', () => {
    const result = joinRegionsToGovernanceDivisions(LEGACY_REGION_BINDINGS.map((binding) => makeRegion(binding.displayName)))
    expect(result.divisions.filter((item) => item.state === 'mapped').map((item) => item.division.id)).toEqual([
      'zhongshu', 'henan-jiangbei', 'huguang', 'jiangzhe',
    ])
    expect(result.divisions.filter((item) => item.state === 'missing')).toHaveLength(8)
    const henanJiangbei = result.divisions.find((item) => item.division.id === 'henan-jiangbei')
    expect(henanJiangbei?.region).toMatchObject({ name: '河南江北行省', garrison: 5, tax_collected: 5 })
    expect(henanJiangbei?.sourceRegions).toHaveLength(5)
    expect(result.unmapped).toHaveLength(0)
    expect(result.duplicates).toHaveLength(0)
  })

  it('uses explicit aggregation rules for administrative status', () => {
    const result = joinRegionsToGovernanceDivisions([
      { ...makeRegion('应天'), stability: 40, garrison: 100, control: '朝廷', tax_contribution: 'low', tax_collected: 10 },
      { ...makeRegion('两淮'), stability: 60, garrison: 200, control: '沦陷', tax_contribution: 'high', tax_collected: 20 },
    ])
    const region = result.divisions.find((item) => item.division.id === 'henan-jiangbei')?.region
    expect(region).toMatchObject({
      name: '河南江北行省', stability: 50, garrison: 300, control: '沦陷',
      tax_contribution: 'high', tax_collected: 30,
    })
  })

  it('normalizes whitespace and supports legacy aliases', () => {
    expect(normalizeRegionName('  应 天  ')).toBe('应天')
    expect(bindingForLegacyRegionName('集庆')?.id).toBe('yingtian')
  })

  it('reports unknown and duplicate payload entries without guessing geometry', () => {
    const result = joinRegionsToGovernanceDivisions([makeRegion('应天'), makeRegion('集庆'), makeRegion('不存在')])
    expect(result.duplicates.map((region) => region.name)).toEqual(['集庆'])
    expect(result.unmapped.map((region) => region.name)).toEqual(['不存在'])
    expect(result.divisions.find((item) => item.division.id === 'henan-jiangbei')?.sourceRegions[0]?.name).toBe('应天')
  })
})
