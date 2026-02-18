import { useState } from 'react'
import Markdown from 'react-markdown'
import type { GameEvent, StructuredDecree } from '../types/game'

interface Props {
  event: GameEvent
  onChoose: (decrees: StructuredDecree[], scriptId: string, freeText?: string) => Promise<string | null>
}

export default function ScriptEventModal({ event, onChoose }: Props) {
  const scriptId = event.script_id!
  const text = event.rich_description || event.description
  const [freeText, setFreeText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [warning, setWarning] = useState<string | null>(null)

  async function handleSubmit() {
    const trimmed = freeText.trim()
    if (submitting || !trimmed) return
    setWarning(null)
    setSubmitting(true)
    try {
      const errorCode = await onChoose([], scriptId, trimmed)
      if (errorCode === 'FREEFORM_EMPTY') {
        setWarning('旨意不明，请重新输入')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay">
      <div className="modal script-modal" onClick={e => e.stopPropagation()}>
        <h3>{event.name}</h3>
        <div className="script-md-body">
          <Markdown>{text}</Markdown>
        </div>
        <div className="script-freetext">
          <textarea
            maxLength={200}
            value={freeText}
            onChange={e => { setFreeText(e.target.value); setWarning(null) }}
            placeholder="输入你的旨意（如：罢免魏忠贤、加征辽饷、按兵不动...）"
            disabled={submitting}
          />
          <div className="script-freetext-footer">
            {warning && <span className="script-warning">{warning}</span>}
            <span className="char-count">{freeText.length}/200</span>
            <button
              className="modal-btn primary"
              disabled={!freeText.trim() || submitting}
              onClick={handleSubmit}
            >
              {submitting ? '处理中…' : '颁旨'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
