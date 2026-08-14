import {
  EAST_ASIA_POLITICAL_GRID,
  type PoliticalGridFeature,
} from './eastAsiaPoliticalGrid'

export interface MapPoint {
  readonly x: number
  readonly y: number
}

export interface MapRect {
  readonly x: number
  readonly y: number
  readonly width: number
  readonly height: number
}

export interface OutlineLabelDefinition {
  readonly id: string
  readonly text: string
  readonly countryIds: readonly string[]
  readonly provinceIds: readonly string[]
  readonly preferred: MapPoint
  readonly baseFontSize: number
  readonly minimumFontSize: number
}

export interface OutlineLabelLayout extends MapPoint {
  readonly id: string
  readonly fontSize: number
  readonly fit: 'inside-clear' | 'inside' | 'fallback'
  readonly outlineIds: readonly string[]
  readonly rect: MapRect
}

interface Bounds {
  readonly minimumX: number
  readonly minimumY: number
  readonly maximumX: number
  readonly maximumY: number
}

type Ring = readonly MapPoint[]

interface ParsedFeature {
  readonly id: string
  readonly rings: readonly Ring[]
  readonly bounds: Bounds
}

const countryById = new Map<string, PoliticalGridFeature>(
  EAST_ASIA_POLITICAL_GRID.countries.map((feature) => [feature.id, feature]),
)
const provinceById = new Map<string, PoliticalGridFeature>(
  EAST_ASIA_POLITICAL_GRID.chinaProvinces.map((feature) => [feature.id, feature]),
)
const parsedFeatureCache = new Map<string, ParsedFeature>()

function parseLinearPath(path: string): readonly Ring[] {
  const tokens = path.match(/[MLZ]|-?\d+(?:\.\d+)?/g) ?? []
  const rings: MapPoint[][] = []
  let ring: MapPoint[] = []
  let cursor = 0

  while (cursor < tokens.length) {
    const command = tokens[cursor]
    cursor += 1
    if (command === 'Z') {
      if (ring.length >= 3) rings.push(ring)
      ring = []
      continue
    }
    if (command !== 'M' && command !== 'L') {
      throw new Error(`Unsupported political-grid path command: ${command}`)
    }
    const x = Number(tokens[cursor])
    const y = Number(tokens[cursor + 1])
    cursor += 2
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error('Political-grid path contains an invalid coordinate')
    }
    if (command === 'M' && ring.length >= 3) rings.push(ring)
    if (command === 'M') ring = []
    ring.push({ x, y })
  }
  if (ring.length >= 3) rings.push(ring)
  return rings
}

function boundsForRings(rings: readonly Ring[]): Bounds {
  const points = rings.flat()
  return {
    minimumX: Math.min(...points.map((point) => point.x)),
    minimumY: Math.min(...points.map((point) => point.y)),
    maximumX: Math.max(...points.map((point) => point.x)),
    maximumY: Math.max(...points.map((point) => point.y)),
  }
}

function parsedFeature(feature: PoliticalGridFeature): ParsedFeature {
  const cached = parsedFeatureCache.get(feature.id)
  if (cached) return cached
  const rings = parseLinearPath(feature.path)
  const parsed = { id: feature.id, rings, bounds: boundsForRings(rings) }
  parsedFeatureCache.set(feature.id, parsed)
  return parsed
}

function pointOnSegment(point: MapPoint, start: MapPoint, end: MapPoint): boolean {
  const cross = (point.y - start.y) * (end.x - start.x) - (point.x - start.x) * (end.y - start.y)
  if (Math.abs(cross) > 0.01) return false
  const dot = (point.x - start.x) * (end.x - start.x) + (point.y - start.y) * (end.y - start.y)
  if (dot < 0) return false
  const squaredLength = (end.x - start.x) ** 2 + (end.y - start.y) ** 2
  return dot <= squaredLength
}

function pointInRing(point: MapPoint, ring: Ring): boolean {
  let inside = false
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const start = ring[previous]
    const end = ring[index]
    if (pointOnSegment(point, start, end)) return true
    const crossesRay = (start.y > point.y) !== (end.y > point.y)
      && point.x < ((end.x - start.x) * (point.y - start.y)) / (end.y - start.y) + start.x
    if (crossesRay) inside = !inside
  }
  return inside
}

function pointInFeature(point: MapPoint, feature: ParsedFeature): boolean {
  if (
    point.x < feature.bounds.minimumX
    || point.x > feature.bounds.maximumX
    || point.y < feature.bounds.minimumY
    || point.y > feature.bounds.maximumY
  ) return false

  let inside = false
  for (const ring of feature.rings) {
    if (pointInRing(point, ring)) inside = !inside
  }
  return inside
}

function pointInOutlines(point: MapPoint, features: readonly ParsedFeature[]): boolean {
  return features.some((feature) => pointInFeature(point, feature))
}

function boundsForFeatures(features: readonly ParsedFeature[]): Bounds {
  return {
    minimumX: Math.min(...features.map((feature) => feature.bounds.minimumX)),
    minimumY: Math.min(...features.map((feature) => feature.bounds.minimumY)),
    maximumX: Math.max(...features.map((feature) => feature.bounds.maximumX)),
    maximumY: Math.max(...features.map((feature) => feature.bounds.maximumY)),
  }
}

export function outlineLabelRect(point: MapPoint, text: string, fontSize: number): MapRect {
  const width = Array.from(text).length * fontSize * 0.92 + 4
  const height = fontSize * 1.12 + 4
  return {
    x: point.x - width / 2,
    y: point.y - fontSize * 0.86 - 2,
    width,
    height,
  }
}

function rectangleSamplePoints(rect: MapRect): readonly MapPoint[] {
  const points: MapPoint[] = []
  const columns = 5
  const rows = 3
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      points.push({
        x: rect.x + (rect.width * column) / (columns - 1),
        y: rect.y + (rect.height * row) / (rows - 1),
      })
    }
  }
  return points
}

function rectangleInsideOutlines(rect: MapRect, features: readonly ParsedFeature[]): boolean {
  return rectangleSamplePoints(rect).every((point) => pointInOutlines(point, features))
}

function rectanglesOverlap(first: MapRect, second: MapRect, padding = 3): boolean {
  return first.x < second.x + second.width + padding
    && first.x + first.width + padding > second.x
    && first.y < second.y + second.height + padding
    && first.y + first.height + padding > second.y
}

function findBestPlacement(
  definition: OutlineLabelDefinition,
  features: readonly ParsedFeature[],
  obstacles: readonly MapRect[],
  fontSize: number,
): { point: MapPoint; rect: MapRect } | null {
  const preferredRect = outlineLabelRect(definition.preferred, definition.text, fontSize)
  if (
    rectangleInsideOutlines(preferredRect, features)
    && obstacles.every((obstacle) => !rectanglesOverlap(preferredRect, obstacle))
  ) return { point: definition.preferred, rect: preferredRect }

  const bounds = boundsForFeatures(features)
  const step = Math.max(4, Math.round(fontSize / 2))
  let best: { point: MapPoint; rect: MapRect; score: number } | null = null
  for (let y = bounds.minimumY; y <= bounds.maximumY; y += step) {
    for (let x = bounds.minimumX; x <= bounds.maximumX; x += step) {
      const point = { x, y }
      if (!pointInOutlines(point, features)) continue
      const rect = outlineLabelRect(point, definition.text, fontSize)
      if (!rectangleInsideOutlines(rect, features)) continue
      if (obstacles.some((obstacle) => rectanglesOverlap(rect, obstacle))) continue
      const score = (x - definition.preferred.x) ** 2 + (y - definition.preferred.y) ** 2
      if (!best || score < best.score) best = { point, rect, score }
    }
  }
  return best
}

function resolveFeatures(definition: OutlineLabelDefinition): {
  readonly features: readonly ParsedFeature[]
  readonly outlineIds: readonly string[]
} {
  const politicalFeatures = [
    ...definition.countryIds.map((id) => countryById.get(id)),
    ...definition.provinceIds.map((id) => provinceById.get(id)),
  ].filter((feature): feature is PoliticalGridFeature => Boolean(feature))
  return {
    features: politicalFeatures.map(parsedFeature),
    outlineIds: politicalFeatures.map((feature) => feature.id),
  }
}

function closestInteriorPoint(definition: OutlineLabelDefinition, features: readonly ParsedFeature[]): MapPoint {
  const bounds = boundsForFeatures(features)
  let best: { point: MapPoint; score: number } | null = null
  for (let y = bounds.minimumY; y <= bounds.maximumY; y += 3) {
    for (let x = bounds.minimumX; x <= bounds.maximumX; x += 3) {
      const point = { x, y }
      if (!pointInOutlines(point, features)) continue
      const score = (x - definition.preferred.x) ** 2 + (y - definition.preferred.y) ** 2
      if (!best || score < best.score) best = { point, score }
    }
  }
  return best?.point ?? definition.preferred
}

export function layoutOutlineLabels(
  definitions: readonly OutlineLabelDefinition[],
  initialObstacles: readonly MapRect[] = [],
): readonly OutlineLabelLayout[] {
  const obstacles = [...initialObstacles]
  return definitions.map((definition) => {
    const { features, outlineIds } = resolveFeatures(definition)
    if (features.length === 0) {
      const rect = outlineLabelRect(definition.preferred, definition.text, definition.minimumFontSize)
      return {
        id: definition.id,
        ...definition.preferred,
        fontSize: definition.minimumFontSize,
        fit: 'fallback' as const,
        outlineIds,
        rect,
      }
    }

    for (let fontSize = definition.baseFontSize; fontSize >= definition.minimumFontSize; fontSize -= 1) {
      const placement = findBestPlacement(definition, features, obstacles, fontSize)
      if (!placement) continue
      obstacles.push(placement.rect)
      return {
        id: definition.id,
        ...placement.point,
        fontSize,
        fit: 'inside-clear' as const,
        outlineIds,
        rect: placement.rect,
      }
    }

    const placement = findBestPlacement(definition, features, [], definition.minimumFontSize)
    if (placement) {
      obstacles.push(placement.rect)
      return {
        id: definition.id,
        ...placement.point,
        fontSize: definition.minimumFontSize,
        fit: 'inside' as const,
        outlineIds,
        rect: placement.rect,
      }
    }

    const point = closestInteriorPoint(definition, features)
    const rect = outlineLabelRect(point, definition.text, definition.minimumFontSize)
    return {
      id: definition.id,
      ...point,
      fontSize: definition.minimumFontSize,
      fit: 'fallback' as const,
      outlineIds,
      rect,
    }
  })
}
