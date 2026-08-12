import { useState } from 'react'
import type { Faction } from '../types/game'

interface Props {
  factions: Faction[]
}

function riskClass(risk: number): string {
  if (risk > 80) return 'risk-critical'
  if (risk > 60) return 'risk-high'
  return ''
}

function Bar({ value, color }: { value: number; color: string }) {
  return (
    <div className="progress-track">
      <div className="progress-fill" style={{ width: `${value}%`, backgroundColor: color }} />
    </div>
  )
}

export default function FactionPanel({ factions }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <div className="faction-panel">
      {factions.map((f) => (
        <div key={f.name} className={`faction-card ${riskClass(f.rebellion_risk)}`}>
          <button type="button" className="faction-name faction-toggle" aria-expanded={expanded === f.name} onClick={() => setExpanded(expanded === f.name ? null : f.name)}>{f.name}<span aria-hidden="true">{expanded === f.name ? '▼' : '▶'}</span></button>
          <div className="faction-row">
            <label>满意度</label>
            <Bar value={f.satisfaction} color={f.satisfaction > 50 ? 'var(--green)' : 'var(--yellow)'} />
            <span style={{ width: 28, textAlign: 'right', fontSize: '0.75rem' }}>{f.satisfaction}</span>
          </div>
          {expanded === f.name && <div className="faction-details" role="region" aria-label={`${f.name}详情`}>
            <p>当前立场与影响力来自本世界版本的派系投影。</p>
            <p>突出风险：{f.rebellion_risk > 60 ? '叛乱风险偏高' : '暂无突出风险'}</p>
          </div>}
          <div className="faction-row">
            <label>影响力</label>
            <Bar value={f.influence} color="var(--accent-gold)" />
            <span style={{ width: 28, textAlign: 'right', fontSize: '0.75rem' }}>{f.influence}</span>
          </div>
          <div className="faction-row">
            <label>叛乱</label>
            <Bar value={f.rebellion_risk} color={f.rebellion_risk > 60 ? 'var(--red)' : 'var(--gray)'} />
            <span style={{ width: 28, textAlign: 'right', fontSize: '0.75rem' }}>{f.rebellion_risk}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
