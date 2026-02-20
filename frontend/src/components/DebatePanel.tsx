import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { DebateResult, StructuredDecree } from '../types/game'
import { Portrait } from '../shared/components/Portrait'

interface Props {
  result: DebateResult
  topic: string
  onAdopt: (decree: StructuredDecree, keywords: string[]) => void
  onSilence: () => void
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
            <Portrait name={result.minister_a.name} faction={result.minister_a.faction} />
            <div className="dm-name">{result.minister_a.name}</div>
            <div className="dm-faction">{result.minister_a.faction}</div>
            <div className="dm-summary">{result.minister_a.position_summary}</div>
          </div>
          <div className="debate-minister-col">
            <Portrait name={result.minister_b.name} faction={result.minister_b.faction} />
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
