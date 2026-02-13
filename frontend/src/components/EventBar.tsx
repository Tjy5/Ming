import { useState } from 'react'
import type { GameEvent } from '../types/game'

interface Props {
  events: GameEvent[]
}

function urgClass(u: string): string {
  if (u === '高') return 'urg-high'
  if (u === '中') return 'urg-mid'
  return 'urg-low'
}

export default function EventBar({ events }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const recent = events.slice(-5).reverse()

  return (
    <div className="event-bar">
      <div className="event-bar-title">近期事件</div>
      {recent.length === 0 && <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>暂无事件</div>}
      {recent.map((e, i) => (
        <div key={`${e.name}-${i}`}>
          <div className="event-item" onClick={() => setExpanded(expanded === e.name ? null : e.name)}>
            <span className={`event-badge ${urgClass(e.urgency)}`} />
            <span className="event-title">{e.name}</span>
          </div>
          {expanded === e.name && e.description && (
            <div className="event-narrative">{e.description}</div>
          )}
        </div>
      ))}
    </div>
  )
}
