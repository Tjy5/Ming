import type { Region } from '../../types/game'
import { EAST_ASIA_REFERENCE_BASEMAP } from './eastAsiaReferenceBasemap'

/** Legacy server-region bindings retained for saves, events, and settlement. */
export interface LegacyRegionBinding {
  readonly id: string
  readonly displayName: string
  readonly legacyNames: readonly string[]
  readonly governanceDivisionId: string
}

export interface HistoricalPolityLabel {
  readonly id: string
  readonly name: string
  readonly x: number
  readonly y: number
  readonly prominence: 'major' | 'neighbor' | 'local'
}

export type MapPaintTone = 'cinnabar' | 'ochre' | 'teal' | 'moss' | 'blue-gray' | 'clay'

export interface HistoricalPolityPaintGroup extends HistoricalPolityLabel {
  readonly countryIds: readonly string[]
  readonly provinceIds: readonly string[]
  readonly labelCountryIds?: readonly string[]
  readonly labelProvinceIds?: readonly string[]
  readonly tone: MapPaintTone
}

export interface HistoricalAdministrativeDivision {
  readonly id: string
  readonly name: string
  readonly countryIds: readonly string[]
  readonly provinceIds: readonly string[]
  readonly label: { readonly x: number; readonly y: number }
  readonly kind: 'central' | 'province' | 'special'
  readonly tone: MapPaintTone
}

export const MAP_VIEWBOX = EAST_ASIA_REFERENCE_BASEMAP.viewBox

const LEGACY_MAP_BOUNDS = { minLongitude: 73, maxLongitude: 150 } as const
const LEGACY_MAP_WIDTH = 1200
const CURRENT_ANGULAR_SCALE = EAST_ASIA_REFERENCE_BASEMAP.height
  / (EAST_ASIA_REFERENCE_BASEMAP.bounds.maxLatitude - EAST_ASIA_REFERENCE_BASEMAP.bounds.minLatitude)
const CURRENT_HORIZONTAL_PADDING = (
  EAST_ASIA_REFERENCE_BASEMAP.width
  - (EAST_ASIA_REFERENCE_BASEMAP.bounds.maxLongitude - EAST_ASIA_REFERENCE_BASEMAP.bounds.minLongitude) * CURRENT_ANGULAR_SCALE
) / 2
const LEGACY_X_SCALE = (
  (LEGACY_MAP_BOUNDS.maxLongitude - LEGACY_MAP_BOUNDS.minLongitude) * CURRENT_ANGULAR_SCALE
) / LEGACY_MAP_WIDTH
const LEGACY_X_OFFSET = CURRENT_HORIZONTAL_PADDING
  + (LEGACY_MAP_BOUNDS.minLongitude - EAST_ASIA_REFERENCE_BASEMAP.bounds.minLongitude) * CURRENT_ANGULAR_SCALE

/** Reprojects project-authored overlays from the former 73-150 E map crop. */
export const LEGACY_MAP_X_TRANSFORM = `matrix(${LEGACY_X_SCALE} 0 0 1 ${LEGACY_X_OFFSET} 0)`

export function reprojectLegacyMapX(x: number): number {
  return LEGACY_X_OFFSET + x * LEGACY_X_SCALE
}

/** Modern country/province IDs are paint units only; all displayed names are historical. */
export const HISTORICAL_POLITY_PAINT_GROUPS: readonly HistoricalPolityPaintGroup[] = [
  { id: 'yuan-court', name: '元廷', x: 650, y: 132, prominence: 'major', countryIds: [], provinceIds: [], labelProvinceIds: ['CN-NM'], tone: 'cinnabar' },
  { id: 'chagatai-khanate', name: '察合台汗国', x: 175, y: 215, prominence: 'neighbor', countryIds: ['KAZ', 'KGZ', 'TJK', 'UZB'], provinceIds: ['CN-XJ'], tone: 'ochre' },
  { id: 'tibetan-polities', name: '吐蕃诸部', x: 230, y: 405, prominence: 'local', countryIds: [], provinceIds: [], labelProvinceIds: ['CN-XZ'], tone: 'clay' },
  { id: 'goryeo', name: '高丽', x: 852, y: 260, prominence: 'neighbor', countryIds: ['PRK', 'KOR'], provinceIds: [], tone: 'teal' },
  { id: 'japan', name: '日本', x: 1030, y: 270, prominence: 'neighbor', countryIds: ['JPN'], provinceIds: [], tone: 'blue-gray' },
  { id: 'ryukyu', name: '琉球', x: 910, y: 440, prominence: 'neighbor', countryIds: [], provinceIds: [], labelCountryIds: ['JPN'], tone: 'blue-gray' },
  { id: 'myanmar-polities', name: '缅甸诸邦', x: 365, y: 472, prominence: 'neighbor', countryIds: ['MMR'], provinceIds: [], tone: 'moss' },
  { id: 'dai-viet', name: '大越', x: 520, y: 472, prominence: 'neighbor', countryIds: ['VNM'], provinceIds: [], tone: 'teal' },
  { id: 'champa', name: '占城', x: 558, y: 557, prominence: 'neighbor', countryIds: [], provinceIds: [], labelCountryIds: ['VNM'], tone: 'clay' },
]

/** Backward-compatible label projection; names and positions stay single-sourced above. */
export const YUAN_END_POLITY_LABELS: readonly HistoricalPolityLabel[] = HISTORICAL_POLITY_PAINT_GROUPS

/**
 * Approximate Yuan administrative divisions, not present-day provinces. These
 * show the 行省/中书省/宣政院 framework and are intentionally schematic.
 */
export const YUAN_ADMINISTRATIVE_DIVISIONS: readonly HistoricalAdministrativeDivision[] = [
  { id: 'lingbei', name: '岭北行省', countryIds: ['MNG'], provinceIds: [], label: { x: 570, y: 95 }, kind: 'province', tone: 'blue-gray' },
  { id: 'liaoyang', name: '辽阳行省', countryIds: [], provinceIds: ['CN-LN', 'CN-JL', 'CN-HL'], label: { x: 855, y: 150 }, kind: 'province', tone: 'moss' },
  { id: 'zhongshu', name: '中书省', countryIds: [], provinceIds: ['CN-BJ', 'CN-TJ', 'CN-HE', 'CN-SD', 'CN-SX', 'CN-NM'], label: { x: 730, y: 235 }, kind: 'central', tone: 'cinnabar' },
  { id: 'gansu', name: '甘肃行省', countryIds: [], provinceIds: ['CN-GS', 'CN-NX'], label: { x: 470, y: 260 }, kind: 'province', tone: 'ochre' },
  { id: 'shaanxi', name: '陕西行省', countryIds: [], provinceIds: ['CN-SN'], label: { x: 575, y: 315 }, kind: 'province', tone: 'clay' },
  { id: 'henan-jiangbei', name: '河南江北行省', countryIds: [], provinceIds: ['CN-HA', 'CN-AH', 'CN-JS'], label: { x: 700, y: 320 }, kind: 'province', tone: 'teal' },
  { id: 'sichuan', name: '四川行省', countryIds: [], provinceIds: ['CN-SC', 'CN-CQ'], label: { x: 510, y: 395 }, kind: 'province', tone: 'moss' },
  { id: 'yunnan', name: '云南行省', countryIds: [], provinceIds: ['CN-YN'], label: { x: 455, y: 505 }, kind: 'province', tone: 'ochre' },
  { id: 'huguang', name: '湖广行省', countryIds: [], provinceIds: ['CN-HB', 'CN-HN', 'CN-GX', 'CN-GZ', 'CN-HI'], label: { x: 610, y: 455 }, kind: 'province', tone: 'blue-gray' },
  { id: 'jiangxi', name: '江西行省', countryIds: [], provinceIds: ['CN-JX', 'CN-GD'], label: { x: 705, y: 475 }, kind: 'province', tone: 'clay' },
  { id: 'jiangzhe', name: '江浙行省', countryIds: [], provinceIds: ['CN-ZJ', 'CN-FJ', 'CN-SH'], label: { x: 790, y: 400 }, kind: 'province', tone: 'ochre' },
  { id: 'xuanzheng', name: '宣政院辖地', countryIds: [], provinceIds: ['CN-XZ', 'CN-QH'], label: { x: 300, y: 360 }, kind: 'special', tone: 'teal' },
]

export function polityForCountryId(id: string): HistoricalPolityPaintGroup | undefined {
  return HISTORICAL_POLITY_PAINT_GROUPS.find((group) => group.countryIds.includes(id))
}

export function polityForProvinceId(id: string): HistoricalPolityPaintGroup | undefined {
  return HISTORICAL_POLITY_PAINT_GROUPS.find((group) => group.provinceIds.includes(id))
}

export function administrativeDivisionForCountryId(id: string): HistoricalAdministrativeDivision | undefined {
  return YUAN_ADMINISTRATIVE_DIVISIONS.find((division) => division.countryIds.includes(id))
}

export function administrativeDivisionForProvinceId(id: string): HistoricalAdministrativeDivision | undefined {
  return YUAN_ADMINISTRATIVE_DIVISIONS.find((division) => division.provinceIds.includes(id))
}

export const LEGACY_REGION_BINDINGS: readonly LegacyRegionBinding[] = [
  { id: 'dadu', displayName: '大都', legacyNames: ['大都'], governanceDivisionId: 'zhongshu' },
  { id: 'lianghuai', displayName: '两淮', legacyNames: ['两淮'], governanceDivisionId: 'henan-jiangbei' },
  { id: 'yingtian', displayName: '应天', legacyNames: ['应天', '集庆'], governanceDivisionId: 'henan-jiangbei' },
  { id: 'taiping', displayName: '太平', legacyNames: ['太平'], governanceDivisionId: 'henan-jiangbei' },
  { id: 'zhenjiang', displayName: '镇江', legacyNames: ['镇江'], governanceDivisionId: 'henan-jiangbei' },
  { id: 'pingjiang', displayName: '平江', legacyNames: ['平江'], governanceDivisionId: 'henan-jiangbei' },
  { id: 'wuchang', displayName: '武昌', legacyNames: ['武昌'], governanceDivisionId: 'huguang' },
  { id: 'hangzhou', displayName: '杭州', legacyNames: ['杭州'], governanceDivisionId: 'jiangzhe' },
]

export interface GovernanceDivisionStatus {
  division: HistoricalAdministrativeDivision
  region: Region | null
  sourceRegionNames: readonly string[]
  sourceRegions: readonly Region[]
  state: 'mapped' | 'partial' | 'missing'
}

const CONTROL_PRIORITY: Readonly<Record<Region['control'], number>> = { '朝廷': 0, '失控': 1, '沦陷': 2 }
const TAX_CONTRIBUTION_PRIORITY: Readonly<Record<Region['tax_contribution'], number>> = { low: 0, medium: 1, high: 2 }

function average(regions: readonly Region[], field: 'stability' | 'civil_morale' | 'rebellion_risk' | 'tax_rate' | 'disaster_level'): number {
  return regions.reduce((total, region) => total + region[field], 0) / regions.length
}

function aggregateDivisionRegion(name: string, regions: readonly Region[]): Region {
  const worstControl = regions.reduce((worst, region) => (
    CONTROL_PRIORITY[region.control] > CONTROL_PRIORITY[worst] ? region.control : worst
  ), regions[0].control)
  const highestContribution = regions.reduce((highest, region) => (
    TAX_CONTRIBUTION_PRIORITY[region.tax_contribution] > TAX_CONTRIBUTION_PRIORITY[highest]
      ? region.tax_contribution
      : highest
  ), regions[0].tax_contribution)
  return {
    name,
    stability: Math.round(average(regions, 'stability')),
    garrison: regions.reduce((total, region) => total + region.garrison, 0),
    control: worstControl,
    threat: regions.find((region) => region.threat !== 'none')?.threat ?? 'none',
    tax_contribution: highestContribution,
    civil_morale: Math.round(average(regions, 'civil_morale')),
    rebellion_risk: Math.round(average(regions, 'rebellion_risk')),
    tax_rate: Number(average(regions, 'tax_rate').toFixed(2)),
    tax_collected: regions.reduce((total, region) => total + region.tax_collected, 0),
    disaster_level: Math.round(average(regions, 'disaster_level')),
  }
}

export function normalizeRegionName(value: string): string {
  return value.trim().replace(/\s+/g, '')
}

export function bindingForLegacyRegionName(name: string): LegacyRegionBinding | undefined {
  const normalized = normalizeRegionName(name)
  return LEGACY_REGION_BINDINGS.find((binding) => binding.legacyNames.some((legacy) => normalizeRegionName(legacy) === normalized))
}

export function joinRegionsToGovernanceDivisions(regions: Region[]): {
  divisions: GovernanceDivisionStatus[]
  unmapped: Region[]
  duplicates: Region[]
} {
  const byBindingId = new Map<string, Region>()
  const duplicates: Region[] = []
  const unmapped: Region[] = []
  for (const region of regions) {
    const binding = bindingForLegacyRegionName(region.name)
    if (!binding) {
      unmapped.push(region)
      continue
    }
    if (byBindingId.has(binding.id)) {
      duplicates.push(region)
      continue
    }
    byBindingId.set(binding.id, region)
  }
  return {
    divisions: YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => {
      const bindings = LEGACY_REGION_BINDINGS.filter((binding) => binding.governanceDivisionId === division.id)
      const sourceRegions = bindings.flatMap((binding) => {
        const region = byBindingId.get(binding.id)
        return region ? [region] : []
      })
      return {
        division,
        sourceRegionNames: bindings.map((binding) => binding.displayName),
        sourceRegions,
        region: sourceRegions.length > 0 ? aggregateDivisionRegion(division.name, sourceRegions) : null,
        state: sourceRegions.length === 0
          ? 'missing' as const
          : sourceRegions.length === bindings.length
            ? 'mapped' as const
            : 'partial' as const,
      }
    }),
    unmapped,
    duplicates,
  }
}
