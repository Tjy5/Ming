import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { get } from 'node:https'
import { fileURLToPath } from 'node:url'

const SOURCE_COMMIT = 'ca96624a56bd078437bca8184e78163e5039ad19'
const SOURCES = {
  countries: {
    file: 'geojson/ne_50m_admin_0_countries.geojson',
    sha256: '3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb',
    featureCount: 242,
  },
  provinces: {
    file: 'geojson/ne_50m_admin_1_states_provinces.geojson',
    sha256: '69a0e06e640b2d505858ae1cb63034e4677f3000b35a98e16312932b98c426b9',
    featureCount: 294,
  },
}
const VIEWBOX = { width: 1200, height: 650 }
const BOUNDS = { minLongitude: 65, maxLongitude: 157, minLatitude: 7, maxLatitude: 57 }
const ANGULAR_SCALE = VIEWBOX.height / (BOUNDS.maxLatitude - BOUNDS.minLatitude)
const HORIZONTAL_PADDING = (VIEWBOX.width - (BOUNDS.maxLongitude - BOUNDS.minLongitude) * ANGULAR_SCALE) / 2
const outputPath = fileURLToPath(new URL('../src/data/map/eastAsiaPoliticalGrid.ts', import.meta.url))

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
  return String(Number(value.toFixed(1)))
}

function squaredSegmentDistance(point, start, end) {
  let x = start[0]
  let y = start[1]
  let dx = end[0] - x
  let dy = end[1] - y
  if (dx !== 0 || dy !== 0) {
    const ratio = ((point[0] - x) * dx + (point[1] - y) * dy) / (dx * dx + dy * dy)
    if (ratio > 1) {
      x = end[0]
      y = end[1]
    } else if (ratio > 0) {
      x += dx * ratio
      y += dy * ratio
    }
  }
  dx = point[0] - x
  dy = point[1] - y
  return dx * dx + dy * dy
}

function simplifyLine(points, tolerance) {
  if (points.length <= 2) return points
  const markers = new Uint8Array(points.length)
  const stack = [[0, points.length - 1]]
  const squaredTolerance = tolerance * tolerance
  markers[0] = 1
  markers[points.length - 1] = 1
  while (stack.length > 0) {
    const [first, last] = stack.pop()
    let index = -1
    let maxDistance = squaredTolerance
    for (let cursor = first + 1; cursor < last; cursor += 1) {
      const distance = squaredSegmentDistance(points[cursor], points[first], points[last])
      if (distance > maxDistance) {
        index = cursor
        maxDistance = distance
      }
    }
    if (index === -1) continue
    markers[index] = 1
    stack.push([first, index], [index, last])
  }
  return points.filter((_, index) => markers[index] === 1)
}

function ringToPath(ring) {
  if (ring.length < 3) return ''
  const projected = simplifyLine(ring.map(project), 0.65)
  if (projected.length < 3) return ''
  return projected.map(([x, y], index) => {
    return `${index === 0 ? 'M' : 'L'}${formatCoordinate(x)} ${formatCoordinate(y)}`
  }).join(' ') + ' Z'
}

function geometryPolygons(geometry) {
  if (geometry.type === 'Polygon') return [geometry.coordinates]
  if (geometry.type === 'MultiPolygon') return geometry.coordinates
  throw new Error(`Unsupported geometry type: ${geometry.type}`)
}

function featurePath(feature) {
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
  return paths.join(' ')
}

async function readSource(source) {
  const url = `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/${SOURCE_COMMIT}/${source.file}`
  const bytes = await download(url)
  assertEqual(createHash('sha256').update(bytes).digest('hex'), source.sha256, `${source.file} SHA-256`)
  const geoJson = JSON.parse(bytes.toString('utf8'))
  assertEqual(geoJson.features.length, source.featureCount, `${source.file} feature count`)
  return geoJson
}

const [countrySource, provinceSource] = await Promise.all([
  readSource(SOURCES.countries),
  readSource(SOURCES.provinces),
])

const countries = countrySource.features.flatMap((feature) => {
  const path = featurePath(feature)
  if (!path) return []
  const nameZh = feature.properties.NAME_ZH
  return [{
    id: feature.properties.ADM0_A3,
    name: feature.properties.NAME_EN,
    nameZh: nameZh && nameZh !== '-99' ? nameZh : feature.properties.NAME_EN,
    path,
  }]
})

const chinaProvinces = provinceSource.features
  .filter((feature) => feature.properties.adm0_a3 === 'CHN')
  .flatMap((feature) => {
    const path = featurePath(feature)
    if (!path) return []
    return [{
      id: feature.properties.iso_3166_2,
      name: feature.properties.name,
      nameZh: feature.properties.name_zh,
      path,
    }]
  })

const generated = `/**
 * Generated by scripts/vendor-east-asia-political-grid.mjs.
 * Natural Earth country and China province geometry is public domain. These
 * present-day units are a paint grid only; displayed labels and groupings are historical.
 */
export interface PoliticalGridFeature {
  readonly id: string
  readonly name: string
  readonly nameZh: string
  readonly path: string
}

export const EAST_ASIA_POLITICAL_GRID = ${JSON.stringify({
  id: 'east-asia-natural-earth-political-paint-grid',
  viewBox: `0 0 ${VIEWBOX.width} ${VIEWBOX.height}`,
  sourceRepository: 'nvkelso/natural-earth-vector',
  sourceCommit: SOURCE_COMMIT,
  license: 'Public Domain',
  projection: 'Plate Carree with uniform angular scale, clipped to 65-157 E and 7-57 N',
  sources: {
    countries: { ...SOURCES.countries, clippedFeatureCount: countries.length },
    provinces: { ...SOURCES.provinces, selectedFeatureCount: chinaProvinces.length },
  },
  countries,
  chinaProvinces,
}, null, 2)} as const satisfies {
  readonly id: string
  readonly viewBox: string
  readonly sourceRepository: string
  readonly sourceCommit: string
  readonly license: string
  readonly projection: string
  readonly sources: {
    readonly countries: { readonly file: string; readonly sha256: string; readonly featureCount: number; readonly clippedFeatureCount: number }
    readonly provinces: { readonly file: string; readonly sha256: string; readonly featureCount: number; readonly selectedFeatureCount: number }
  }
  readonly countries: readonly PoliticalGridFeature[]
  readonly chinaProvinces: readonly PoliticalGridFeature[]
}
`

writeFileSync(outputPath, generated)
console.log(`Vendored ${countries.length} country and ${chinaProvinces.length} China province paint units`)
console.log(`Output: ${outputPath}`)
