import { useState } from 'react'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { DebateResult, StructuredDecree } from '../types/game'
import { getPortraitUrl } from '../utils/portraits'

interface Props {
  result: DebateResult
  topic: string
  onAdopt: (decree: StructuredDecree, keywords: string[]) => void
  onSilence: () => void
}

const FACTION_COLORS: Record<string, string> = {
  '东林党': '#4a7c59',
  '阉党残余': '#8b4513',
  '勋贵集团': '#6b5b95',
  '边将势力': '#4682b4',
}

function MinisterAvatar({ name, faction }: { name: string; faction: string }) {
  const [loadFailed, setLoadFailed] = useState(false)
  if (!loadFailed) {
    return (
      <img
        className="mp-avatar"
        src={getPortraitUrl(name)}
        alt={name}
        onError={() => setLoadFailed(true)}
      />
    )
  }

  const bg = FACTION_COLORS[faction] ?? '#555'
  return (
    <div className="mp-avatar mp-placeholder" style={{ backgroundColor: bg }}>
      {name.charAt(0) || '?'}
    </div>
  )
}

export default function DebatePanel({ result, topic, onAdopt, onSilence }: Props) {
  return (
    <div className="modal-overlay" onClick={onSilence}>
      <motion.div
        className="debate-modal"
        initial={{ scale: 0.85, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.85, opacity: 0 }}
        transition={{ duration: 0.25 }}
        onClick={e => e.stopPropagation()}
      >
        <div className="debate-topic">{topic}</div>

        <div className="debate-ministers">
          <div className="debate-minister-col">
            <MinisterAvatar name={result.minister_a.name} faction={result.minister_a.faction} />
            <div className="dm-name">{result.minister_a.name}</div>
            <div className="dm-faction">{result.minister_a.faction}</div>
            <div className="dm-summary">{result.minister_a.position_summary}</div>
          </div>
          <div className="debate-minister-col">
            <MinisterAvatar name={result.minister_b.name} faction={result.minister_b.faction} />
            <div className="dm-name">{result.minister_b.name}</div>
            <div className="dm-faction">{result.minister_b.faction}</div>
            <div className="dm-summary">{result.minister_b.position_summary}</div>
          </div>
        </div>

        <div className="debate-text">
          <Markdown>{result.debate_text}</Markdown>
        </div>

        <div className="debate-actions">
          <button
            className="debate-adopt"
            onClick={() => onAdopt(result.option_a, result.keywords)}
          >
            采纳甲方
          </button>
          <button
            className="debate-adopt"
            onClick={() => onAdopt(result.option_b, result.keywords)}
          >
            采纳乙方
          </button>
          <button className="debate-silence" onClick={onSilence}>
            喝止争吵
          </button>
        </div>
      </motion.div>
    </div>
  )
}
