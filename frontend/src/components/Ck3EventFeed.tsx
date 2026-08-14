import { useState } from 'react'
import Markdown from 'react-markdown'
import type { GameEvent } from '../types/game'

interface Props {
  events: GameEvent[]
  onScriptClick?: (event: GameEvent) => void
}

function urgClass(u: string): string {
  if (u === '高') return 'urg-high'
  if (u === '中') return 'urg-mid'
  return 'urg-low'
}

export default function Ck3EventFeed({ events, onScriptClick }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const recent = events.slice(-3).reverse()

  if (recent.length === 0) return null

  function handleClick(e: GameEvent) {
    if (e.is_scripted && e.choices.length > 0 && onScriptClick) {
      onScriptClick(e)
    } else {
      setExpanded(expanded === e.name ? null : e.name)
    }
  }

  return (
    <aside className="ck3-event-feed" aria-label="天下简报">
      {recent.map((e, i) => (
        <article
          key={`${e.name}-${i}`}
          className={`ck3-event-item ${urgClass(e.urgency)}`}
          onClick={() => handleClick(e)}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              handleClick(e)
            }
          }}
          title={e.is_scripted ? '点击进行剧情决断' : '点击查看详情'}
        >
          <div className="ck3-event-header">
            <span className="ck3-event-badge">{e.is_scripted ? '剧情' : '要闻'}</span>
            <strong className="ck3-event-title">{e.name}</strong>
          </div>
          <p className="ck3-event-desc">{e.description || '局势演变中。'}</p>
          {expanded === e.name && (
            <div className="ck3-event-expanded" onClick={(ev) => ev.stopPropagation()}>
              {e.rich_description ? <Markdown>{e.rich_description}</Markdown> : e.description}
            </div>
          )}
        </article>
      ))}
    </aside>
  )
}
