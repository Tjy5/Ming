import { useState } from 'react'
import Markdown from 'react-markdown'
import type { GameEvent } from '../types/game'

interface Props {
  events: GameEvent[]
  pendingMemorials?: number
  onScriptClick?: (event: GameEvent) => void
  onMemorialClick?: () => void
}

function urgClass(u: string): string {
  if (u === '高') return 'urg-high'
  if (u === '中') return 'urg-mid'
  return 'urg-low'
}

export default function EventBar({ events, pendingMemorials = 0, onScriptClick, onMemorialClick }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const recent = events.slice(-5).reverse()

  function handleClick(e: GameEvent) {
    if (e.is_scripted && e.choices.length > 0 && onScriptClick) {
      onScriptClick(e)
    } else {
      setExpanded(expanded === e.name ? null : e.name)
    }
  }

  return (
    <div className="event-bar">
      <div className="event-bar-title">近期事件</div>
      {pendingMemorials > 0 && (
        <div className="event-item memorial-notify" onClick={onMemorialClick}>
          <span className="event-badge urg-high" />
          <span className="event-title">奏折待批</span>
          <span className="memorial-badge">{pendingMemorials}</span>
        </div>
      )}
      {recent.length === 0 && <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>暂无事件</div>}
      {recent.map((e, i) => (
        <div key={`${e.name}-${i}`}>
          <div className="event-item" onClick={() => handleClick(e)}>
            <span className={`event-badge ${urgClass(e.urgency)}`} />
            <span className="event-title">{e.name}</span>
            {e.is_scripted && <span className="event-scripted-badge">剧情</span>}
          </div>
          {expanded === e.name && (
            <div className="event-narrative">
              {e.rich_description
                ? <Markdown>{e.rich_description}</Markdown>
                : e.description}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
