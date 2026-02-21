import { useState } from 'react'
import type { GameState, DecreeType, StructuredDecree, ModalItem } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import EdictWritingPanel from './EdictWritingPanel'

interface Props {
  state: GameState
  loading: boolean
  hasBlockingEvent: boolean
  onDecree: (decrees: StructuredDecree[]) => void
  onFreeText: (text: string) => void
  onAdvanceMonth: () => void
  advanceMonthInFlight: boolean
  currentModal: ModalItem | null
}

type Category = '内政' | '军事' | '外交' | '其他'

const CATEGORIES: Category[] = ['内政', '军事', '外交', '其他']

const CATEGORY_DECREES: Record<Category, DecreeType[]> = {
  军事: ['recruit_troops', 'disband_troops'],
  内政: ['tax_increase', 'tax_decrease', 'disaster_relief', 'harsh_punishment'],
  外交: ['diplomacy'],
  其他: ['personnel'],
}

export default function ActionArea({
  state, loading, hasBlockingEvent,
  onDecree, onFreeText, onAdvanceMonth, advanceMonthInFlight,
  currentModal,
}: Props) {
  const [text, setText] = useState('')
  const [tab, setTab] = useState<Category>('内政')
  const [edictType, setEdictType] = useState<DecreeType | null>(null)
  const actionLocked = loading || hasBlockingEvent
  const textLocked = loading

  function handleSubmit() {
    const t = text.trim()
    if (!t) return
    onFreeText(t)
    setText('')
  }

  function handleEdictConfirm(decree: StructuredDecree) {
    setEdictType(null)
    onDecree([decree])
  }

  function handleEdictCancel() {
    setEdictType(null)
  }

  return (
    <div className="action-area">
      <div className="category-tabs">
        {CATEGORIES.map(c => (
          <button
            key={c}
            className={`cat-tab${tab === c ? ' active' : ''}`}
            onClick={() => setTab(c)}
          >{c}</button>
        ))}
      </div>

      <div className="decree-tab-content">
          <div
            className="decree-grid"
          >
            {CATEGORY_DECREES[tab].map(type => {
              const ok = checkPrecondition(state, type)
              const usedThisMonth = !!state.decrees_this_month[type]
              return (
                <button
                  key={type}
                  className="decree-btn"
                  disabled={!ok || actionLocked || usedThisMonth}
                  title={ok ? DECREE_LABELS[type] : PRECONDITION_MESSAGES[type]}
                  onClick={() => {
                    if (actionLocked) return
                    setEdictType(type)
                  }}
                >
                  {usedThisMonth ? '本月已用' : DECREE_LABELS[type]}
                </button>
              )
            })}
          </div>
      </div>

      <div className="text-input-row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && !textLocked && handleSubmit()}
          placeholder="输入政令（如：加征辽饷）"
          disabled={textLocked}
        />
        <button className="confirm-btn" onClick={handleSubmit} disabled={textLocked || !text.trim()}>下旨</button>
      </div>

      <button
        className="advance-btn"
        disabled={loading || !!currentModal || hasBlockingEvent || advanceMonthInFlight || actionLocked}
        onClick={onAdvanceMonth}
      >
        {advanceMonthInFlight && <div className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }} />}
        进入下月
      </button>

      {edictType && (
        <EdictWritingPanel
          type={edictType}
          state={state}
          loading={loading}
          onConfirm={handleEdictConfirm}
          onCancel={handleEdictCancel}
        />
      )}
    </div>
  )
}
