import { useMemo, useState } from 'react'
import type { Region } from '../types/game'
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

interface Props {
  regions: Region[]
}

export default function RegionMap({ regions }: Props) {
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
          return (
            <div
              key={r.name}
              className={`region-block ${stabClassMap[level]}`}
              onClick={() => setTooltip(tooltip === r.name ? null : r.name)}
            >
              <div className="region-name">{r.name}</div>
              <div className="region-info">
                <span className="region-control">{r.control}</span>
                {r.threat !== 'none' && <span className="region-threat">{r.threat}</span>}
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
