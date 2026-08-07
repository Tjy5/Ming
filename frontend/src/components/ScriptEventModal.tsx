import { useState } from 'react'
import Markdown from 'react-markdown'
import type { GameEvent, StructuredDecree } from '../types/game'

interface Props {
  event: GameEvent
  onChoose: (decrees: StructuredDecree[], scriptId: string, freeText?: string, loyaltyEffects?: [string, number][], stateEffects?: Record<string, number>) => Promise<string | null>
  onBack: () => void
}

export default function ScriptEventModal({ event, onChoose, onBack }: Props) {
  const scriptId = event.script_id!
  const text = event.rich_description || event.description
  const [freeText, setFreeText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [warning, setWarning] = useState<string | null>(null)
  const [hintOpen, setHintOpen] = useState(false)

  async function handleSubmit() {
    const trimmed = freeText.trim()
    if (submitting || !trimmed) return
    setWarning(null)
    setSubmitting(true)
    try {
      const errorCode = await onChoose([], scriptId, trimmed)
      if (errorCode === 'FREEFORM_EMPTY') {
        setWarning('指令不明，请重新输入')
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
        {(event.historical_hint || event.historical_basis) && (
          <div className="script-hint-section">
            <button
              type="button"
              className="script-hint-toggle"
              aria-expanded={hintOpen}
              aria-controls="historical-hint-content"
              onClick={() => setHintOpen(v => !v)}
            >
              {hintOpen ? '📜 史实注释（附文）（点击收起）' : '📜 史实注释（附文）（点击展开）'}
            </button>
            {hintOpen && (
              <div id="historical-hint-content" className="script-hint-body">
                <Markdown>{event.historical_basis || event.historical_hint}</Markdown>
              </div>
            )}
          </div>
        )} 

        <div className="script-freetext">
          <textarea
            maxLength={200}
            value={freeText}
            onChange={e => { setFreeText(e.target.value); setWarning(null) }}
            placeholder="输入你的指令（如：罢免贪官、开仓赈济、按兵不动...）"
            disabled={submitting}
          />
          <div className="script-freetext-footer">
            {warning && <span className="script-warning">{warning}</span>}
            <span className="char-count">{freeText.length}/200</span>
            <button
              className="modal-btn"
              disabled={submitting}
              onClick={onBack}
            >
              返回
            </button>
            <button
              className="modal-btn primary"
              disabled={!freeText.trim() || submitting}
              onClick={handleSubmit}
            >
              {submitting ? '处理中…' : '下令'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
