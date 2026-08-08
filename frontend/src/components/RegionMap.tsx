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

const VIEW_LABELS: Record<ViewMode, string> = {
  standard: '标准',
  disaster: '灾情',
  morale: '民心',
  rebellion: '动乱',
  tax_rate: '税率',
  tax_collected: '赋税',
}

const VIEW_MODES: ViewMode[] = ['standard', 'disaster', 'morale', 'rebellion', 'tax_rate', 'tax_collected']

const CONTROL_BG: Partial<Record<RegionControl, string>> = {
  '失控': 'rgba(229,184,41,0.08)',
  '沦陷': 'rgba(224,64,64,0.1)',
}

interface Props {
  regions: Region[]
  highlightRegion?: string
  toasts?: string[]
  onRegionClick?: (region: Region) => void
}

export default function RegionMap({ regions, highlightRegion, toasts, onRegionClick }: Props) {
  const [tooltip, setTooltip] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('standard')

  const taxRanks = useMemo(
    () => viewMode === 'tax_collected' ? getTaxCollectedRanks(regions) : null,
    [viewMode, regions],
  )

  function resolveLevel(r: Region): 'high' | 'mid' | 'low' {
    if (viewMode === 'tax_collected') return taxRanks?.get(r.name) ?? 'low'
    return getColorLevel(viewMode, r)
  }

  const stabClassMap = { high: 'stab-high', mid: 'stab-mid', low: 'stab-low' } as const

  return (
    <div className="region-map-container">
      <div className="region-map">
        {regions.map((r) => {
          const level = resolveLevel(r)
          const highlighted = highlightRegion === r.name
          return (
            <div
              key={r.name}
              className={`region-block ${stabClassMap[level]}${highlighted ? ' highlight-pulse' : ''}`}
              onClick={() => {
                setTooltip(tooltip === r.name ? null : r.name)
                onRegionClick?.(r)
              }}
              style={{ backgroundColor: CONTROL_BG[r.control] }}
            >
              <div className="region-name">{r.name}</div>
              <div className="region-info">
                <span className="region-control">{r.control}</span>
                {r.threat !== 'none' && (
                  <motion.span
                    className="region-threat"
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ duration: 0.2 }}
                  >
                    {r.threat}
                  </motion.span>
                )}
              </div>
              <div className="region-stab-bar">
                <div
                  className="region-stab-fill"
                  style={{ width: `${getBarPercent(viewMode, r, regions)}%`, backgroundColor: levelColor(level) }}
                />
              </div>
              {tooltip === r.name && (
                <div className="region-tooltip" style={{ top: '100%', left: 0, marginTop: 4 }}>
                  {getTooltipText(viewMode, r)}
                </div>
              )}
            </div>
          )
        })}
        <AnimatePresence>
          {toasts?.map((msg) => (
            <motion.div
              key={msg}
              className="map-toast"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >{msg}</motion.div>
          ))}
        </AnimatePresence>
      </div>
      <div className="view-switcher">
        {VIEW_MODES.map(m => (
          <button
            key={m}
            className={`view-btn${viewMode === m ? ' active' : ''}`}
            onClick={() => setViewMode(m)}
          >
            {VIEW_LABELS[m]}
          </button>
        ))}
      </div>
    </div>
  )
}
