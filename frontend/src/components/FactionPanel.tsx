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
  return (
    <div className="faction-panel">
      {factions.map((f) => (
        <div key={f.name} className={`faction-card ${riskClass(f.rebellion_risk)}`}>
          <div className="faction-name">{f.name}</div>
          <div className="faction-row">
            <label>满意度</label>
            <Bar value={f.satisfaction} color={f.satisfaction > 50 ? 'var(--green)' : 'var(--yellow)'} />
            <span style={{ width: 28, textAlign: 'right', fontSize: '0.75rem' }}>{f.satisfaction}</span>
          </div>
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
