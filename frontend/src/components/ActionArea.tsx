import { useState } from 'react'
import type { GameState, DecreeType, StructuredDecree } from '../types/game'
import { DECREE_TYPES, DECREE_LABELS, PRECONDITION_MESSAGES, TARGET_REQUIRED } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import TargetDialog from './TargetDialog'

interface Props {
  state: GameState
  loading: boolean
  onDecree: (decrees: StructuredDecree[]) => void
  onFreeText: (text: string) => void
}

export default function ActionArea({ state, loading, onDecree, onFreeText }: Props) {
  const [text, setText] = useState('')
  const [targetType, setTargetType] = useState<DecreeType | null>(null)

  function handleBtn(type: DecreeType) {
    if (TARGET_REQUIRED[type]) {
      setTargetType(type)
    } else {
      onDecree([{ type }])
    }
  }

  function handleSubmit() {
    const t = text.trim()
    if (!t) return
    onFreeText(t)
    setText('')
  }

  return (
    <div className="action-area">
      <div className="decree-grid">
        {DECREE_TYPES.map((type) => {
          const ok = checkPrecondition(state, type)
          return (
            <button
              key={type}
              className="decree-btn"
              disabled={!ok || loading}
              title={ok ? DECREE_LABELS[type] : PRECONDITION_MESSAGES[type]}
              onClick={() => handleBtn(type)}
            >
              {DECREE_LABELS[type]}
            </button>
          )
        })}
      </div>
      <div className="text-input-row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="输入政令（如：加征辽饷）"
          disabled={loading}
        />
        <button onClick={handleSubmit} disabled={loading || !text.trim()}>下旨</button>
      </div>
      {targetType && (
        <TargetDialog
          type={targetType}
          onConfirm={(decree) => { setTargetType(null); onDecree([decree]) }}
          onCancel={() => setTargetType(null)}
        />
      )}
    </div>
  )
}
