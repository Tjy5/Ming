import { useState } from 'react'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { Memorial } from '../types/game'

interface Props {
  memorials: Memorial[]
  resolving?: boolean
  onResolve: (id: string, action: 'approved' | 'rejected' | 'deferred') => void
  onClose: () => void
}

const URGENCY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2 }
const URGENCY_LABEL: Record<string, string> = { critical: '紧急', high: '重要', medium: '一般' }
const URGENCY_CLASS: Record<string, string> = { critical: 'urg-critical', high: 'urg-high', medium: 'urg-medium' }

function sortByUrgency(a: Memorial, b: Memorial) {
  return (URGENCY_ORDER[a.urgency] ?? 3) - (URGENCY_ORDER[b.urgency] ?? 3)
}

export default function MemorialPanel({ memorials, resolving = false, onResolve, onClose }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const sorted = [...memorials].sort(sortByUrgency)

  return (
    <div className="modal-overlay" onClick={onClose}>
      <motion.div
        className="modal memorial-modal"
        onClick={e => e.stopPropagation()}
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
      >
        <h3 className="memorial-header">奏折批阅</h3>
        {sorted.length === 0 ? (
          <div className="memorial-empty">暂无待批奏折</div>
        ) : (
          <div className="memorial-list">
            {sorted.map(m => {
              const expanded = expandedId === m.id
              const actionable = m.status === 'pending' || m.status === 'deferred'
              return (
                <div key={m.id} className={`memorial-card ${URGENCY_CLASS[m.urgency] ?? ''}`}>
                  <div className="memorial-card-head" onClick={() => setExpandedId(expanded ? null : m.id)}>
                    <span className={`memorial-urg ${URGENCY_CLASS[m.urgency] ?? ''}`}>
                      {URGENCY_LABEL[m.urgency] ?? m.urgency}
                    </span>
                    <div className="memorial-card-info">
                      <span className="memorial-title">{m.title}</span>
                      <span className="memorial-author">{m.author_name}（{m.author_faction}）</span>
                    </div>
                    <span className="memorial-expand">{expanded ? '▼' : '▶'}</span>
                  </div>
                  {expanded && (
                    <div className="memorial-detail">
                      <div className="memorial-content">
                        <Markdown>{m.content}</Markdown>
                      </div>
                      <div className="memorial-reason">触发: {m.trigger_reason}</div>
                      {actionable && (
                        <div className="memorial-actions">
                          <button className="mem-btn mem-approve" disabled={resolving} onClick={() => onResolve(m.id, 'approved')}>准奏</button>
                          <button className="mem-btn mem-reject" disabled={resolving} onClick={() => onResolve(m.id, 'rejected')}>驳回</button>
                          <button className="mem-btn mem-defer" disabled={resolving} onClick={() => onResolve(m.id, 'deferred')}>留中</button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
        <div className="modal-actions">
          <button className="modal-btn primary" onClick={onClose}>退出批阅</button>
        </div>
      </motion.div>
    </div>
  )
}
