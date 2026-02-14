import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { GameState, DecreeType, StructuredDecree, PersonnelAction } from '../types/game'
import { DECREE_LABELS, REGION_NAMES, DIPLOMACY_TARGETS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'

interface Props {
  type: DecreeType
  state: GameState
  loading: boolean
  onConfirm: (decree: StructuredDecree) => void
  onCancel: () => void
}

export default function EdictWritingPanel({ type, state, loading, onConfirm, onCancel }: Props) {
  const [target, setTarget] = useState<string | null>(null)
  const [subAction, setSubAction] = useState<PersonnelAction>('appoint')
  const [personName, setPersonName] = useState('')
  const [sealing, setSealing] = useState(false)
  const submitted = useRef(false)

  const canIssue = checkPrecondition(state, type)
  const needsTarget = type === 'disaster_relief' || type === 'diplomacy' || type === 'personnel'
  const paramReady = type === 'personnel' ? !!personName.trim() : needsTarget ? !!target : true

  function handleSeal() {
    if (!canIssue || !paramReady || sealing) return
    setSealing(true)
  }

  function buildDecree(): StructuredDecree {
    if (type === 'personnel') return { type, target: personName.trim(), sub_action: subAction }
    if (target) return { type, target }
    return { type }
  }

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
            transition={{ duration: 0.3 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="edict-header">{DECREE_LABELS[type]}</div>

            {!canIssue && (
              <div className="edict-warn">{PRECONDITION_MESSAGES[type]}</div>
            )}

            {type === 'disaster_relief' && (
              <div className="edict-targets">
                {REGION_NAMES.map(name => (
                  <button
                    key={name}
                    className={`edict-target-btn${target === name ? ' selected' : ''}`}
                    onClick={() => setTarget(name)}
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
                    onClick={() => setTarget(name)}
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
                  onChange={e => setPersonName(e.target.value)}
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
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.4, ease: 'easeOut' }}
              onAnimationComplete={() => {
                if (submitted.current) return
                submitted.current = true
                setTimeout(() => onConfirm(buildDecree()), 600)
              }}
            >
              御批
            </motion.div>
            <motion.div
              className="edict-header"
              animate={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.6, delay: 0.4 }}
            >
              {DECREE_LABELS[type]}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
