import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { GameState, DecreeType, StructuredDecree, Capabilities } from '../types/game'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { checkPrecondition } from '../hooks/store'
import EdictWritingPanel from './EdictWritingPanel'
import TopicSelector from './TopicSelector'

interface Props {
  state: GameState
  loading: boolean
  capabilities: Capabilities
  hasBlockingEvent: boolean
  debateLoading: boolean
  onDecree: (decrees: StructuredDecree[]) => void
  onFreeText: (text: string) => void
  onDebateStart: (topic: string, category: DecreeType) => void
  prefilledDecree?: StructuredDecree | null
  prefilledKeywords?: string[]
  onPrefilledClear?: () => void
}

type Category = '内政' | '军事' | '外交' | '其他'

const CATEGORIES: Category[] = ['内政', '军事', '外交', '其他']

const CATEGORY_DECREES: Record<Category, DecreeType[]> = {
  军事: ['recruit_troops', 'disband_troops'],
  内政: ['tax_increase', 'tax_decrease', 'disaster_relief', 'harsh_punishment'],
  外交: ['diplomacy'],
  其他: ['personnel'],
}

const CATEGORY_TO_DECREE_TYPE: Record<Category, DecreeType> = {
  内政: 'tax_increase',
  军事: 'recruit_troops',
  外交: 'diplomacy',
  其他: 'personnel',
}

export default function ActionArea({
  state, loading, capabilities, hasBlockingEvent, debateLoading,
  onDecree, onFreeText, onDebateStart,
  prefilledDecree, prefilledKeywords, onPrefilledClear,
}: Props) {
  const [text, setText] = useState('')
  const [tab, setTab] = useState<Category>('内政')
  const [edictType, setEdictType] = useState<DecreeType | null>(null)
  const [showTopics, setShowTopics] = useState(false)

  // Open edict panel from prefilled decree (debate result)
  const activeEdictType = prefilledDecree ? prefilledDecree.type : edictType

  function handleSubmit() {
    const t = text.trim()
    if (!t) return
    onFreeText(t)
    setText('')
  }

  function handleTopicSelect(topic: string, decreeType: DecreeType) {
    setShowTopics(false)
    onDebateStart(topic, decreeType)
  }

  function handleEdictConfirm(decree: StructuredDecree) {
    if (prefilledDecree) onPrefilledClear?.()
    setEdictType(null)
    onDecree([decree])
  }

  function handleEdictCancel() {
    if (prefilledDecree) onPrefilledClear?.()
    setEdictType(null)
  }

  return (
    <div className="action-area">
      <div className="category-tabs">
        {CATEGORIES.map(c => (
          <button
            key={c}
            className={`cat-tab${tab === c ? ' active' : ''}`}
            onClick={() => {
              setTab(c)
              setShowTopics(false)
            }}
          >{c}</button>
        ))}
      </div>

      <div className="decree-tab-content">
        {capabilities.debate_supported && (
          <div style={{ position: 'relative' }}>
            <button
              className="debate-btn"
              disabled={loading || hasBlockingEvent || debateLoading}
              onClick={() => setShowTopics(v => !v)}
            >
              {debateLoading ? '廷推进行中...' : '廷推议事'}
            </button>
            {showTopics && (
              <TopicSelector
                category={CATEGORY_TO_DECREE_TYPE[tab]}
                onSelect={handleTopicSelect}
                onClose={() => setShowTopics(false)}
              />
            )}
          </div>
        )}

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

      {activeEdictType && (
        <EdictWritingPanel
          type={activeEdictType}
          state={state}
          loading={loading}
          prefilledDecree={prefilledDecree}
          keywords={prefilledKeywords}
          onConfirm={handleEdictConfirm}
          onCancel={handleEdictCancel}
        />
      )}
    </div>
  )
}
