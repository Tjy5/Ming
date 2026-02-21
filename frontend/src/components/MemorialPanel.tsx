import { useState, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { Memorial } from '../types/game'
import ResultDisplay from './shared/ResultDisplay'

interface Props {
  memorials: Memorial[]
  resolving?: boolean
  onResolve: (id: string, action: 'approved' | 'rejected' | 'deferred') => Promise<{ narrative?: string, delta?: Record<string, number> } | void>
  onClose: () => void
}

const URGENCY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2 }
const URGENCY_LABEL: Record<string, string> = { critical: '紧急', high: '重要', medium: '一般' }
const URGENCY_CLASS: Record<string, string> = { critical: 'urg-critical', high: 'urg-high', medium: 'urg-medium' }


function sortByUrgency(a: Memorial, b: Memorial) {
  // 可操作状态优先（pending/deferred），已结案状态（approved/rejected）靠后
  const aActionable = (a.status === 'pending' || a.status === 'deferred') ? 0 : 1
  const bActionable = (b.status === 'pending' || b.status === 'deferred') ? 0 : 1
  if (aActionable !== bActionable) return aActionable - bActionable
  return (URGENCY_ORDER[a.urgency] ?? 3) - (URGENCY_ORDER[b.urgency] ?? 3)
}

export default function MemorialPanel({ memorials, resolving = false, onResolve, onClose }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const sorted = [...memorials].sort(sortByUrgency)

  useEffect(() => {
    if (expandedId && cardRefs.current[expandedId]) {
      requestAnimationFrame(() => {
        cardRefs.current[expandedId]?.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest'
        })
      })
    }
  }, [expandedId])

  const handleResolve = async (id: string, action: 'approved' | 'rejected' | 'deferred') => {
    await onResolve(id, action)
    setExpandedId(id)
  }

  const handleCardHeadClick = (id: string, expanded: boolean) => {
    setExpandedId(expanded ? null : id)
  }

  const handleCardHeadKeyDown = (e: React.KeyboardEvent, id: string, expanded: boolean) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleCardHeadClick(id, expanded)
    }
  }

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
                <div
                  key={m.id}
                  className={`memorial-card ${URGENCY_CLASS[m.urgency] ?? ''}`}
                  ref={(el) => {
                    if (el) cardRefs.current[m.id] = el
                  }}
                >
                  <div
                    className="memorial-card-head"
                    role="button"
                    tabIndex={0}
                    onClick={() => handleCardHeadClick(m.id, expanded)}
                    onKeyDown={(e) => handleCardHeadKeyDown(e, m.id, expanded)}
                    aria-expanded={expanded}
                    aria-label={`${m.title} - ${m.author_name}`}
                  >
                    <span className={`memorial-urg ${URGENCY_CLASS[m.urgency] ?? ''}`}>
                      {URGENCY_LABEL[m.urgency] ?? m.urgency}
                    </span>
                    <div className="memorial-card-info">
                      <span className="memorial-title">{m.title}</span>
                      {m.resolution_result ? (
                        <span className={`memorial-status-tag status-${m.resolution_result.action}`}>
                          {m.resolution_result.action === 'approved' ? '已批准' :
                            m.resolution_result.action === 'rejected' ? '已驳回' : '已缓议'}
                        </span>
                      ) : m.status === 'approved' ? (
                        <span className="memorial-status-tag status-approved">已批准</span>
                      ) : m.status === 'rejected' ? (
                        <span className="memorial-status-tag status-rejected">已驳回</span>
                      ) : null}
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
                      {m.resolution_result && (
                        <div className="memorial-result">
                          <ResultDisplay result={m.resolution_result} />
                        </div>
                      )}
                      {actionable && (
                        <div className="memorial-actions">
                          <button className="mem-btn mem-approve" disabled={resolving} onClick={() => handleResolve(m.id, 'approved')}>准奏</button>
                          <button className="mem-btn mem-reject" disabled={resolving} onClick={() => handleResolve(m.id, 'rejected')}>驳回</button>
                          <button className="mem-btn mem-defer" disabled={resolving} onClick={() => handleResolve(m.id, 'deferred')}>留中</button>
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
