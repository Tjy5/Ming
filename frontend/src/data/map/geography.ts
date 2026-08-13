import type { Region } from '../../types/game'
import { CHINA_REFERENCE_BASEMAP } from './chinaReferenceBasemap'

/**
 * Approximate Yuan-end strategic interaction areas over a modern reference map.
 * These hand-reviewed paths are gameplay overlays, not administrative borders.
 */
export interface StrategicOverlayFeature {
  readonly mapRegionId: string
  readonly displayName: string
  readonly legacyNames: readonly string[]
  readonly path: string
  readonly anchor: { readonly x: number; readonly y: number }
  readonly label: { readonly x: number; readonly y: number; readonly width: number; readonly height: number }
}

export const MAP_VIEWBOX = CHINA_REFERENCE_BASEMAP.viewBox

export const YUANMING_STRATEGIC_OVERLAY: readonly StrategicOverlayFeature[] = [
  { mapRegionId: 'dadu', displayName: '大都', legacyNames: ['大都'], path: 'M560 188 C570 171 594 166 609 179 C621 192 614 214 594 220 C575 224 554 209 560 188 Z', anchor: { x: 586, y: 195 }, label: { x: 548, y: 139, width: 78, height: 45 } },
  { mapRegionId: 'lianghuai', displayName: '两淮', legacyNames: ['两淮'], path: 'M541 322 C559 305 592 304 612 320 C625 334 617 352 596 359 C570 363 539 349 541 322 Z', anchor: { x: 580, y: 334 }, label: { x: 514, y: 281, width: 86, height: 44 } },
  { mapRegionId: 'wuchang', displayName: '武昌', legacyNames: ['武昌'], path: 'M478 369 C493 353 519 354 531 370 C541 386 526 404 505 405 C484 405 468 387 478 369 Z', anchor: { x: 505, y: 380 }, label: { x: 432, y: 359, width: 82, height: 46 } },
  { mapRegionId: 'taiping', displayName: '太平', legacyNames: ['太平'], path: 'M563 367 C570 358 585 359 591 369 C596 379 587 390 575 390 C563 389 556 377 563 367 Z', anchor: { x: 576, y: 374 }, label: { x: 520, y: 405, width: 78, height: 44 } },
  { mapRegionId: 'yingtian', displayName: '应天', legacyNames: ['应天', '集庆'], path: 'M580 354 C588 345 603 348 607 359 C610 371 598 379 587 375 C576 372 573 362 580 354 Z', anchor: { x: 591, y: 361 }, label: { x: 548, y: 333, width: 82, height: 44 } },
  { mapRegionId: 'zhenjiang', displayName: '镇江', legacyNames: ['镇江'], path: 'M597 354 C603 347 614 348 619 356 C622 365 614 373 605 371 C596 369 592 361 597 354 Z', anchor: { x: 607, y: 359 }, label: { x: 631, y: 319, width: 84, height: 44 } },
  { mapRegionId: 'pingjiang', displayName: '平江', legacyNames: ['平江'], path: 'M609 371 C617 362 631 365 635 376 C637 387 626 395 616 391 C606 388 603 379 609 371 Z', anchor: { x: 620, y: 378 }, label: { x: 650, y: 369, width: 82, height: 44 } },
  { mapRegionId: 'hangzhou', displayName: '杭州', legacyNames: ['杭州'], path: 'M606 397 C615 385 632 388 637 401 C640 414 626 423 614 418 C603 414 599 405 606 397 Z', anchor: { x: 619, y: 403 }, label: { x: 616, y: 431, width: 84, height: 44 } },
]

export type MapRegionStatus = {
  feature: StrategicOverlayFeature
  region: Region | null
  state: 'mapped' | 'missing'
}

export function normalizeRegionName(value: string): string {
  return value.trim().replace(/\s+/g, '')
}

export function featureForLegacyName(name: string): StrategicOverlayFeature | undefined {
  const normalized = normalizeRegionName(name)
  return YUANMING_STRATEGIC_OVERLAY.find((feature) => feature.legacyNames.some((legacy) => normalizeRegionName(legacy) === normalized))
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
    features: YUANMING_STRATEGIC_OVERLAY.map((feature) => ({
      feature,
      region: byId.get(feature.mapRegionId) ?? null,
      state: byId.has(feature.mapRegionId) ? 'mapped' : 'missing',
    })),
    unmapped,
    duplicates,
  }
}
