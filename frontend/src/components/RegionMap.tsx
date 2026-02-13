import { useState } from 'react'
import type { Region } from '../types/game'

interface Props {
  regions: Region[]
}

function stabClass(s: number): string {
  if (s > 60) return 'stab-high'
  if (s >= 30) return 'stab-mid'
  return 'stab-low'
}

function stabColor(s: number): string {
  if (s > 60) return 'var(--green)'
  if (s >= 30) return 'var(--yellow)'
  return 'var(--red)'
}

const TAX_LABELS = { low: '低', medium: '中', high: '高' } as const

export default function RegionMap({ regions }: Props) {
  const [tooltip, setTooltip] = useState<string | null>(null)

  return (
    <div className="region-map">
      {regions.map((r) => (
        <div
          key={r.name}
          className={`region-block ${stabClass(r.stability)}`}
          onClick={() => setTooltip(tooltip === r.name ? null : r.name)}
        >
          <div className="region-name">{r.name}</div>
          <div className="region-info">
            <span className="region-control">{r.control}</span>
            {r.threat !== 'none' && <span className="region-threat">{r.threat}</span>}
          </div>
          <div className="region-stab-bar">
            <div className="region-stab-fill" style={{ width: `${r.stability}%`, backgroundColor: stabColor(r.stability) }} />
          </div>
          {tooltip === r.name && (
            <div className="region-tooltip" style={{ top: '100%', left: 0, marginTop: 4 }}>
              <dl>
                <dt>稳定度</dt><dd>{r.stability}/100</dd>
                <dt>驻军</dt><dd>{r.garrison.toLocaleString()}</dd>
                <dt>税贡</dt><dd>{TAX_LABELS[r.tax_contribution]}</dd>
                <dt>威胁</dt><dd>{r.threat === 'none' ? '无' : r.threat}</dd>
                <dt>控制</dt><dd>{r.control}</dd>
              </dl>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
