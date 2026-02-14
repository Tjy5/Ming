import Markdown from 'react-markdown'
import type { GameEvent, GameState, StructuredDecree } from '../types/game'
import { PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'

interface Props {
  event: GameEvent
  state: GameState
  onChoose: (decrees: StructuredDecree[], scriptId: string) => void
}

function disabledReason(state: GameState, decrees: StructuredDecree[]): string | null {
  const failed = [...new Set(
    decrees.filter(d => !checkPrecondition(state, d.type)).map(d => d.type),
  )]
  return failed.length ? failed.map(t => PRECONDITION_MESSAGES[t]).join('；') : null
}

export default function ScriptEventModal({ event, state, onChoose }: Props) {
  const scriptId = event.script_id!
  const text = event.rich_description || event.description

  return (
    <div className="modal-overlay">
      <div className="modal script-modal" onClick={e => e.stopPropagation()}>
        <h3>{event.name}</h3>
        <div className="script-md-body">
          <Markdown>{text}</Markdown>
        </div>
        <div className="script-choices">
          {event.choices.length === 0 ? (
            <button className="modal-btn primary" onClick={() => onChoose([], scriptId)}>
              知道了
            </button>
          ) : event.choices.map((c, i) => {
            const reason = disabledReason(state, c.decrees)
            return (
              <button
                key={i}
                className={`script-choice-btn${reason ? ' disabled' : ''}`}
                disabled={!!reason}
                onClick={() => onChoose(c.decrees, scriptId)}
              >
                <span className="sc-label">{c.label}</span>
                <span className="sc-desc">{c.description}</span>
                {reason && <span className="sc-reason">{reason}</span>}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
