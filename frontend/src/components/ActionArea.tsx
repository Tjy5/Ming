import { useState } from 'react'
import type { GameState, DecreeType, StructuredDecree, ModalItem } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import { CATEGORY_DECREES, CATEGORY_TABS, TAB_TO_CATEGORY, type DecreeCategoryTab } from '../constants/decreeCategories'
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
  targetRegion?: string | null
  onClearTargetRegion?: () => void
}

export default function ActionArea({
  state, loading, hasBlockingEvent,
  onDecree, onFreeText, onAdvanceMonth, advanceMonthInFlight,
  currentModal,
  targetRegion,
  onClearTargetRegion,
}: Props) {
  const [text, setText] = useState('')
  const [tab, setTab] = useState<DecreeCategoryTab>('内政')
  const [edictType, setEdictType] = useState<DecreeType | null>(null)
  const actionLocked = loading || hasBlockingEvent
  const textLocked = loading

  function handleSubmit() {
    const t = text.trim()
    if (!t) return
    onFreeText(targetRegion ? `【目标地区：${targetRegion}】${t}` : t)
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
        {CATEGORY_TABS.map(c => (
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
              const usedThisMonth = !!state.decrees_this_month[TAB_TO_CATEGORY[tab]]
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
        {targetRegion && (
          <div className="action-target-chip" aria-label={`行动目标：${targetRegion}`}>
            <span>目标地区：{targetRegion}</span>
            <button type="button" aria-label="移除地区目标" onClick={onClearTargetRegion}>×</button>
          </div>
        )}
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && !textLocked && handleSubmit()}
          placeholder="输入政令（如：整顿军备）"
          disabled={textLocked}
        />
        <button className="confirm-btn" onClick={handleSubmit} disabled={textLocked || !text.trim()}>下令</button>
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
