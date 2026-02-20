import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { GameState, DecreeType, StructuredDecree, PersonnelAction } from '../types/game'
import { DECREE_LABELS, REGION_NAMES, DIPLOMACY_TARGETS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'

interface Props {
  type: DecreeType
  state: GameState
  loading: boolean
  prefilledDecree?: StructuredDecree | null
  keywords?: string[]
  onConfirm: (decree: StructuredDecree) => void
  onCancel: () => void
}

function matchKeyword(type: DecreeType, kw: string): 'target' | null {
  if (type === 'disaster_relief' && (REGION_NAMES as readonly string[]).includes(kw)) return 'target'
  if (type === 'diplomacy' && (DIPLOMACY_TARGETS as string[]).includes(kw)) return 'target'
  if (type === 'personnel' && kw.length >= 2 && kw.length <= 4) return 'target'
  return null
}

export default function EdictWritingPanel({
  type, state, loading, prefilledDecree, keywords, onConfirm, onCancel,
}: Props) {
  const [target, setTarget] = useState<string | null>(prefilledDecree?.target ?? null)
  const [subAction, setSubAction] = useState<PersonnelAction>(
    (prefilledDecree?.sub_action as PersonnelAction) ?? 'appoint',
  )
  const [personName, setPersonName] = useState(
    type === 'personnel' && prefilledDecree?.target ? prefilledDecree.target : '',
  )
  const [sealing, setSealing] = useState(false)
  const [shaking, setShaking] = useState(false)
  const [inkSpread, setInkSpread] = useState(false)
  const submitted = useRef(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const timerRef = useRef<number[]>([])
  const [activeKeyword, setActiveKeyword] = useState<string | null>(null)

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
      }
      timerRef.current.forEach(id => window.clearTimeout(id))
    }
  }, [])

  const canIssue = checkPrecondition(state, type)
  const needsTarget = type === 'disaster_relief' || type === 'diplomacy' || type === 'personnel'
  const paramReady = type === 'personnel' ? !!personName.trim() : needsTarget ? !!target : true

  function handleKeywordClick(kw: string) {
    const role = matchKeyword(type, kw)
    if (!role) return
    setActiveKeyword(kw)
    if (type === 'personnel') setPersonName(kw)
    else setTarget(kw)
  }

  function handleSeal() {
    if (!canIssue || !paramReady || sealing) return
    setSealing(true)
  }

  function buildDecree(): StructuredDecree {
    const params = prefilledDecree?.parameters ?? undefined
    if (type === 'personnel') return { type, target: personName.trim(), sub_action: subAction, parameters: params }
    if (target) return { type, target, parameters: params }
    return { type, parameters: params }
  }

  function onSealLanded() {
    if (submitted.current) return
    // Sound
    if (!audioRef.current) audioRef.current = new Audio('/seal.mp3')
    audioRef.current.play().catch((err) => console.error('Audio playback failed:', err))
    // Shake
    setShaking(true)
    timerRef.current.push(window.setTimeout(() => {
      setShaking(false)
      // Ink spread
      setInkSpread(true)
      timerRef.current.push(window.setTimeout(() => {
        submitted.current = true
        onConfirm(buildDecree())
      }, 600))
    }, 200))
  }

  const stampAnimate = shaking
    ? { scale: 1, opacity: 1, x: [-2, 2, -2, 2, -2, 2, 0] }
    : { scale: 1, opacity: 1, x: 0 }

  return (
    <div className="modal-overlay" onClick={() => !sealing && onCancel()}>
      <AnimatePresence>
        {!sealing ? (
          <motion.div
            key="edict"
            className="edict-panel"
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, width: 0, padding: 0 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="edict-vertical-title">奉天承运皇帝诏曰</div>
            <div className="edict-header">{DECREE_LABELS[type]}</div>

            {!canIssue && (
              <div className="edict-warn">{PRECONDITION_MESSAGES[type]}</div>
            )}

            {keywords && keywords.length > 0 && (
              <div className="edict-keywords">
                {keywords.map(kw => {
                  const role = matchKeyword(type, kw)
                  return (
                    <button
                      key={kw}
                      className={`edict-keyword${activeKeyword === kw ? ' active' : ''}${!role ? ' inert' : ''}`}
                      onClick={() => handleKeywordClick(kw)}
                    >
                      {kw}
                    </button>
                  )
                })}
              </div>
            )}

            {type === 'disaster_relief' && (
              <div className="edict-targets">
                {REGION_NAMES.map(name => (
                  <button
                    key={name}
                    className={`edict-target-btn${target === name ? ' selected' : ''}`}
                    onClick={() => { setTarget(name); setActiveKeyword(null) }}
                  >{name}</button>
                ))}
              </div>
            )}

            {type === 'diplomacy' && (
              <div className="edict-targets">
                {DIPLOMACY_TARGETS.map(name => (
                  <button
                    key={name}
                    className={`edict-target-btn${target === name ? ' selected' : ''}`}
                    onClick={() => { setTarget(name); setActiveKeyword(null) }}
                  >{name}</button>
                ))}
              </div>
            )}

            {type === 'personnel' && (
              <div className="edict-personnel">
                <select value={subAction} onChange={e => setSubAction(e.target.value as PersonnelAction)}>
                  <option value="appoint">任命</option>
                  <option value="dismiss">罢免</option>
                </select>
                <input
                  placeholder="输入人物名称"
                  value={personName}
                  onChange={e => { setPersonName(e.target.value); setActiveKeyword(null) }}
                />
              </div>
            )}

            <div className="edict-actions">
              <button className="edict-cancel" onClick={onCancel}>取消</button>
              <button
                className="edict-seal-btn"
                disabled={!canIssue || !paramReady || loading}
                onClick={handleSeal}
              >颁布诏书</button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="seal-anim"
            className="edict-panel sealing"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 1 }}
            animate={{ opacity: 1 }}
          >
            <motion.div
              className="seal-stamp"
              initial={{ scale: 3, opacity: 0 }}
              animate={stampAnimate}
              transition={{ duration: 0.4, ease: 'easeOut' }}
              onAnimationComplete={onSealLanded}
            >
              御批
              {inkSpread && (
                <motion.div
                  className="seal-ink-spread"
                  initial={{ opacity: 0, scale: 0.3 }}
                  animate={{ opacity: 0, scale: 1.2 }}
                  transition={{ duration: 0.6 }}
                />
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
