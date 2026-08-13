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
import { CHINA_REFERENCE_BASEMAP } from '../data/map/chinaReferenceBasemap'
import { joinRegionsToMap, MAP_VIEWBOX, type MapRegionStatus } from '../data/map/geography'

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
    const { anchor, label: viewport } = feature
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
        <path
          d={`M${anchor.x} ${anchor.y} L${viewport.x + viewport.width / 2} ${viewport.y + viewport.height / 2}`}
          className="map-feature-leader"
          aria-hidden="true"
        />
        <circle cx={anchor.x} cy={anchor.y} r="4" className="map-feature-anchor" aria-hidden="true" />
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
        <svg viewBox={MAP_VIEWBOX} aria-labelledby="region-map-title region-map-description" preserveAspectRatio="xMidYMid meet">
          <title id="region-map-title">现代中国地理参考与元末八战略区域</title>
          <desc id="region-map-description">现代省域轮廓仅作方位参照，彩色范围为可操作的元末战略区域。</desc>
          <rect x="0" y="0" width="774" height="569" className="map-water" aria-hidden="true" />
          <g className="china-reference-basemap" aria-hidden="true">
            {CHINA_REFERENCE_BASEMAP.features.map((province) => (
              <path key={province.id} data-reference-id={province.id} d={province.path} />
            ))}
          </g>
          <g className="yuanming-strategic-overlay">
            {joined.features.map(renderFeature)}
          </g>
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
        <p className="map-accuracy-note">现代地理参考底图；区域为元末战略范围，不等同于现代省界或精确的 1368 行政疆界。</p>
        <AnimatePresence>{toasts?.map((msg) => <motion.div key={msg} className="map-toast" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>{msg}</motion.div>)}</AnimatePresence>
      </div>
      <div className="view-switcher" role="group" aria-label="地图视图">
        {VIEW_MODES.map((mode) => <button key={mode} type="button" className={`view-btn${viewMode === mode ? ' active' : ''}`} aria-pressed={viewMode === mode} onClick={() => setViewMode(mode)}>{VIEW_LABELS[mode]}</button>)}
      </div>
    </div>
  )
}
