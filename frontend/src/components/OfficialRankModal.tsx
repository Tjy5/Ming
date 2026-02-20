import { useState } from 'react'
import { FACTION_COLORS } from '../shared/constants/factions'
import type { Minister } from '../types/game'

interface Props {
  ministers: Minister[]
  onClose: () => void
  onAppoint: (name: string, position: string) => Promise<void>
}

const TREE = [
  { group: '内阁', leaves: ['首辅大学士', '次辅大学士', '群辅大学士'] },
  { group: '六部', leaves: ['吏部尚书', '吏部侍郎', '户部尚书', '户部侍郎', '礼部尚书', '礼部侍郎', '兵部尚书', '兵部侍郎', '刑部尚书', '刑部侍郎', '工部尚书', '工部侍郎'] },
  { group: '都察院', leaves: ['左都御史'] },
  { group: '锦衣卫', leaves: ['指挥使'] },
  { group: '地方', leaves: ['巡抚', '总兵'] },
]

export default function OfficialRankModal({ ministers, onClose, onAppoint }: Props) {
  const [expandedLeaf, setExpandedLeaf] = useState<string | null>(null)
  const [appointing, setAppointing] = useState(false)

  const idleMinisters = ministers.filter(m => m.status === 'idle')

  async function handleAppoint(name: string, position: string) {
    if (appointing) return
    const holders = ministers.filter(m => m.position === position && m.status === 'active')
    if (holders.length > 0) {
      if (!window.confirm(`确认将 ${name} 任命为 ${position}？原任职者将失去该职位。`)) return
    }
    setAppointing(true)
    try {
      await onAppoint(name, position)
      setExpandedLeaf(null)
    } finally {
      setAppointing(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal official-rank-modal" onClick={e => e.stopPropagation()}>
        <div className="orm-header">
          <span className="orm-title">官职补缺</span>
          <button className="toolbar-btn" onClick={onClose}>✕</button>
        </div>
        <div className="orm-body">
          {TREE.map(({ group, leaves }) => (
            <div key={group} className="orm-group">
              <div className="orm-group-label">{group}</div>
              <div className="orm-leaves">
                {leaves.map(leaf => {
                  const holders = ministers.filter(m => m.position === leaf && m.status === 'active')
                  const isExpanded = expandedLeaf === leaf
                  return (
                    <div key={leaf} className="orm-leaf-wrap">
                      <div
                        className={`orm-leaf${isExpanded ? ' orm-leaf-active' : ''}`}
                        onClick={() => setExpandedLeaf(isExpanded ? null : leaf)}
                      >
                        <span className="orm-leaf-name">{leaf}</span>
                        <span className={`orm-holders${holders.length === 0 ? ' orm-vacant' : ''}`}>
                          {holders.length > 0 ? holders.map(h => h.name).join('、') : '空缺'}
                        </span>
                      </div>
                      {isExpanded && (
                        <div className="orm-panel">
                          {idleMinisters.length === 0
                            ? <span className="orm-empty">无可用大臣</span>
                            : idleMinisters.map(m => (
                              <button
                                key={m.name}
                                className="orm-candidate"
                                disabled={appointing}
                                onClick={() => handleAppoint(m.name, leaf)}
                              >
                                <span style={{ color: FACTION_COLORS[m.faction] ?? 'var(--text-main)' }}>{m.name}</span>
                                <span className="orm-abilities">{m.abilities.civil}/{m.abilities.military}/{m.abilities.diplomacy}</span>
                              </button>
                            ))
                          }
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
