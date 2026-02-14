import { useState, useMemo } from 'react'
import type { Region } from '../types/game'

export type ViewMode = 'standard' | 'disaster' | 'morale' | 'rebellion' | 'tax_rate' | 'tax_collected'

const VIEW_LABELS: Record<ViewMode, string> = {
  standard: '标准',
  disaster: '灾情',
  morale: '民心',
  rebellion: '动乱',
  tax_rate: '税率',
  tax_collected: '赋税',
}

const VIEW_MODES: ViewMode[] = ['standard', 'disaster', 'morale', 'rebellion', 'tax_rate', 'tax_collected']

const TAX_LABELS = { low: '低', medium: '中', high: '高' } as const
const THREAT_LABELS: Record<string, string> = { none: '无', 后金: '后金', 民变: '民变', 土司: '土司', 海盗: '海盗' }

interface Props {
  regions: Region[]
}

function threeLevel(value: number, low: number, high: number): 'high' | 'mid' | 'low' {
  if (value > high) return 'high'
  if (value >= low) return 'mid'
  return 'low'
}

function levelColor(level: 'high' | 'mid' | 'low'): string {
  if (level === 'high') return 'var(--green)'
  if (level === 'mid') return 'var(--yellow)'
  return 'var(--red)'
}

function getColorLevel(view: ViewMode, r: Region): 'high' | 'mid' | 'low' {
  switch (view) {
    case 'standard': return threeLevel(r.stability, 30, 60)
    case 'disaster': // <20 green, 20-50 yellow, >50 red
      if (r.disaster_level < 20) return 'high'
      if (r.disaster_level <= 50) return 'mid'
      return 'low'
    case 'morale': return threeLevel(r.civil_morale, 30, 60)
    case 'rebellion': // <20 green, 20-50 yellow, >50 red
      if (r.rebellion_risk < 20) return 'high'
      if (r.rebellion_risk <= 50) return 'mid'
      return 'low'
    case 'tax_rate': // >0.8 green, 0.5-0.8 yellow, <0.5 red
      if (r.tax_rate > 0.8) return 'high'
      if (r.tax_rate >= 0.5) return 'mid'
      return 'low'
    default: return 'mid'
  }
}

export function getTaxCollectedRanks(regions: Region[]): Map<string, 'high' | 'mid' | 'low'> {
  const result = new Map<string, 'high' | 'mid' | 'low'>()
  if (regions.every(r => r.tax_collected === 0)) {
    regions.forEach(r => result.set(r.name, 'low'))
    return result
  }
  const sorted = [...regions].sort((a, b) => {
    if (b.tax_collected !== a.tax_collected) return b.tax_collected - a.tax_collected
    if (b.stability !== a.stability) return b.stability - a.stability
    return a.name.localeCompare(b.name)
  })
  sorted.forEach((r, i) => {
    if (i < 2) result.set(r.name, 'high')
    else if (i < 6) result.set(r.name, 'mid')
    else result.set(r.name, 'low')
  })
  return result
}

function getBarPercent(view: ViewMode, r: Region, regions: Region[]): number {
  let v: number
  switch (view) {
    case 'standard': v = r.stability; break
    case 'disaster': v = 100 - r.disaster_level; break
    case 'morale': v = r.civil_morale; break
    case 'rebellion': v = 100 - r.rebellion_risk; break
    case 'tax_rate': v = r.tax_rate * 100; break
    case 'tax_collected': {
      const max = Math.max(...regions.map(x => x.tax_collected), 1)
      v = (r.tax_collected / max) * 100; break
    }
  }
  return Math.max(0, Math.min(100, v))
}

export function getTooltipText(view: ViewMode, r: Region): string {
  switch (view) {
    case 'standard':
      return `稳定度: ${r.stability} | 驻军: ${r.garrison.toLocaleString()} | 控制: ${r.control}`
    case 'disaster':
      return `灾害等级: ${r.disaster_level} | 威胁: ${THREAT_LABELS[r.threat] ?? r.threat} | 稳定度: ${r.stability}`
    case 'morale':
      return `民心: ${r.civil_morale} | 稳定度: ${r.stability} | 控制: ${r.control}`
    case 'rebellion':
      return `动乱风险: ${r.rebellion_risk} | 驻军: ${r.garrison.toLocaleString()} | 威胁: ${THREAT_LABELS[r.threat] ?? r.threat}`
    case 'tax_rate':
      return `完成率: ${Math.round(r.tax_rate * 100)}% | 税贡: ${TAX_LABELS[r.tax_contribution]} | 稳定度: ${r.stability}`
    case 'tax_collected':
      return `实征: ${r.tax_collected} | 税贡: ${TAX_LABELS[r.tax_contribution]} | 完成率: ${Math.round(r.tax_rate * 100)}%`
  }
}

export default function RegionMap({ regions }: Props) {
  const [tooltip, setTooltip] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('standard')

  const taxRanks = useMemo(
    () => viewMode === 'tax_collected' ? getTaxCollectedRanks(regions) : null,
    [viewMode, regions]
  )

  function resolveLevel(r: Region): 'high' | 'mid' | 'low' {
    if (viewMode === 'tax_collected') return taxRanks!.get(r.name) ?? 'low'
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
                <div className="region-stab-fill" style={{ width: `${getBarPercent(viewMode, r, regions)}%`, backgroundColor: levelColor(level) }} />
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
