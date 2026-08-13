import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Region, RegionControl } from '../types/game'
import {
  MAP_MODE_PRESENTATIONS,
  VIEW_MODES,
  getBarPercent,
  getColorLevel,
  getModeValueLabel,
  getTaxCollectedRanks,
  getTooltipText,
  levelColor,
  type ViewMode,
} from './regionMapUtils'
import { CHINA_REFERENCE_BASEMAP } from '../data/map/chinaReferenceBasemap'
import { joinRegionsToMap, MAP_VIEWBOX, type MapRegionStatus } from '../data/map/geography'

const CONTROL_CLASSES: Record<RegionControl, string> = {
  '朝廷': 'control-court',
  '失控': 'control-lost',
  '沦陷': 'control-fallen',
}

interface Props {
  regions: Region[]
  highlightRegion?: string
  toasts?: string[]
  onRegionClick?: (region: Region) => void
}

export default function RegionMap({ regions, highlightRegion, toasts, onRegionClick }: Props) {
  const [tooltip, setTooltip] = useState<string | null>(null)
  const [hoveredRegionId, setHoveredRegionId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('standard')
  const joined = useMemo(() => joinRegionsToMap(regions), [regions])
  const taxRanks = useMemo(() => viewMode === 'tax_collected' ? getTaxCollectedRanks(regions) : null, [viewMode, regions])
  const presentation = MAP_MODE_PRESENTATIONS[viewMode]

  function resolveLevel(region: Region): 'high' | 'mid' | 'low' {
    return viewMode === 'tax_collected' ? taxRanks?.get(region.name) ?? 'low' : getColorLevel(viewMode, region)
  }

  function renderFeature(item: MapRegionStatus) {
    const { feature, region } = item
    const highlighted = !!region && highlightRegion === region.name
    const level = region ? resolveLevel(region) : 'low'
    const { anchor, label: viewport } = feature
    const controlClass = region ? CONTROL_CLASSES[region.control] : 'control-missing'
    const hasThreat = !!region && region.threat !== 'none'
    const hovered = hoveredRegionId === feature.mapRegionId
    const label = region
      ? `${region.name}，控制：${region.control}，${presentation.title}：${getModeValueLabel(viewMode, region)}${hasThreat ? `，威胁：${region.threat}` : ''}`
      : `${feature.displayName}，尚未接入治理数据`
    return (
      <g
        key={feature.mapRegionId}
        className={`map-feature stab-${level} ${controlClass}${highlighted ? ' selected' : ''}${hovered ? ' hovered' : ''}${hasThreat ? ' has-threat' : ''}${item.state === 'missing' ? ' missing' : ''}`}
        data-map-region-id={feature.mapRegionId}
        data-state={item.state}
        data-level={level}
        data-control={region?.control ?? 'missing'}
        data-threat={region?.threat ?? 'unknown'}
      >
        <path
          d={feature.path}
          className="map-feature-shape"
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
            className={`region-block map-region-button${highlighted ? ' highlight-pulse' : ''}`}
            data-region-name={region?.name ?? feature.displayName}
            data-view-mode={viewMode}
            aria-pressed={highlighted}
            aria-label={label}
            disabled={!region}
            onMouseEnter={() => setHoveredRegionId(feature.mapRegionId)}
            onMouseLeave={() => setHoveredRegionId(null)}
            onFocus={() => setHoveredRegionId(feature.mapRegionId)}
            onBlur={() => setHoveredRegionId(null)}
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
          >
            <span className="region-name">{feature.displayName}</span>
            {region ? (
              <>
                <span className="region-info"><span className="region-mode-value">{getModeValueLabel(viewMode, region)}</span>{hasThreat && <motion.span className="region-threat" initial={{ scale: 0 }} animate={{ scale: 1 }}>{region.threat}</motion.span>}</span>
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
      <div className={`region-map geographic-map mode-${viewMode}`} data-view-mode={viewMode}>
        <svg viewBox={MAP_VIEWBOX} aria-labelledby="region-map-title region-map-description" preserveAspectRatio="xMidYMid meet">
          <title id="region-map-title">现代中国地理参考与元末八战略区域</title>
          <desc id="region-map-description">现代省域轮廓仅作方位参照，彩色范围为可操作的元末战略区域。</desc>
          <rect x="0" y="0" width="774" height="569" className="map-water" aria-hidden="true" />
          <defs aria-hidden="true">
            <pattern id="map-missing-pattern" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="10" height="10" className="map-missing-pattern-bg" />
              <line x1="0" y1="0" x2="0" y2="10" className="map-missing-pattern-line" />
            </pattern>
          </defs>
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
          <div className="map-data-warning" role="status" aria-label="地图数据告警">
            {joined.unmapped.length > 0 && <span className="map-warning-item warning-unmapped" data-warning-kind="unmapped">未映射：{joined.unmapped.map((region) => region.name).join('、')}</span>}
            {joined.duplicates.length > 0 && <span className="map-warning-item warning-duplicate" data-warning-kind="duplicate">重复：{joined.duplicates.map((region) => region.name).join('、')}</span>}
          </div>
        )}
        <section className="map-mode-context" aria-live="polite" aria-label={`${presentation.title}图例`}>
          <div className="map-mode-heading">
            <h2>{presentation.title}</h2>
            <span>{presentation.label}</span>
          </div>
          <p>{presentation.description}</p>
          <div className="map-legend">
            {presentation.legend.map((entry) => (
              <span key={entry.level} data-legend-level={entry.level}><i className={`legend-swatch legend-${entry.level}`} />{entry.label}<small>{entry.range}</small></span>
            ))}
          </div>
        </section>
        <p className="map-accuracy-note">现代地理参考底图；区域为元末战略范围，不等同于现代省界或精确的 1368 行政疆界。</p>
        <AnimatePresence>{toasts?.map((msg) => <motion.div key={msg} className="map-toast" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>{msg}</motion.div>)}</AnimatePresence>
      </div>
      <div className="view-switcher" role="group" aria-label="地图视图">
        {VIEW_MODES.map((mode) => <button key={mode} type="button" className={`view-btn mode-${mode}${viewMode === mode ? ' active' : ''}`} aria-pressed={viewMode === mode} onClick={() => setViewMode(mode)}>{MAP_MODE_PRESENTATIONS[mode].label}</button>)}
      </div>
    </div>
  )
}
