import { useState } from 'react'
import { FACTION_COLORS } from '../shared/constants/factions'
import type { Minister } from '../types/game'

interface Props {
  ministers: Minister[]
  onClose: () => void
  onAppoint: (name: string, position: string) => Promise<void>
}

const TREE = [
  { group: '内阁', leaves: ['首辅大学士', '次辅大学士', '东阁大学士', '文渊阁大学士', '武英殿大学士'] },
  { group: '六部', leaves: ['吏部尚书', '户部尚书', '礼部尚书', '兵部尚书', '刑部尚书', '工部尚书', '吏部侍郎', '户部侍郎', '礼部侍郎', '兵部侍郎', '刑部侍郎', '工部侍郎', '吏部主事', '户部主事', '礼部主事', '兵部主事', '刑部主事', '工部主事', '吏科给事中', '户科给事中', '礼科给事中', '兵科给事中', '刑科给事中', '工科给事中'] },
  { group: '都察院', leaves: ['左都御史', '左副都御史', '右佥都御史', '监察御史'] },
  { group: '锦衣卫', leaves: ['指挥使'] },
  { group: '地方', leaves: ['辽东巡抚', '河南巡抚', '福建巡抚', '登莱巡抚', '宣府总兵', '山海关总兵', '东江总兵', '辽东副总兵'] },
  { group: '京官', leaves: ['翰林学士', '太仆寺卿', '大理寺卿', '通政使', '翰林编修', '翰林修撰', '顺天府尹', '光禄寺卿'] },
  { group: '勋戚', leaves: ['成国公', '英国公', '魏国公', '定国公', '驸马都尉', '嘉定伯', '襄城伯'] },
  { group: '内廷', leaves: ['司礼监掌印太监', '司礼监太监', '司礼监秉笔太监'] }
]

function positionMatchesLeaf(position: string, leaf: string): boolean {
  return position === leaf
}

const EUNUCH_POSITIONS = new Set([
  '司礼监掌印太监',
  '司礼监太监',
  '司礼监秉笔太监'
])

export default function OfficialRankModal({ ministers, onClose, onAppoint }: Props) {
  const [expandedLeaf, setExpandedLeaf] = useState<string | null>(null)
  const [appointing, setAppointing] = useState(false)

  function getEligibleMinisters(position: string) {
    const isEunuchPos = EUNUCH_POSITIONS.has(position)
    return ministers.filter(m => {
      if (m.status !== 'active') return false
      if (!!m.is_eunuch !== isEunuchPos) return false
      if (m.positions?.some(p => positionMatchesLeaf(p, position))) return false

      const tags = m.personality_tags || []
      const isNoble = tags.includes('勋贵') || m.faction === '勋贵集团'
      const isHanlin = tags.includes('翰林')
      const isMilitary = tags.includes('武将')

      const isNoblePos = ['成国公', '英国公', '魏国公', '定国公', '驸马都尉', '嘉定伯', '襄城伯'].includes(position)
      const isCabinetPos = position.includes('大学士')
      const isGovernorPos = position.includes('巡抚')

      if (isNoble && !isNoblePos) return false
      if (!isNoble && isNoblePos) return false
      if (isCabinetPos && !isHanlin) return false
      if (isGovernorPos && isMilitary) return false

      return true
    })
  }

  async function handleAppoint(name: string, position: string) {
    if (appointing) return
    const holders = ministers.filter(m => m.positions?.some(p => positionMatchesLeaf(p, position)) && m.status === 'active')
    const candidate = ministers.find(m => m.name === name)

    // Build confirmation message
    let confirmMsg = `确认将 ${name} 任命为 ${position}？`
    if (holders.length > 0) {
      confirmMsg += `\n原任职者 ${holders.map(h => h.name).join('、')} 将失去该职位。`
    }
    // Task 5.5: Warn if candidate already has positions (multi-position scenario)
    if (candidate && candidate.positions?.length > 0) {
      confirmMsg += `\n\n${name} 现任职位：${candidate.positions.join('、')}`
    }

    if (!window.confirm(confirmMsg)) return
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
                  const holders = ministers.filter(m => m.positions?.some(p => positionMatchesLeaf(p, leaf)) && m.status === 'active')
                  const isExpanded = expandedLeaf === leaf
                  return (
                    <div key={leaf} className="orm-leaf-wrap">
                      <div
                        className={`orm-leaf${isExpanded ? ' orm-leaf-active' : ''}`}
                        onClick={() => setExpandedLeaf(isExpanded ? null : leaf)}
                      >
                        <span className="orm-leaf-name">{leaf}</span>
                        <span className={`orm-holders${holders.length === 0 ? ' orm-vacant' : ''}`}>
                          {holders.length > 0
                            ? holders.map(h => `${h.name}${h.positions?.length > 1 ? ` (${h.positions.join('、')})` : ''}`).join('、')
                            : '空缺'}
                        </span>
                      </div>
                      {isExpanded && (
                        <div className="orm-panel">
                          {getEligibleMinisters(leaf).length === 0
                            ? <span className="orm-empty">无可用大臣</span>
                            : getEligibleMinisters(leaf).map(m => (
                              <button
                                key={m.name}
                                className="orm-candidate"
                                disabled={appointing}
                                onClick={() => handleAppoint(m.name, leaf)}
                              >
                                <span style={{ color: FACTION_COLORS[m.faction] ?? 'var(--text-main)' }}>
                                  {m.name}
                                  {m.positions?.length > 0 && <span className="orm-candidate-positions"> ({m.positions.join('、')})</span>}
                                </span>
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
