import { useState } from 'react'
import { motion } from 'framer-motion'
import Markdown from 'react-markdown'
import type { Memorial } from '../types/game'

interface Props {
  memorials: Memorial[]
  resolving?: boolean
  onResolve: (id: string, action: 'approved' | 'rejected' | 'deferred') => Promise<{ narrative?: string, delta?: Record<string, number> } | void>
  onClose: () => void
}

const URGENCY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2 }
const URGENCY_LABEL: Record<string, string> = { critical: '紧急', high: '重要', medium: '一般' }
const URGENCY_CLASS: Record<string, string> = { critical: 'urg-critical', high: 'urg-high', medium: 'urg-medium' }

const FIELD_LABELS: Record<string, string> = {
  national_treasury: '国库', imperial_treasury: '内帑', grain: '粮草',
  population: '人口', military_strength: '兵力', civil_morale: '民心',
  military_morale: '军心', court_prestige: '威望',
}

function resolveLabel(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]
  for (const field in FIELD_LABELS) {
    if (key.endsWith(`_${field}`)) return `${key.slice(0, key.length - field.length - 1)}${FIELD_LABELS[field]}`
  }
  return key
}

function sortByUrgency(a: Memorial, b: Memorial) {
  const aApproved = a.status === 'approved' ? 1 : 0
  const bApproved = b.status === 'approved' ? 1 : 0
  if (aApproved !== bApproved) return aApproved - bApproved
  return (URGENCY_ORDER[a.urgency] ?? 3) - (URGENCY_ORDER[b.urgency] ?? 3)
}

export default function MemorialPanel({ memorials, resolving = false, onResolve, onClose }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [resolveResults, setResolveResults] = useState<Record<string, { narrative: string, delta: Record<string, number>, action: string }>>({})
  const sorted = [...memorials].sort(sortByUrgency)

  const ACTION_LABELS: Record<string, string> = { approved: '已准奏', rejected: '已驳回', deferred: '已留中' }

  async function handleResolve(id: string, action: 'approved' | 'rejected' | 'deferred') {
    const res = await onResolve(id, action)
    setResolveResults(prev => ({ ...prev, [id]: { narrative: res?.narrative ?? '', delta: res?.delta ?? {}, action } }))
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
              const result = resolveResults[m.id]
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
                          <button className="mem-btn mem-approve" disabled={resolving} onClick={() => handleResolve(m.id, 'approved')}>准奏</button>
                          <button className="mem-btn mem-reject" disabled={resolving} onClick={() => handleResolve(m.id, 'rejected')}>驳回</button>
                          <button className="mem-btn mem-defer" disabled={resolving} onClick={() => handleResolve(m.id, 'deferred')}>留中</button>
                        </div>
                      )}
                    </div>
                  )}
                  {result && (
                    <div className="memorial-resolve-result">
                      <div className="res-action-label" style={{ fontWeight: 'bold', marginBottom: '4px', color: result.action === 'approved' ? '#4caf50' : result.action === 'rejected' ? '#ff9800' : '#90a4ae' }}>
                        {ACTION_LABELS[result.action] ?? result.action}
                      </div>
                      {result.narrative && <div className="res-narrative">{result.narrative}</div>}
                      {Object.keys(result.delta).length > 0 && (
                        <ul className="delta-list">
                          {Object.entries(result.delta).filter(([, v]) => v !== 0).map(([k, v]) => (
                            <li key={k}>
                              <span>{resolveLabel(k)}</span>
                              <span className={v > 0 ? 'delta-pos' : 'delta-neg'}>{v > 0 ? '+' : ''}{v}</span>
                            </li>
                          ))}
                        </ul>
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
