import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { get } from 'node:https'
import { fileURLToPath } from 'node:url'

const SOURCE_COMMIT = 'ca96624a56bd078437bca8184e78163e5039ad19'
const SOURCE_URL = `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/${SOURCE_COMMIT}/geojson/ne_50m_land.geojson`
const EXPECTED_SHA256 = 'e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b'
const EXPECTED_FEATURE_COUNT = 1420
const VIEWBOX = { width: 1200, height: 650 }
const BOUNDS = { minLongitude: 65, maxLongitude: 157, minLatitude: 7, maxLatitude: 57 }
const ANGULAR_SCALE = VIEWBOX.height / (BOUNDS.maxLatitude - BOUNDS.minLatitude)
const HORIZONTAL_PADDING = (VIEWBOX.width - (BOUNDS.maxLongitude - BOUNDS.minLongitude) * ANGULAR_SCALE) / 2
const outputPath = fileURLToPath(new URL('../src/data/map/eastAsiaReferenceBasemap.ts', import.meta.url))

function download(url) {
  return new Promise((resolve, reject) => {
    get(url, (response) => {
      if (response.statusCode && response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume()
        download(response.headers.location).then(resolve, reject)
        return
      }
      if (response.statusCode !== 200) {
        reject(new Error(`Download failed with HTTP ${response.statusCode ?? 'unknown'}`))
        response.resume()
        return
      }
      const chunks = []
      response.on('data', (chunk) => chunks.push(chunk))
      response.on('end', () => resolve(Buffer.concat(chunks)))
      response.on('error', reject)
    }).on('error', reject)
  })
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(`${label} mismatch: expected ${expected}, received ${actual}`)
}

function clipAgainst(points, inside, intersect) {
  if (points.length === 0) return []
  const result = []
  let previous = points.at(-1)
  let previousInside = inside(previous)
  for (const current of points) {
    const currentInside = inside(current)
    if (currentInside !== previousInside) result.push(intersect(previous, current))
    if (currentInside) result.push(current)
    previous = current
    previousInside = currentInside
  }
  return result
}

function clipRing(sourceRing) {
  let points = sourceRing.slice(0, -1)
  points = clipAgainst(
    points,
    ([longitude]) => longitude >= BOUNDS.minLongitude,
    ([longitudeA, latitudeA], [longitudeB, latitudeB]) => {
      const ratio = (BOUNDS.minLongitude - longitudeA) / (longitudeB - longitudeA)
      return [BOUNDS.minLongitude, latitudeA + ratio * (latitudeB - latitudeA)]
    },
  )
  points = clipAgainst(
    points,
    ([longitude]) => longitude <= BOUNDS.maxLongitude,
    ([longitudeA, latitudeA], [longitudeB, latitudeB]) => {
      const ratio = (BOUNDS.maxLongitude - longitudeA) / (longitudeB - longitudeA)
      return [BOUNDS.maxLongitude, latitudeA + ratio * (latitudeB - latitudeA)]
    },
  )
  points = clipAgainst(
    points,
    ([, latitude]) => latitude >= BOUNDS.minLatitude,
    ([longitudeA, latitudeA], [longitudeB, latitudeB]) => {
      const ratio = (BOUNDS.minLatitude - latitudeA) / (latitudeB - latitudeA)
      return [longitudeA + ratio * (longitudeB - longitudeA), BOUNDS.minLatitude]
    },
  )
  return clipAgainst(
    points,
    ([, latitude]) => latitude <= BOUNDS.maxLatitude,
    ([longitudeA, latitudeA], [longitudeB, latitudeB]) => {
      const ratio = (BOUNDS.maxLatitude - latitudeA) / (latitudeB - latitudeA)
      return [longitudeA + ratio * (longitudeB - longitudeA), BOUNDS.maxLatitude]
    },
  )
}

function project([longitude, latitude]) {
  return [
    HORIZONTAL_PADDING + (longitude - BOUNDS.minLongitude) * ANGULAR_SCALE,
    (BOUNDS.maxLatitude - latitude) * ANGULAR_SCALE,
  ]
}

function formatCoordinate(value) {
  return String(Number(value.toFixed(2)))
}

function ringToPath(ring) {
  if (ring.length < 3) return ''
  return ring.map((point, index) => {
    const [x, y] = project(point)
    return `${index === 0 ? 'M' : 'L'}${formatCoordinate(x)} ${formatCoordinate(y)}`
  }).join(' ') + ' Z'
}

function geometryPolygons(geometry) {
  if (geometry.type === 'Polygon') return [geometry.coordinates]
  if (geometry.type === 'MultiPolygon') return geometry.coordinates
  throw new Error(`Unsupported geometry type: ${geometry.type}`)
}

const sourceBytes = await download(SOURCE_URL)
assertEqual(createHash('sha256').update(sourceBytes).digest('hex'), EXPECTED_SHA256, 'SHA-256')
const source = JSON.parse(sourceBytes.toString('utf8'))
assertEqual(source.features.length, EXPECTED_FEATURE_COUNT, 'feature count')

const features = source.features.flatMap((feature, sourceIndex) => {
  const paths = []
  for (const polygon of geometryPolygons(feature.geometry)) {
    const outer = clipRing(polygon[0])
    if (outer.length < 3) continue
    paths.push(ringToPath(outer))
    for (const hole of polygon.slice(1)) {
      const clippedHole = clipRing(hole)
      if (clippedHole.length >= 3) paths.push(ringToPath(clippedHole))
    }
  }
  if (paths.length === 0) return []
  return [{
    id: `natural-earth-land-${String(sourceIndex + 1).padStart(4, '0')}`,
    path: paths.join(' '),
  }]
})

const generated = `/**
 * Generated by scripts/vendor-east-asia-reference-map.mjs.
 * Natural Earth 1:50m land geometry is public domain. It is clipped to East Asia,
 * projected into a fixed repository-owned viewBox, and contains no political borders.
 */
export interface EastAsiaReferenceFeature {
  readonly id: string
  readonly path: string
}

export const EAST_ASIA_REFERENCE_BASEMAP = ${JSON.stringify({
  id: 'east-asia-natural-earth-50m-land',
  label: 'East Asia physical land reference',
  viewBox: `0 0 ${VIEWBOX.width} ${VIEWBOX.height}`,
  width: VIEWBOX.width,
  height: VIEWBOX.height,
  bounds: BOUNDS,
  sourceRepository: 'nvkelso/natural-earth-vector',
  sourceCommit: SOURCE_COMMIT,
  sourceFile: 'geojson/ne_50m_land.geojson',
  sourceSha256: EXPECTED_SHA256,
  sourceScale: '1:50m',
  license: 'Public Domain',
  projection: 'Plate Carree with uniform angular scale, clipped to 65-157 E and 7-57 N',
  sourceFeatureCount: EXPECTED_FEATURE_COUNT,
  clippedFeatureCount: features.length,
  features,
}, null, 2)} as const satisfies {
  readonly id: string
  readonly label: string
  readonly viewBox: string
  readonly width: number
  readonly height: number
  readonly bounds: {
    readonly minLongitude: number
    readonly maxLongitude: number
    readonly minLatitude: number
    readonly maxLatitude: number
  }
  readonly sourceRepository: string
  readonly sourceCommit: string
  readonly sourceFile: string
  readonly sourceSha256: string
  readonly sourceScale: string
  readonly license: string
  readonly projection: string
  readonly sourceFeatureCount: number
  readonly clippedFeatureCount: number
  readonly features: readonly EastAsiaReferenceFeature[]
}
`

writeFileSync(outputPath, generated)
console.log(`Vendored ${features.length} East Asia land features from ${SOURCE_URL}`)
console.log(`Output: ${outputPath}`)
