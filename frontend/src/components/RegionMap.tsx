import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Region, RegionControl } from '../types/game'
import {
  MAP_MODE_PRESENTATIONS,
  VIEW_MODES,
  getColorLevel,
  getModeValueLabel,
  getTaxCollectedRanks,
  type ViewMode,
} from './regionMapUtils'
import { EAST_ASIA_REFERENCE_BASEMAP } from '../data/map/eastAsiaReferenceBasemap'
import { EAST_ASIA_POLITICAL_GRID } from '../data/map/eastAsiaPoliticalGrid'
import {
  administrativeDivisionForCountryId,
  administrativeDivisionForProvinceId,
  HISTORICAL_POLITY_PAINT_GROUPS,
  joinRegionsToGovernanceDivisions,
  polityForCountryId,
  polityForProvinceId,
  reprojectLegacyMapX,
  YUAN_ADMINISTRATIVE_DIVISIONS,
  type GovernanceDivisionStatus,
} from '../data/map/geography'
import { layoutOutlineLabels } from '../data/map/outlineLabelLayout'

const CONTROL_CLASSES: Record<RegionControl, string> = {
  '朝廷': 'control-court',
  '失控': 'control-lost',
  '沦陷': 'control-fallen',
}

const BASE_MAP_VIEW = {
  x: 0,
  y: 0,
  width: EAST_ASIA_REFERENCE_BASEMAP.width,
  height: EAST_ASIA_REFERENCE_BASEMAP.height,
} as const
const MIN_MAP_ZOOM = 1
const MAX_MAP_ZOOM = 3
const MAP_ZOOM_STEP = 1.25
const MAP_WHEEL_ZOOM_STEP = 1.15
const DEFAULT_MAP_CAMERA = {
  centerX: BASE_MAP_VIEW.x + BASE_MAP_VIEW.width / 2,
  centerY: BASE_MAP_VIEW.y + BASE_MAP_VIEW.height / 2,
  zoom: MIN_MAP_ZOOM,
} as const
const DEFAULT_MAP_VIEWPORT = {
  width: BASE_MAP_VIEW.width,
  height: BASE_MAP_VIEW.height,
} as const

const POLITY_LABEL_FONT_SIZES = {
  major: { base: 24, minimum: 13 },
  neighbor: { base: 17, minimum: 9 },
  local: { base: 10, minimum: 8 },
} as const
const POLITY_LABEL_LAYOUTS = layoutOutlineLabels(
  HISTORICAL_POLITY_PAINT_GROUPS.map((polity) => ({
    id: polity.id,
    text: polity.name,
    countryIds: polity.labelCountryIds ?? polity.countryIds,
    provinceIds: polity.labelProvinceIds ?? polity.provinceIds,
    preferred: { x: reprojectLegacyMapX(polity.x), y: polity.y },
    baseFontSize: POLITY_LABEL_FONT_SIZES[polity.prominence].base,
    minimumFontSize: POLITY_LABEL_FONT_SIZES[polity.prominence].minimum,
  })),
  [],
)
const ADMINISTRATIVE_LABEL_LAYOUTS = layoutOutlineLabels(
  YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => ({
    id: division.id,
    text: division.name,
    countryIds: division.countryIds,
    provinceIds: division.provinceIds,
    preferred: { x: reprojectLegacyMapX(division.label.x), y: division.label.y },
    baseFontSize: division.kind === 'central' ? 13 : 12,
    minimumFontSize: 8,
  })),
  POLITY_LABEL_LAYOUTS.map((layout) => layout.rect),
)
const polityLabelLayoutById = new Map(POLITY_LABEL_LAYOUTS.map((layout) => [layout.id, layout]))
const administrativeLabelLayoutById = new Map(ADMINISTRATIVE_LABEL_LAYOUTS.map((layout) => [layout.id, layout]))

interface MapView {
  x: number
  y: number
  width: number
  height: number
}

interface MapCamera {
  centerX: number
  centerY: number
  zoom: number
}

interface MapViewport {
  width: number
  height: number
}

interface MapDragState {
  pointerId: number
  clientX: number
  clientY: number
  camera: MapCamera
  view: MapView
}

type MapControlPanel = 'map' | 'camera'

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function formatViewBox(view: MapView): string {
  return [view.x, view.y, view.width, view.height]
    .map((value) => String(Number(value.toFixed(2))))
    .join(' ')
}

function baseMapViewSize(viewport: MapViewport): Pick<MapView, 'width' | 'height'> {
  const viewportAspect = viewport.width / viewport.height
  const mapAspect = BASE_MAP_VIEW.width / BASE_MAP_VIEW.height
  if (!Number.isFinite(viewportAspect) || viewportAspect <= 0) {
    return { width: BASE_MAP_VIEW.width, height: BASE_MAP_VIEW.height }
  }
  if (viewportAspect >= mapAspect) {
    return { width: BASE_MAP_VIEW.width, height: BASE_MAP_VIEW.width / viewportAspect }
  }
  return { width: BASE_MAP_VIEW.height * viewportAspect, height: BASE_MAP_VIEW.height }
}

function constrainMapCamera(camera: MapCamera, viewport: MapViewport): MapCamera {
  const zoom = clamp(camera.zoom, MIN_MAP_ZOOM, MAX_MAP_ZOOM)
  const baseSize = baseMapViewSize(viewport)
  const width = baseSize.width / zoom
  const height = baseSize.height / zoom
  return {
    centerX: clamp(camera.centerX, BASE_MAP_VIEW.x + width / 2, BASE_MAP_VIEW.x + BASE_MAP_VIEW.width - width / 2),
    centerY: clamp(camera.centerY, BASE_MAP_VIEW.y + height / 2, BASE_MAP_VIEW.y + BASE_MAP_VIEW.height - height / 2),
    zoom,
  }
}

function mapViewForCamera(camera: MapCamera, viewport: MapViewport): MapView {
  const constrained = constrainMapCamera(camera, viewport)
  const baseSize = baseMapViewSize(viewport)
  const width = baseSize.width / constrained.zoom
  const height = baseSize.height / constrained.zoom
  return {
    x: constrained.centerX - width / 2,
    y: constrained.centerY - height / 2,
    width,
    height,
  }
}

interface Props {
  regions: Region[]
  highlightDivisionId?: string
  toasts?: string[]
  onDivisionClick?: (division: GovernanceDivisionStatus) => void
  railControls?: ReactNode
}

export default function RegionMap({ regions, highlightDivisionId, toasts, onDivisionClick, railControls }: Props) {
  const [hoveredDivisionId, setHoveredDivisionId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('standard')
  const [mapCamera, setMapCamera] = useState<MapCamera>(DEFAULT_MAP_CAMERA)
  const [mapViewport, setMapViewport] = useState<MapViewport>(DEFAULT_MAP_VIEWPORT)
  const [isDraggingMap, setIsDraggingMap] = useState(false)
  const [activeControlPanel, setActiveControlPanel] = useState<MapControlPanel | null>(null)
  const mapSurface = useRef<HTMLDivElement | null>(null)
  const mapSvg = useRef<SVGSVGElement | null>(null)
  const mapDrag = useRef<MapDragState | null>(null)
  const mapPanelTrigger = useRef<HTMLButtonElement | null>(null)
  const cameraPanelTrigger = useRef<HTMLButtonElement | null>(null)
  const joined = useMemo(() => joinRegionsToGovernanceDivisions(regions), [regions])
  const mappedRegions = useMemo(() => joined.divisions.flatMap((division) => division.region ? [division.region] : []), [joined])
  const taxRanks = useMemo(() => viewMode === 'tax_collected' ? getTaxCollectedRanks(mappedRegions) : null, [viewMode, mappedRegions])
  const presentation = MAP_MODE_PRESENTATIONS[viewMode]
  const mapView = mapViewForCamera(mapCamera, mapViewport)
  const defaultMapView = mapViewForCamera(DEFAULT_MAP_CAMERA, mapViewport)
  const mapZoom = mapCamera.zoom
  const mapIsAtDefaultView = Math.abs(mapView.x - defaultMapView.x) < 0.01
    && Math.abs(mapView.y - defaultMapView.y) < 0.01
    && Math.abs(mapZoom - MIN_MAP_ZOOM) < 0.001

  useLayoutEffect(() => {
    const surface = mapSurface.current
    if (!surface) return

    const updateViewport = (width: number, height: number) => {
      if (width <= 0 || height <= 0) return
      setMapViewport((current) => (
        Math.abs(current.width - width) < 0.5 && Math.abs(current.height - height) < 0.5
          ? current
          : { width, height }
      ))
    }

    const bounds = surface.getBoundingClientRect()
    updateViewport(bounds.width, bounds.height)
    if (typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver(([entry]) => {
      if (entry) updateViewport(entry.contentRect.width, entry.contentRect.height)
    })
    observer.observe(surface)
    return () => observer.disconnect()
  }, [])

  function zoomBy(factor: number) {
    setMapCamera((current) => {
      const currentView = mapViewForCamera(current, mapViewport)
      return constrainMapCamera({
        centerX: currentView.x + currentView.width / 2,
        centerY: currentView.y + currentView.height / 2,
        zoom: current.zoom * factor,
      }, mapViewport)
    })
  }

  const handleMapWheel = useCallback((event: WheelEvent) => {
    event.preventDefault()
    const svg = event.currentTarget
    if (!(svg instanceof SVGSVGElement)) return
    const svgBounds = svg.getBoundingClientRect()
    if (svgBounds.width <= 0 || svgBounds.height <= 0) return
    const focusRatioX = clamp((event.clientX - svgBounds.left) / svgBounds.width, 0, 1)
    const focusRatioY = clamp((event.clientY - svgBounds.top) / svgBounds.height, 0, 1)
    setMapCamera((current) => {
      const currentView = mapViewForCamera(current, mapViewport)
      const focusX = currentView.x + focusRatioX * currentView.width
      const focusY = currentView.y + focusRatioY * currentView.height
      const zoom = clamp(
        current.zoom * (event.deltaY < 0 ? MAP_WHEEL_ZOOM_STEP : 1 / MAP_WHEEL_ZOOM_STEP),
        MIN_MAP_ZOOM,
        MAX_MAP_ZOOM,
      )
      const baseSize = baseMapViewSize(mapViewport)
      const nextWidth = baseSize.width / zoom
      const nextHeight = baseSize.height / zoom
      return constrainMapCamera({
        centerX: focusX + (0.5 - focusRatioX) * nextWidth,
        centerY: focusY + (0.5 - focusRatioY) * nextHeight,
        zoom,
      }, mapViewport)
    })
  }, [mapViewport])

  useEffect(() => {
    const svg = mapSvg.current
    if (!svg) return
    svg.addEventListener('wheel', handleMapWheel, { passive: false })
    return () => svg.removeEventListener('wheel', handleMapWheel)
  }, [handleMapWheel])

  useEffect(() => {
    if (!activeControlPanel) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const trigger = activeControlPanel === 'map' ? mapPanelTrigger.current : cameraPanelTrigger.current
      trigger?.focus()
      setActiveControlPanel(null)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [activeControlPanel])

  function toggleControlPanel(panel: MapControlPanel) {
    setActiveControlPanel((current) => current === panel ? null : panel)
  }

  function closeControlPanel() {
    const trigger = activeControlPanel === 'map' ? mapPanelTrigger.current : cameraPanelTrigger.current
    trigger?.focus()
    setActiveControlPanel(null)
  }

  function handleMapPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return
    if (event.target instanceof Element && event.target.closest('[data-governance-division-id]')) return
    mapDrag.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      camera: {
        centerX: mapView.x + mapView.width / 2,
        centerY: mapView.y + mapView.height / 2,
        zoom: mapZoom,
      },
      view: mapView,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setIsDraggingMap(true)
  }

  function handleMapPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const drag = mapDrag.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width <= 0 || bounds.height <= 0) return
    setMapCamera(constrainMapCamera({
      centerX: drag.camera.centerX - (event.clientX - drag.clientX) * drag.view.width / bounds.width,
      centerY: drag.camera.centerY - (event.clientY - drag.clientY) * drag.view.height / bounds.height,
      zoom: drag.camera.zoom,
    }, mapViewport))
  }

  function endMapDrag(event: ReactPointerEvent<SVGSVGElement>) {
    if (mapDrag.current?.pointerId !== event.pointerId) return
    mapDrag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setIsDraggingMap(false)
  }

  function resolveLevel(region: Region): 'high' | 'mid' | 'low' {
    return viewMode === 'tax_collected' ? taxRanks?.get(region.name) ?? 'low' : getColorLevel(viewMode, region)
  }

  function renderGovernanceDivision(item: GovernanceDivisionStatus) {
    const { division, region, sourceRegions } = item
    const highlighted = highlightDivisionId === division.id
    const level = region ? resolveLevel(region) : 'low'
    const controlClass = region ? CONTROL_CLASSES[region.control] : 'control-missing'
    const hasThreat = sourceRegions.some((sourceRegion) => sourceRegion.threat !== 'none')
    const hovered = hoveredDivisionId === division.id
    const label = region
      ? `${division.name}，所辖治理地区：${sourceRegions.map((sourceRegion) => sourceRegion.name).join('、')}，控制：${region.control}，${presentation.title}：${getModeValueLabel(viewMode, region)}`
      : `${division.name}，尚未接入治理数据`
    return (
      <g
        key={division.id}
        className={`map-governance-division stab-${level} ${controlClass}${highlighted ? ' selected' : ''}${hovered ? ' hovered' : ''}${hasThreat ? ' has-threat' : ''}${item.state === 'missing' ? ' missing' : ''}`}
        data-governance-division-id={division.id}
        data-governance-division-name={division.name}
        data-source-region-names={sourceRegions.map((sourceRegion) => sourceRegion.name).join(' ')}
        data-state={item.state}
        data-level={level}
        data-control={region?.control ?? 'missing'}
        data-threat={region?.threat ?? 'unknown'}
        role={region ? 'button' : 'img'}
        tabIndex={region ? 0 : undefined}
        aria-disabled={!region || undefined}
        aria-label={label}
        onMouseEnter={() => region && setHoveredDivisionId(division.id)}
        onMouseLeave={() => setHoveredDivisionId(null)}
        onFocus={() => region && setHoveredDivisionId(division.id)}
        onBlur={() => setHoveredDivisionId(null)}
        onClick={() => region && onDivisionClick?.(item)}
        onKeyDown={(event) => {
          if (!region || (event.key !== 'Enter' && event.key !== ' ')) return
          event.preventDefault()
          onDivisionClick?.(item)
        }}
      >
        <title>{label}</title>
        {division.countryIds.map((countryId) => {
          const country = EAST_ASIA_POLITICAL_GRID.countries.find((candidate) => candidate.id === countryId)
          return country ? <path key={`country-${countryId}`} data-country-id={countryId} d={country.path} fillRule="evenodd" /> : null
        })}
        {division.provinceIds.map((provinceId) => {
          const province = EAST_ASIA_POLITICAL_GRID.chinaProvinces.find((candidate) => candidate.id === provinceId)
          return province ? <path key={`province-${provinceId}`} data-province-id={provinceId} d={province.path} fillRule="evenodd" /> : null
        })}
      </g>
    )
  }

  return (
    <div className="region-map-container">
      <div ref={mapSurface} className={`region-map geographic-map mode-${viewMode}`} data-view-mode={viewMode}>
        <svg
          ref={mapSvg}
          viewBox={formatViewBox(mapView)}
          aria-labelledby="region-map-title region-map-description"
          preserveAspectRatio="xMidYMid meet"
          className={`is-pannable${mapZoom > MIN_MAP_ZOOM ? ' is-zoomed' : ''}${isDraggingMap ? ' is-dragging' : ''}`}
          data-map-zoom={mapZoom.toFixed(2)}
          onPointerDown={handleMapPointerDown}
          onPointerMove={handleMapPointerMove}
          onPointerUp={endMapDrag}
          onPointerCancel={endMapDrag}
        >
          <title id="region-map-title">元末东亚政区与行政区治理</title>
          <desc id="region-map-description">东亚国家与省级地理轮廓按十四世纪中叶政权和元代行政区着色，历史行政区轮廓同时承载治理数据、地区检查和施政交互。</desc>
          <rect x="0" y="0" width={EAST_ASIA_REFERENCE_BASEMAP.width} height={EAST_ASIA_REFERENCE_BASEMAP.height} className="map-water" aria-hidden="true" />
          <g className="map-atmosphere" aria-hidden="true" pointerEvents="none">
            <image
              className="map-atmosphere-paper-water"
              href="/map/atmosphere/v1/paper-water-wash-v1.webp"
              x="0"
              y="0"
              width={EAST_ASIA_REFERENCE_BASEMAP.width}
              height={EAST_ASIA_REFERENCE_BASEMAP.height}
              preserveAspectRatio="xMidYMid slice"
            />
            <image
              className="map-atmosphere-terrain"
              href="/map/atmosphere/v1/terrain-drybrush-v1.webp"
              x="0"
              y="0"
              width={EAST_ASIA_REFERENCE_BASEMAP.width}
              height={EAST_ASIA_REFERENCE_BASEMAP.height}
              preserveAspectRatio="xMidYMid slice"
            />
          </g>
          <defs aria-hidden="true">
            <pattern id="map-missing-pattern" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="10" height="10" className="map-missing-pattern-bg" />
              <line x1="0" y1="0" x2="0" y2="10" className="map-missing-pattern-line" />
            </pattern>
          </defs>
          <g className="east-asia-reference-basemap" aria-hidden="true">
            {EAST_ASIA_REFERENCE_BASEMAP.features.map((land) => (
              <path key={land.id} data-reference-id={land.id} d={land.path} fillRule="evenodd" />
            ))}
          </g>
          <g className="east-asia-country-grid" aria-hidden="true">
            {EAST_ASIA_POLITICAL_GRID.countries.map((country) => {
              const division = administrativeDivisionForCountryId(country.id)
              const polity = polityForCountryId(country.id)
              const paint = division ?? polity
              return (
                <path
                  key={country.id}
                  data-country-id={country.id}
                  data-admin-division-id={division?.id}
                  data-polity-paint-id={polity?.id}
                  className={paint ? `paint-tone-${paint.tone}` : undefined}
                  d={country.path}
                  fillRule="evenodd"
                />
              )
            })}
          </g>
          <g className="china-historical-admin-grid" aria-hidden="true">
            {EAST_ASIA_POLITICAL_GRID.chinaProvinces.map((province) => {
              const division = administrativeDivisionForProvinceId(province.id)
              const polity = polityForProvinceId(province.id)
              const paint = division ?? polity
              return (
                <path
                  key={province.id}
                  data-province-paint-id={province.id}
                  data-admin-division-id={division?.id}
                  data-polity-paint-id={polity?.id}
                  className={paint ? `paint-tone-${paint.tone}` : undefined}
                  d={province.path}
                  fillRule="evenodd"
                />
              )
            })}
          </g>
          <g className="east-asia-coastline" aria-hidden="true">
            {EAST_ASIA_REFERENCE_BASEMAP.features.map((land) => (
              <path key={land.id} d={land.path} fillRule="evenodd" />
            ))}
          </g>
          <g className="yuan-governance-divisions" aria-label="元代行政区治理图层">
            {joined.divisions.map(renderGovernanceDivision)}
          </g>
          <g className="yuan-administrative-labels" aria-hidden="true">
            {YUAN_ADMINISTRATIVE_DIVISIONS.map((division) => {
              const layout = administrativeLabelLayoutById.get(division.id)
              return (
                <text
                  key={division.id}
                  x={layout?.x ?? reprojectLegacyMapX(division.label.x)}
                  y={layout?.y ?? division.label.y}
                  textAnchor="middle"
                  className={`admin-kind-${division.kind}`}
                  data-label-fit={layout?.fit ?? 'fallback'}
                  data-outline-ids={layout?.outlineIds.join(' ') ?? ''}
                  style={layout ? { fontSize: `${layout.fontSize}px` } : undefined}
                >
                  {division.name}
                </text>
              )
            })}
          </g>
          <g className="historical-polity-labels" aria-label="十四世纪中叶周边政权方位">
            {HISTORICAL_POLITY_PAINT_GROUPS.map((polity) => {
              const layout = polityLabelLayoutById.get(polity.id)
              return (
                <g
                  key={polity.id}
                  className={`historical-polity-label prominence-${polity.prominence}`}
                  data-label-role={polity.prominence === 'local' ? 'local-context' : 'polity'}
                  data-polity-id={polity.id}
                >
                  <text
                    x={layout?.x ?? reprojectLegacyMapX(polity.x)}
                    y={layout?.y ?? polity.y}
                    textAnchor="middle"
                    data-label-fit={layout?.fit ?? 'fallback'}
                    data-outline-ids={layout?.outlineIds.join(' ') ?? ''}
                    style={layout ? { fontSize: `${layout.fontSize}px` } : undefined}
                  >
                    {polity.name}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>
        {(joined.unmapped.length > 0 || joined.duplicates.length > 0) && (
          <div className="map-data-warning" role="status" aria-label="地图数据告警">
            {joined.unmapped.length > 0 && <span className="map-warning-item warning-unmapped" data-warning-kind="unmapped">未映射：{joined.unmapped.map((region) => region.name).join('、')}</span>}
            {joined.duplicates.length > 0 && <span className="map-warning-item warning-duplicate" data-warning-kind="duplicate">重复：{joined.duplicates.map((region) => region.name).join('、')}</span>}
          </div>
        )}
        {railControls && (
          <nav className="primary-command-strip" aria-label="朝廷管理">
            {railControls}
          </nav>
        )}
        <p className="map-accuracy-note">约 14 世纪中叶历史归组；现代省界仅用于拼合历史行政区。点击有治理数据的行政区轮廓可查看汇总状态并施政；淡色斜纹区尚未接入本剧本数据。</p>
        <AnimatePresence>{toasts?.map((msg) => <motion.div key={msg} className="map-toast" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>{msg}</motion.div>)}</AnimatePresence>
      </div>
      <aside className="view-switcher" aria-label="地图控制" data-expanded-panel={activeControlPanel ?? 'none'}>
        {activeControlPanel && (
          <section
            id={`map-${activeControlPanel}-control-panel`}
            className={`map-control-panel panel-${activeControlPanel}`}
            role="region"
            aria-label={activeControlPanel === 'map' ? '地图模式面板' : '地图镜头面板'}
          >
            <header className="map-control-panel-header">
              <div>
                <span>地图工具</span>
                <h2>{activeControlPanel === 'map' ? '地图模式' : '地图镜头'}</h2>
              </div>
              <button
                type="button"
                className="map-control-panel-close"
                aria-label={`收起${activeControlPanel === 'map' ? '地图模式' : '地图镜头'}面板`}
                title="收起面板"
                onClick={closeControlPanel}
              >
                ×
              </button>
            </header>

            {activeControlPanel === 'map' ? (
              <div className="map-control-panel-body">
                <div className="map-view-controls" role="group" aria-label="地图模式">
                  {VIEW_MODES.map((mode) => {
                    const label = MAP_MODE_PRESENTATIONS[mode].label
                    return (
                      <button
                        key={mode}
                        type="button"
                        className={`rail-text-button view-btn mode-${mode}${viewMode === mode ? ' active' : ''}`}
                        aria-label={label}
                        title={`${label}地图模式`}
                        aria-pressed={viewMode === mode}
                        onClick={() => setViewMode(mode)}
                      >
                        <span className="rail-button-label">{label}</span>
                      </button>
                    )
                  })}
                </div>
                <section className="map-mode-context" aria-live="polite" aria-label={`${presentation.title}图例`}>
                  <div className="map-mode-heading">
                    <h3>{presentation.title}</h3>
                    <span>{presentation.label}</span>
                  </div>
                  <p>{presentation.description}</p>
                  <div className="map-legend">
                    {presentation.legend.map((entry) => (
                      <span key={entry.level} data-legend-level={entry.level}><i className={`legend-swatch legend-${entry.level}`} />{entry.label}<small>{entry.range}</small></span>
                    ))}
                  </div>
                  <div className="map-boundary-legend" aria-label="地图图层图例">
                    <span><i className="boundary-sample polity-boundary-sample" />周边政权</span>
                    <span><i className="boundary-sample admin-boundary-sample" />元代政区</span>
                    <span><i className="governance-division-sample" />可治理行政区</span>
                  </div>
                </section>
              </div>
            ) : (
              <div className="map-control-panel-body">
                <div className="map-zoom-controls" role="group" aria-label="地图镜头">
                  <div className="map-zoom-heading">
                    <span>当前缩放</span>
                    <output className="map-zoom-level" aria-label="当前地图缩放比例" aria-live="polite">{Math.round(mapZoom * 100)}%</output>
                  </div>
                  <button className="rail-text-button" type="button" aria-label="缩小地图" title="缩小地图" disabled={mapZoom <= MIN_MAP_ZOOM} onClick={() => zoomBy(1 / MAP_ZOOM_STEP)}>
                    <span className="rail-button-label">缩小</span>
                  </button>
                  <button className="rail-text-button" type="button" aria-label="放大地图" title="放大地图" disabled={mapZoom >= MAX_MAP_ZOOM} onClick={() => zoomBy(MAP_ZOOM_STEP)}>
                    <span className="rail-button-label">放大</span>
                  </button>
                  <button className="rail-text-button map-reset-view" type="button" aria-label="重置地图视图" title="重置地图视图" disabled={mapIsAtDefaultView} onClick={() => setMapCamera(DEFAULT_MAP_CAMERA)}>
                    <span className="rail-button-label">复位</span>
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        <nav className="map-control-dock" aria-label="地图工具入口">
          <button
            ref={mapPanelTrigger}
            type="button"
            className={`map-dock-button${activeControlPanel === 'map' ? ' active' : ''}`}
            aria-label="地图模式"
            aria-expanded={activeControlPanel === 'map'}
            aria-controls="map-map-control-panel"
            title="地图模式"
            onClick={() => toggleControlPanel('map')}
          >
            地图
          </button>
          <button
            ref={cameraPanelTrigger}
            type="button"
            className={`map-dock-button camera-dock-button${activeControlPanel === 'camera' ? ' active' : ''}`}
            aria-label="地图镜头"
            aria-expanded={activeControlPanel === 'camera'}
            aria-controls="map-camera-control-panel"
            title="地图镜头"
            onClick={() => toggleControlPanel('camera')}
          >
            镜头
          </button>
        </nav>
      </aside>
    </div>
  )
}
