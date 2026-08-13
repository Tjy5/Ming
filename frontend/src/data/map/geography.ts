import type { Region } from '../../types/game'

/**
 * Repository-owned illustrative geography for the eight governance regions.
 * Coordinates are intentionally stylized and historical, not modern borders.
 */
export interface MapFeature {
  mapRegionId: string
  displayName: string
  legacyNames: readonly string[]
  path: string
  label: { x: number; y: number }
}

export const MAP_VIEWBOX = '0 0 1000 620'

export const MAP_LANDMASS_PATH = 'M70 136 C134 82 238 52 348 52 C456 18 626 24 760 82 C874 132 938 230 930 344 C954 430 914 536 820 582 C694 622 548 608 428 596 C304 610 194 568 108 502 C54 432 40 286 70 136 Z'

export const MAP_RIVERS = [
  'M278 72 C342 146 394 208 468 288 C536 350 628 392 748 492',
  'M438 84 C462 156 514 222 586 286 C652 340 734 364 876 390',
  'M202 204 C302 252 380 286 486 328 C574 364 624 422 654 536',
] as const

export const MAP_FEATURES: readonly MapFeature[] = [
  { mapRegionId: 'dadu', displayName: '大都', legacyNames: ['大都'], path: 'M378 48 C450 30 568 28 644 54 L724 92 L704 166 L628 194 L548 174 L468 186 L398 144 Z', label: { x: 566, y: 104 } },
  { mapRegionId: 'lianghuai', displayName: '两淮', legacyNames: ['两淮'], path: 'M398 178 L468 186 L548 174 L628 194 L712 176 L784 242 L760 302 L702 326 L624 306 L548 316 L468 282 L422 240 Z', label: { x: 610, y: 248 } },
  { mapRegionId: 'wuchang', displayName: '武昌', legacyNames: ['武昌'], path: 'M220 244 L302 226 L380 238 L422 240 L468 282 L548 316 L534 380 L474 414 L392 438 L318 408 L246 374 L202 314 Z', label: { x: 374, y: 332 } },
  { mapRegionId: 'taiping', displayName: '太平', legacyNames: ['太平'], path: 'M152 334 L202 314 L246 374 L318 408 L392 438 L356 506 L302 548 L222 548 L144 506 L104 438 Z', label: { x: 238, y: 440 } },
  { mapRegionId: 'yingtian', displayName: '应天', legacyNames: ['应天', '集庆'], path: 'M468 282 L548 316 L624 306 L676 350 L640 410 L584 452 L510 440 L474 414 L392 438 L422 382 Z', label: { x: 512, y: 374 } },
  { mapRegionId: 'zhenjiang', displayName: '镇江', legacyNames: ['镇江'], path: 'M624 306 L702 326 L760 302 L800 348 L752 392 L676 350 L640 410 L584 374 Z', label: { x: 680, y: 354 } },
  { mapRegionId: 'pingjiang', displayName: '平江', legacyNames: ['平江'], path: 'M676 350 L752 392 L800 348 L876 394 L870 468 L824 512 L726 536 L640 476 L584 452 L640 410 Z', label: { x: 744, y: 446 } },
  { mapRegionId: 'hangzhou', displayName: '杭州', legacyNames: ['杭州'], path: 'M584 452 L640 476 L726 536 L692 588 L604 602 L516 580 L470 520 L474 414 L510 440 Z', label: { x: 592, y: 524 } },
]

export type MapRegionStatus = {
  feature: MapFeature
  region: Region | null
  state: 'mapped' | 'missing'
}

export function normalizeRegionName(value: string): string {
  return value.trim().replace(/\s+/g, '')
}

export function featureForLegacyName(name: string): MapFeature | undefined {
  const normalized = normalizeRegionName(name)
  return MAP_FEATURES.find((feature) => feature.legacyNames.some((legacy) => normalizeRegionName(legacy) === normalized))
}

export function joinRegionsToMap(regions: Region[]): {
  features: MapRegionStatus[]
  unmapped: Region[]
  duplicates: Region[]
} {
  const byId = new Map<string, Region>()
  const duplicates: Region[] = []
  const unmapped: Region[] = []
  for (const region of regions) {
    const feature = featureForLegacyName(region.name)
    if (!feature) {
      unmapped.push(region)
      continue
    }
    if (byId.has(feature.mapRegionId)) {
      duplicates.push(region)
      continue
    }
    byId.set(feature.mapRegionId, region)
  }
  return {
    features: MAP_FEATURES.map((feature) => ({
      feature,
      region: byId.get(feature.mapRegionId) ?? null,
      state: byId.has(feature.mapRegionId) ? 'mapped' : 'missing',
    })),
    unmapped,
    duplicates,
  }
}
