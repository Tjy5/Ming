import { useState, useRef, useEffect } from 'react'
import type { GameState, DecreeType, StructuredDecree } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import {
  CATEGORY_DECREES,
  CATEGORY_TABS,
  TAB_TO_CATEGORY,
  type DecreeCategoryTab,
} from '../constants/decreeCategories'
import EdictWritingPanel from './EdictWritingPanel'
import DesktopIcon from './DesktopIcon'

interface Props {
  isOpen: boolean
  onClose: () => void
  state: GameState
  loading: boolean
  hasBlockingEvent: boolean
  targetRegion?: string | null
  targetRegionMembers?: readonly string[]
  onClearTargetRegion?: () => void
  onDecree: (decrees: StructuredDecree[]) => void
  onFreeText: (text: string) => void
}

export default function ImperialEdictModal({
  isOpen,
  onClose,
  state,
  loading,
  hasBlockingEvent,
  targetRegion,
  targetRegionMembers = [],
  onClearTargetRegion,
  onDecree,
  onFreeText,
}: Props) {
  const [text, setText] = useState('')
  const [tab, setTab] = useState<DecreeCategoryTab>('内政')
  const [selectedStructuredType, setSelectedStructuredType] = useState<DecreeType | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const actionLocked = loading || hasBlockingEvent
  const textLocked = loading

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !selectedStructuredType) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    window.setTimeout(() => textareaRef.current?.focus(), 50)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose, selectedStructuredType])

  if (!isOpen) return null

  const handleFreeSubmit = () => {
    const t = text.trim()
    if (!t || textLocked) return
    const targetContext = targetRegion
      ? `【目标行政区：${targetRegion}${targetRegionMembers.length > 0 ? `；所辖治理地区：${targetRegionMembers.join('、')}` : ''}】`
      : ''
    const fullText = `${targetContext}${t}`
    onFreeText(fullText)
    setText('')
    onClose()
  }

  const handleStructuredConfirm = (decree: StructuredDecree) => {
    setSelectedStructuredType(null)
    onDecree([decree])
    onClose()
  }

  return (
    <div className="imperial-edict-overlay" onClick={onClose} aria-modal="true" role="dialog">
      <div
        className="imperial-edict-scroll"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="imperial-edict-top">
          <div className="imperial-edict-header-title">
            <DesktopIcon name="document" />
            <div>
              <span className="imperial-edict-kicker">奉天承运 · 皇帝诏曰</span>
              <h2 className="imperial-edict-title">御笔草诏台</h2>
            </div>
          </div>
          <button
            type="button"
            className="imperial-edict-close"
            onClick={onClose}
            aria-label="关闭草诏台"
            title="关闭 (ESC)"
          >
            ×
          </button>
        </header>

        <div className="imperial-edict-content">
          {targetRegion && (
            <div className="imperial-edict-target-row">
              <span>当前行政区：</span>
              <div className="action-target-chip">
                <span>📍 {targetRegion}</span>
                <button type="button" onClick={onClearTargetRegion} title="移除地区目标">
                  ×
                </button>
              </div>
              {targetRegionMembers.length > 0 && (
                <small className="imperial-edict-target-members">所辖：{targetRegionMembers.join('、')}</small>
              )}
            </div>
          )}

          {/* 自由自然语言下旨 */}
          <div className="imperial-textarea-wrap">
            <label htmlFor="imperial-decree-text">✍️ 御笔草拟圣旨（由内阁与枢密院 AI 研判执行）</label>
            <textarea
              id="imperial-decree-text"
              ref={textareaRef}
              className="imperial-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault()
                  handleFreeSubmit()
                }
              }}
              placeholder={
                targetRegion
                  ? `向【${targetRegion}】颁布政令（如：命徐达巡防防备敌军，开仓赈济灾民……）`
                  : '在此手书圣旨（如：命徐达领兵进驻徐州，并拨内帑赈济灾民……按 Ctrl+Enter 颁布）'
              }
              disabled={textLocked}
            />
          </div>

          {/* 分类快捷政令 */}
          <div className="imperial-quick-decrees">
            <label>或从六部九卿定制政令：</label>
            <div className="imperial-edict-categories" role="tablist">
              {CATEGORY_TABS.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="tab"
                  className={`imperial-category-tab${tab === c ? ' active' : ''}`}
                  aria-selected={tab === c}
                  onClick={() => setTab(c)}
                >
                  {c === '内政' && '🏛️ '}
                  {c === '军事' && '⚔️ '}
                  {c === '外交' && '🤝 '}
                  {c === '其他' && '👥 '}
                  {c}
                </button>
              ))}
            </div>

            <div className="imperial-quick-grid">
              {CATEGORY_DECREES[tab].map((type) => {
                const ok = checkPrecondition(state, type)
                const usedThisMonth = !!state.decrees_this_month[TAB_TO_CATEGORY[tab]]
                const disabled = !ok || actionLocked || usedThisMonth
                return (
                  <button
                    key={type}
                    type="button"
                    className="imperial-quick-btn"
                    disabled={disabled}
                    title={ok ? DECREE_LABELS[type] : PRECONDITION_MESSAGES[type]}
                    onClick={() => setSelectedStructuredType(type)}
                  >
                    {usedThisMonth ? `${DECREE_LABELS[type]}(已用)` : DECREE_LABELS[type]}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        <footer className="imperial-edict-footer">
          <button type="button" className="edict-cancel" onClick={onClose}>
            收回御案
          </button>
          <button
            type="button"
            className="imperial-seal-submit"
            onClick={handleFreeSubmit}
            disabled={textLocked || !text.trim()}
            title="颁布自然语言草拟之圣旨 (Ctrl+Enter)"
          >
            <DesktopIcon name="document" />
            <span>御批 · 颁布诏书</span>
          </button>
        </footer>
      </div>

      {/* 结构化政令细化弹窗 */}
      {selectedStructuredType && (
        <EdictWritingPanel
          type={selectedStructuredType}
          state={state}
          loading={loading}
          prefilledDecree={targetRegion ? { type: selectedStructuredType, target: targetRegion } : null}
          onConfirm={handleStructuredConfirm}
          onCancel={() => setSelectedStructuredType(null)}
        />
      )}
    </div>
  )
}
