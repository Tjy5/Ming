import type { DecreeType } from '../types/game'
import { DEBATE_TOPICS } from '../types/game'

interface Props {
  category: DecreeType
  onSelect: (topic: string, decreeType: DecreeType) => void
}

export default function TopicSelector({ category, onSelect }: Props) {
  const topics = DEBATE_TOPICS[category] ?? []
  if (!topics.length) return null

  return (
    <>
      <div className="topic-popover">
        {topics.map(t => (
          <button
            key={t.topic}
            className="topic-item"
            onClick={() => onSelect(t.topic, t.decreeType)}
          >
            {t.topic}
          </button>
        ))}
      </div>
    </>
  )
}
