import { useState } from 'react'
import Markdown from 'react-markdown'
import type { GameEvent } from '../types/game'
import SurfaceHeader from './SurfaceHeader'
import DesktopIcon from './DesktopIcon'

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
    <section className="event-bar" aria-labelledby="event-report-title">
      <SurfaceHeader icon="document" title="事件与奏报" meta={recent.length ? `近报 ${recent.length}` : '暂无新报'} id="event-report-title" />
      {pendingMemorials > 0 && (
        <button type="button" className="event-item memorial-notify" onClick={onMemorialClick}>
          <span className="event-badge urg-high" />
          <span className="event-title">奏折待批</span>
          <span className="memorial-badge">{pendingMemorials}</span>
          <DesktopIcon name="chevron" size={13} />
        </button>
      )}
      {recent.length === 0 && <div className="event-empty-state">天下暂无新报，已结算事项将在此列示。</div>}
      {recent.map((e, i) => (
        <div key={`${e.name}-${i}`}>
          <button
            type="button"
            className="event-item"
            aria-expanded={!e.is_scripted || e.choices.length === 0 ? expanded === e.name : undefined}
            onClick={() => handleClick(e)}
          >
            <span className={`event-badge ${urgClass(e.urgency)}`} />
            <span className="event-title">{e.name}</span>
            {e.is_scripted && <span className="event-scripted-badge">剧情</span>}
            <DesktopIcon name="chevron" size={13} />
          </button>
          {expanded === e.name && (
            <div className="event-narrative">
              {e.rich_description
                ? <Markdown>{e.rich_description}</Markdown>
                : e.description}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
