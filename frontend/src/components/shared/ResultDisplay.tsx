import type { FC } from 'react'
import { motion } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import type { MemorialResolutionResult } from '../../types/game'

interface ResultDisplayProps {
  result: MemorialResolutionResult
}

export const ResultDisplay: FC<ResultDisplayProps> = ({ result }) => {
  const { narrative, delta, minister_reactions } = result

  // 检查是否所有字段都为空
  const isEmpty = !narrative && (!delta || Object.keys(delta).length === 0) && (!minister_reactions || minister_reactions.length === 0)

  if (isEmpty) {
    return (
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: 'auto' }}
        exit={{ opacity: 0, height: 0 }}
        transition={{ duration: 0.3 }}
        className="result-display"
      >
        <p>批复已处理</p>
      </motion.div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.3 }}
      className="result-display"
    >
      {narrative && (
        <div className="narrative-text">
          <ReactMarkdown>{narrative}</ReactMarkdown>
        </div>
      )}

      {delta && Object.keys(delta).length > 0 && (
        <div className="delta-list">
          {Object.entries(delta).map(([key, value]) => {
            const numValue = typeof value === 'number' ? value : 0
            return (
              <div key={key} className="delta-item">
                <span className="delta-key">{key}</span>: <span className="delta-value">{numValue > 0 ? '+' : ''}{numValue}</span>
              </div>
            )
          })}
        </div>
      )}

      {minister_reactions && minister_reactions.length > 0 && (
        <div className="narrative-reactions">
          {minister_reactions.map((reaction, index) => (
            <div key={index} className="reaction-item">
              <strong>{reaction.minister_name}</strong>: {reaction.reaction_text}
            </div>
          ))}
        </div>
      )}
    </motion.div>
  )
}

export default ResultDisplay
