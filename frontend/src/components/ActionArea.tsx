import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { GameState, DecreeType, StructuredDecree } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import EdictWritingPanel from './EdictWritingPanel'

interface Props {
  state: GameState
  loading: boolean
  onDecree: (decrees: StructuredDecree[]) => void
  onFreeText: (text: string) => void
}

type Category = '内政' | '军事' | '外交' | '其他'

const CATEGORIES: Category[] = ['内政', '军事', '外交', '其他']

const CATEGORY_DECREES: Record<Category, DecreeType[]> = {
  军事: ['recruit_troops', 'disband_troops'],
  内政: ['tax_increase', 'tax_decrease', 'disaster_relief', 'harsh_punishment'],
  外交: ['diplomacy'],
  其他: ['personnel'],
}

export default function ActionArea({ state, loading, onDecree, onFreeText }: Props) {
  const [text, setText] = useState('')
  const [tab, setTab] = useState<Category>('内政')
  const [edictType, setEdictType] = useState<DecreeType | null>(null)

  function handleSubmit() {
    const t = text.trim()
    if (!t) return
    onFreeText(t)
    setText('')
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
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            className="decree-grid"
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ duration: 0.15 }}
          >
            {CATEGORY_DECREES[tab].map(type => {
              const ok = checkPrecondition(state, type)
              return (
                <button
                  key={type}
                  className="decree-btn"
                  disabled={!ok || loading}
                  title={ok ? DECREE_LABELS[type] : PRECONDITION_MESSAGES[type]}
                  onClick={() => setEdictType(type)}
                >
                  {DECREE_LABELS[type]}
                </button>
              )
            })}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="text-input-row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && handleSubmit()}
          placeholder="输入政令（如：加征辽饷）"
          disabled={loading}
        />
        <button onClick={handleSubmit} disabled={loading || !text.trim()}>下旨</button>
      </div>

      {edictType && (
        <EdictWritingPanel
          type={edictType}
          state={state}
          loading={loading}
          onConfirm={(decree) => { setEdictType(null); onDecree([decree]) }}
          onCancel={() => setEdictType(null)}
        />
      )}
    </div>
  )
}
