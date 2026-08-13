import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Region, RegionControl } from '../types/game'
import {
  getBarPercent,
  getColorLevel,
  getTaxCollectedRanks,
  getTooltipText,
  levelColor,
  type ViewMode,
} from './regionMapUtils'
import { joinRegionsToMap, MAP_LANDMASS_PATH, MAP_RIVERS, MAP_VIEWBOX, type MapRegionStatus } from '../data/map/geography'

const VIEW_LABELS: Record<ViewMode, string> = {
  standard: '标准', disaster: '灾情', morale: '民心', rebellion: '动乱', tax_rate: '税率', tax_collected: '赋税',
}
const VIEW_MODES: ViewMode[] = ['standard', 'disaster', 'morale', 'rebellion', 'tax_rate', 'tax_collected']
const CONTROL_BG: Partial<Record<RegionControl, string>> = { '失控': 'rgba(229,184,41,0.18)', '沦陷': 'rgba(224,64,64,0.2)' }

interface Props {
  regions: Region[]
  highlightRegion?: string
  toasts?: string[]
  onRegionClick?: (region: Region) => void
}

function featureViewport(feature: MapRegionStatus) {
  const pathNumbers = feature.feature.path.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? []
  const xs = pathNumbers.filter((_, index) => index % 2 === 0)
  const ys = pathNumbers.filter((_, index) => index % 2 === 1)
  const x = Math.min(...xs, feature.feature.label.x) - 8
  const y = Math.min(...ys, feature.feature.label.y) - 8
  const width = Math.max(...xs, feature.feature.label.x) - x + 16
  const height = Math.max(...ys, feature.feature.label.y) - y + 16
  return { x, y, width, height }
}

export default function RegionMap({ regions, highlightRegion, toasts, onRegionClick }: Props) {
  const [tooltip, setTooltip] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('standard')
  const joined = useMemo(() => joinRegionsToMap(regions), [regions])
  const taxRanks = useMemo(() => viewMode === 'tax_collected' ? getTaxCollectedRanks(regions) : null, [viewMode, regions])

  function resolveLevel(region: Region): 'high' | 'mid' | 'low' {
    return viewMode === 'tax_collected' ? taxRanks?.get(region.name) ?? 'low' : getColorLevel(viewMode, region)
  }

  function renderFeature(item: MapRegionStatus) {
    const { feature, region } = item
    const highlighted = !!region && highlightRegion === region.name
    const level = region ? resolveLevel(region) : 'low'
    const viewport = featureViewport(item)
    const label = region
      ? `${region.name}，控制：${region.control}，稳定度：${region.stability}`
      : `${feature.displayName}，尚未接入治理数据`
    return (
      <g key={feature.mapRegionId} className={`map-feature${highlighted ? ' selected' : ''}${item.state === 'missing' ? ' missing' : ''}`}>
        <path
          d={feature.path}
          className={`map-feature-shape stab-${level}`}
          fill={region ? (CONTROL_BG[region.control] ?? 'var(--bg-card)') : 'rgba(43,38,32,0.05)'}
          stroke={region ? levelColor(level) : 'var(--gray)'}
          aria-hidden="true"
        />
        <foreignObject {...viewport}>
          <button
            type="button"
            className={`region-block map-region-button stab-${level}${highlighted ? ' highlight-pulse' : ''}`}
            data-region-name={region?.name ?? feature.displayName}
            aria-pressed={highlighted}
            aria-label={label}
            disabled={!region}
            onClick={() => {
              if (!region) return
              setTooltip(tooltip === region.name ? null : region.name)
              onRegionClick?.(region)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                if (region) onRegionClick?.(region)
              }
            }}
            style={{ backgroundColor: region ? CONTROL_BG[region.control] : undefined }}
          >
            <span className="region-name">{feature.displayName}</span>
            {region ? (
              <>
                <span className="region-info"><span className="region-control">{region.control}</span>{region.threat !== 'none' && <motion.span className="region-threat" initial={{ scale: 0 }} animate={{ scale: 1 }}>{region.threat}</motion.span>}</span>
                <span className="region-stab-bar"><span className="region-stab-fill" style={{ width: `${getBarPercent(viewMode, region, regions)}%`, backgroundColor: levelColor(level) }} /></span>
              </>
            ) : <span className="region-info map-missing-label">未接入</span>}
            {tooltip === region?.name && region && <span className="region-tooltip">{getTooltipText(viewMode, region)}</span>}
          </button>
        </foreignObject>
      </g>
    )
  }

  return (
    <div className="region-map-container">
      <div className="region-map geographic-map">
        <svg viewBox={MAP_VIEWBOX} aria-labelledby="region-map-title" preserveAspectRatio="xMidYMid meet">
          <title id="region-map-title">八地理区域治理地图</title>
          <rect x="0" y="0" width="1000" height="620" className="map-water" aria-hidden="true" />
          <path d={MAP_LANDMASS_PATH} className="map-landmass" aria-hidden="true" />
          <g className="map-rivers" aria-hidden="true">
            {MAP_RIVERS.map((river) => <path key={river} d={river} />)}
          </g>
          {joined.features.map(renderFeature)}
        </svg>
        {(joined.unmapped.length > 0 || joined.duplicates.length > 0) && (
          <div className="map-data-warning" role="status">
            {joined.unmapped.length > 0 && `未映射地区：${joined.unmapped.map((region) => region.name).join('、')}`}
            {joined.duplicates.length > 0 && ` 重复地区：${joined.duplicates.map((region) => region.name).join('、')}`}
          </div>
        )}
        <div className="map-legend" aria-label="地图图例">
          <span><i className="legend-swatch legend-high" />高</span><span><i className="legend-swatch legend-mid" />中</span><span><i className="legend-swatch legend-low" />低</span>
        </div>
        <AnimatePresence>{toasts?.map((msg) => <motion.div key={msg} className="map-toast" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>{msg}</motion.div>)}</AnimatePresence>
      </div>
      <div className="view-switcher" role="group" aria-label="地图视图">
        {VIEW_MODES.map((mode) => <button key={mode} type="button" className={`view-btn${viewMode === mode ? ' active' : ''}`} aria-pressed={viewMode === mode} onClick={() => setViewMode(mode)}>{VIEW_LABELS[mode]}</button>)}
      </div>
    </div>
  )
}
