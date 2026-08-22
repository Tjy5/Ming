import { useRef, useState } from 'react'
import type { GameState, DecreeType, StructuredDecree, ModalItem } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import { CATEGORY_DECREES, CATEGORY_TABS, TAB_TO_CATEGORY, type DecreeCategoryTab } from '../constants/decreeCategories'
import EdictWritingPanel from './EdictWritingPanel'
import SurfaceHeader from './SurfaceHeader'
import DesktopIcon from './DesktopIcon'

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
  const edictTrigger = useRef<HTMLButtonElement | null>(null)
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
    window.setTimeout(() => edictTrigger.current?.focus(), 0)
  }

  function handleCategoryTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, category: DecreeCategoryTab) {
    const currentIndex = CATEGORY_TABS.indexOf(category)
    const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? CATEGORY_TABS.length - 1
        : direction
          ? (currentIndex + direction + CATEGORY_TABS.length) % CATEGORY_TABS.length
          : null
    if (nextIndex === null) return

    event.preventDefault()
    const nextTab = CATEGORY_TABS[nextIndex]
    setTab(nextTab)
    window.setTimeout(() => document.getElementById(`decree-category-${nextTab}`)?.focus(), 0)
  }

  return (
    <section className="action-area" aria-labelledby="command-surface-title">
      <SurfaceHeader
        icon="document"
        title="政令与行动"
        meta={actionLocked ? (hasBlockingEvent ? '事件待决' : '结算中') : `当前：${tab}`}
        id="command-surface-title"
      />
      <div className="category-tabs" role="tablist" aria-label="政令分类">
        {CATEGORY_TABS.map(c => (
          <button
            type="button"
            key={c}
            className={`cat-tab${tab === c ? ' active' : ''}`}
            id={`decree-category-${c}`}
            role="tab"
            aria-selected={tab === c}
            aria-controls="decree-tab-content"
            tabIndex={tab === c ? 0 : -1}
            onClick={() => setTab(c)}
            onKeyDown={(event) => handleCategoryTabKeyDown(event, c)}
          >{c}</button>
        ))}
      </div>

      <div className="decree-tab-content" id="decree-tab-content" role="tabpanel" aria-labelledby={`decree-category-${tab}`}>
          <div
            className="decree-grid"
          >
            {CATEGORY_DECREES[tab].map(type => {
              const ok = checkPrecondition(state, type)
              const usedThisMonth = !!state.decrees_this_month[TAB_TO_CATEGORY[tab]]
              return (
                <button
                  type="button"
                  key={type}
                  className="decree-btn"
                  disabled={!ok || actionLocked || usedThisMonth}
                  title={ok ? DECREE_LABELS[type] : PRECONDITION_MESSAGES[type]}
                  onClick={(event) => {
                    if (actionLocked) return
                    edictTrigger.current = event.currentTarget
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
          aria-label="御前政令"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && !textLocked && handleSubmit()}
          placeholder="输入政令（如：整顿军备）"
          disabled={textLocked}
        />
        <button type="button" className="confirm-btn" onClick={handleSubmit} disabled={textLocked || !text.trim()}><DesktopIcon name="document" />下令</button>
      </div>

      <button
        type="button"
        className="advance-btn"
        disabled={loading || !!currentModal || hasBlockingEvent || advanceMonthInFlight || actionLocked}
        onClick={onAdvanceMonth}
      >
        {advanceMonthInFlight ? <div className="spinner command-spinner" /> : <DesktopIcon name="clock" />}
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
    </section>
  )
}
