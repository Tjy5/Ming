import { useState, useRef, useEffect, useMemo } from 'react'
import type { GameState, DecreeType, StructuredDecree } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES, REGION_TARGET_NAMES, GOVERNANCE_REGION_NAMES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import { useRegisterOverlay } from '../hooks/useRegisterOverlay'
import { useFocusTrap } from '../hooks/useFocusTrap'
import {
  CATEGORY_DECREES,
  CATEGORY_TABS,
  TAB_TO_CATEGORY,
  type DecreeCategoryTab,
} from '../constants/decreeCategories'
import EdictWritingPanel from './EdictWritingPanel'
import DesktopIcon from './DesktopIcon'
import { joinRegionsToGovernanceDivisions } from '../data/map/geography'

interface Props {
  isOpen: boolean
  onClose: () => void
  state: GameState
  loading: boolean
  hasBlockingEvent: boolean
  targetRegion?: string | null
  targetRegionMembers?: readonly string[]
  onClearTargetRegion?: () => void
  onDecree: (decrees: StructuredDecree[]) => Promise<string | null> | void
  onFreeText: (text: string) => Promise<string | null> | void
}

interface PainPointItem {
  id: string
  kind: 'disaster' | 'rebellion' | 'threat' | 'morale'
  severity: number
  description: string
  suggestion: {
    title: string
    structured?: StructuredDecree
    text: string
  }
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
  const [prefilledStructuredDecree, setPrefilledStructuredDecree] = useState<StructuredDecree | null>(null)
  const [sealing, setSealing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const modalPanelRef = useRef<HTMLDivElement | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const actionLocked = loading || hasBlockingEvent || submitting || sealing
  const textLocked = loading || submitting || sealing

  // Register central modal overlay when structured sub-panel is NOT open
  useRegisterOverlay(isOpen && !selectedStructuredType, {
    id: 'imperial_edict_modal',
    kind: 'central_modal',
    priority: 30,
    closeAction: onClose,
  })

  useFocusTrap({
    active: isOpen && !selectedStructuredType,
    containerRef: modalPanelRef,
    overlayId: 'imperial_edict_modal',
  })

  useEffect(() => {
    if (isOpen && !selectedStructuredType) {
      window.setTimeout(() => textareaRef.current?.focus(), 50)
    }
  }, [isOpen, selectedStructuredType])

  const isValidTarget = useMemo(() => {
    if (!targetRegion) return false
    return (
      (REGION_TARGET_NAMES as readonly string[]).includes(targetRegion) ||
      (GOVERNANCE_REGION_NAMES as readonly string[]).includes(targetRegion)
    )
  }, [targetRegion])

  // Derive target region aggregation & pain points
  const targetDivision = useMemo(() => {
    if (!targetRegion) return null
    const { divisions } = joinRegionsToGovernanceDivisions(state.regions)
    return divisions.find((d) => d.division.name === targetRegion) ?? null
  }, [state.regions, targetRegion])

  const targetRegionData = useMemo(() => {
    if (targetDivision?.region) return targetDivision.region
    return state.regions.find((r) => r.name === targetRegion) ?? null
  }, [state.regions, targetDivision, targetRegion])

  const painPoints = useMemo<PainPointItem[]>(() => {
    if (!isValidTarget || !targetRegionData || !targetRegion) return []
    const items: PainPointItem[] = []

    // 1. Disaster (priority 1)
    if (targetRegionData.disaster_level > 50) {
      const canRelief = checkPrecondition(state, 'disaster_relief')
      items.push({
        id: 'sugg_disaster',
        kind: 'disaster',
        severity: targetRegionData.disaster_level,
        description: `灾情严重（灾害等级 ${targetRegionData.disaster_level}）`,
        suggestion: canRelief
          ? {
              title: `【${targetRegion}】开仓赈济`,
              structured: { type: 'disaster_relief', target: targetRegion },
              text: `命户部开仓赈济${targetRegion}灾民，拨付钱粮平抑灾情。`,
            }
          : {
              title: `【${targetRegion}】赈济灾民（拟诏）`,
              text: `命户部与地方官严加体恤，拨付内帑赈济${targetRegion}受灾百姓。`,
            },
      })
    }

    // 2. Rebellion / Stability (priority 2)
    if (targetRegionData.rebellion_risk > 50 || targetRegionData.stability < 15) {
      items.push({
        id: 'sugg_rebellion',
        kind: 'rebellion',
        severity: Math.max(targetRegionData.rebellion_risk, 100 - targetRegionData.stability),
        description: `动乱失序（叛乱风险 ${targetRegionData.rebellion_risk}%，稳定度 ${targetRegionData.stability}）`,
        suggestion: {
          title: `【${targetRegion}】安抚治安`,
          text: `降旨安抚${targetRegion}军民，宽赦流民，整饬地方治安以平息动乱。`,
        },
      })
    }

    // 3. External Threat (priority 3)
    if (targetRegionData.threat !== 'none') {
      const canRecruit = checkPrecondition(state, 'recruit_troops')
      items.push({
        id: 'sugg_threat',
        kind: 'threat',
        severity: 70,
        description: `外患威胁：${targetRegionData.threat}（驻军 ${targetRegionData.garrison.toLocaleString()}人）`,
        suggestion: canRecruit
          ? {
              title: `【${targetRegion}】募兵布防`,
              structured: { type: 'recruit_troops', target: targetRegion },
              text: `命兵部在${targetRegion}募兵增援，加强城防哨戒以御外侮。`,
            }
          : {
              title: `【${targetRegion}】严加守备（拟诏）`,
              text: `严令${targetRegion}守军修缮城防，严密哨探防备敌情。`,
            },
      })
    }

    // 4. Morale (priority 4)
    if (targetRegionData.civil_morale < 15) {
      const canDecreaseTax = checkPrecondition(state, 'tax_decrease')
      items.push({
        id: 'sugg_morale',
        kind: 'morale',
        severity: 100 - targetRegionData.civil_morale,
        description: `民心低迷（民心指数 ${targetRegionData.civil_morale}%）`,
        suggestion: canDecreaseTax
          ? {
              title: `【${targetRegion}】减免赋税`,
              structured: { type: 'tax_decrease', target: targetRegion },
              text: `念${targetRegion}民生维艰，特予蠲免钱粮赋税，休养生息。`,
            }
          : {
              title: `【${targetRegion}】体恤民瘼（拟诏）`,
              text: `谕旨${targetRegion}抚恤孤寡，革除苛捐杂税以收揽民心。`,
            },
      })
    }

    // Sort order: Disaster > Rebellion > Threat > Morale, then severity desc, then id
    const kindOrder: Record<string, number> = { disaster: 1, rebellion: 2, threat: 3, morale: 4 }
    items.sort((a, b) => {
      if (kindOrder[a.kind] !== kindOrder[b.kind]) {
        return kindOrder[a.kind] - kindOrder[b.kind]
      }
      if (b.severity !== a.severity) {
        return b.severity - a.severity
      }
      return a.id.localeCompare(b.id)
    })

    return items.slice(0, 3)
  }, [isValidTarget, targetRegionData, targetRegion, state])

  if (!isOpen) return null

  const handleSuggestionClick = (item: PainPointItem) => {
    if (item.suggestion.structured) {
      setPrefilledStructuredDecree(item.suggestion.structured)
      setSelectedStructuredType(item.suggestion.structured.type)
    } else {
      setText(item.suggestion.text)
    }
  };

  const executeSealAndSubmit = (submitFn: () => Promise<string | null | void> | void) => {
    if (submitting || sealing) return
    setSubmitting(true)
    setSealing(true)
    setSubmitError(null)

    // Play seal sound if possible
    try {
      if (!audioRef.current && typeof Audio !== 'undefined') {
        audioRef.current = new Audio('/seal.mp3')
        audioRef.current.play().catch(() => {})
      }
    } catch {
      // Audio failure does not block submission
    }

    try {
      const res = submitFn()
      if (res && typeof (res as Promise<unknown>).then === 'function') {
        void (res as Promise<string | null | void>)
          .then((err) => {
            if (err && typeof err === 'string') {
              setSubmitError(err)
              setSubmitting(false)
              setSealing(false)
            } else {
              setText('')
              setSubmitting(false)
              setSealing(false)
              onClose()
            }
          })
          .catch((e) => {
            setSubmitError(e instanceof Error ? e.message : '政令提交失败')
            setSubmitting(false)
            setSealing(false)
          })
      } else {
        setText('')
        setSubmitting(false)
        setSealing(false)
        onClose()
      }
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : '政令提交失败')
      setSubmitting(false)
      setSealing(false)
    }
  }

  const handleFreeSubmit = () => {
    const t = text.trim()
    if (!t || textLocked) return
    const targetContext = targetRegion
      ? `【目标行政区：${targetRegion}${targetRegionMembers.length > 0 ? `；所辖治理地区：${targetRegionMembers.join('、')}` : ''}】`
      : ''
    const fullText = `${targetContext}${t}`
    void executeSealAndSubmit(() => onFreeText(fullText))
  }

  const handleStructuredConfirm = (decree: StructuredDecree) => {
    setSelectedStructuredType(null)
    setPrefilledStructuredDecree(null)
    void executeSealAndSubmit(() => onDecree([decree]))
  }

  return (
    <div
      className="imperial-edict-overlay"
      onClick={() => !sealing && !submitting && onClose()}
      aria-modal="true"
      role="dialog"
      aria-labelledby="imperial-edict-title"
      data-overlay-root="modal"
    >
      <div
        ref={modalPanelRef}
        data-overlay-panel="true"
        className={`imperial-edict-scroll${sealing ? ' is-sealing' : ''}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="imperial-edict-top">
          <div className="imperial-edict-header-title">
            <DesktopIcon name="document" />
            <div>
              <span className="imperial-edict-kicker">奉天承运 · 皇帝诏曰</span>
              <h2 id="imperial-edict-title" className="imperial-edict-title">御笔草诏台</h2>
            </div>
          </div>
          <button
            type="button"
            className="imperial-edict-close"
            onClick={onClose}
            aria-label="关闭草诏台"
            title="关闭 (ESC)"
            disabled={sealing || submitting}
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

          {/* 目标政区痛点与预填建议 */}
          {targetRegion && isValidTarget && (
            <div className="edict-painpoints-section" aria-label="目标行政区态势研判">
              <span className="painpoints-title">🏛️ 地方态势研判与建议：</span>
              {painPoints.length > 0 ? (
                <div className="painpoints-list">
                  {painPoints.map((item) => (
                    <div key={item.id} className={`painpoint-card kind-${item.kind}`}>
                      <span className="painpoint-desc">{item.description}</span>
                      <button
                        type="button"
                        className="painpoint-suggest-btn"
                        onClick={() => handleSuggestionClick(item)}
                        title="点击仅预填草拟政令，不会直接提交"
                      >
                        预填建议：{item.suggestion.title}
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="painpoints-calm">局势平稳（该行政区各项指标平稳，可按需定制政令）</p>
              )}
            </div>
          )}

          {targetRegion && !isValidTarget && (
            <div className="edict-painpoints-section" aria-label="目标行政区提示">
              <p className="painpoints-calm">当前选定区域暂无治理细化指标，不可自动预填。</p>
            </div>
          )}

          {submitError && (
            <div className="edict-submit-error" role="alert">
              ⚠️ 政令提交未完成：{submitError}，草稿已保留。
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
                    onClick={() => {
                      setPrefilledStructuredDecree(targetRegion ? { type, target: targetRegion } : null)
                      setSelectedStructuredType(type)
                    }}
                  >
                    {usedThisMonth ? `${DECREE_LABELS[type]}(已用)` : DECREE_LABELS[type]}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        <footer className="imperial-edict-footer">
          <button type="button" className="edict-cancel" onClick={onClose} disabled={sealing || submitting}>
            收回御案
          </button>
          <button
            type="button"
            className="imperial-seal-submit"
            onClick={handleFreeSubmit}
            disabled={textLocked || !text.trim()}
            title="颁布自然语言草拟之圣旨 (Ctrl+Enter)"
          >
            {sealing ? (
              <span className="seal-stamp-mini">御批落印中…</span>
            ) : (
              <>
                <DesktopIcon name="document" />
                <span>御批 · 颁布诏书</span>
              </>
            )}
          </button>
        </footer>
      </div>

      {/* 结构化政令细化弹窗 */}
      {selectedStructuredType && (
        <EdictWritingPanel
          type={selectedStructuredType}
          state={state}
          loading={loading || submitting || sealing}
          prefilledDecree={prefilledStructuredDecree}
          onConfirm={handleStructuredConfirm}
          onCancel={() => {
            setSelectedStructuredType(null)
            setPrefilledStructuredDecree(null)
          }}
        />
      )}
    </div>
  )
}
