import { useState } from 'react'
import { FACTION_COLORS } from '../shared/constants/factions'
import { POSITION_DESCRIPTIONS } from '../shared/constants/positions'
import type { Minister } from '../types/game'

interface Props {
  ministers: Minister[]
  onClose: () => void
  onAppoint: (name: string, position: string) => Promise<void>
}

// 元末吴王幕府官职树（与后端 models/positions.py POSITION_REGISTRY 对齐）
const TREE = [
  { group: '中书省', leaves: ['左丞相', '右丞相', '平章政事', '左丞', '右丞', '参知政事'] },
  { group: '大都督府', leaves: ['大都督', '同知都督'] },
  { group: '御史台', leaves: ['御史大夫', '治书侍御史'] },
  { group: '幕府文职', leaves: ['中书参政', '太史令', '博士', '都事', '郎中', '员外郎', '经历', '儒学提举'] },
  { group: '军职', leaves: ['元帅', '总管', '判官', '参军', '万户', '镇抚', '千户', '检校'] },
  { group: '勋爵', leaves: ['吴国公', '太师', '太尉', '司徒', '司空'] },
  { group: '内廷', leaves: ['宣徽使', '内史监令'] }
]

function positionMatchesLeaf(position: string, leaf: string): boolean {
  return position === leaf
}

const EUNUCH_POSITIONS = new Set([
  '宣徽使',
  '内史监令'
])

const NOBLE_POSITIONS = ['吴国公', '太师', '太尉', '司徒', '司空']

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
      const isNoblePos = NOBLE_POSITIONS.includes(position)

      if (isNoble && !isNoblePos) return false
      if (!isNoble && isNoblePos) return false

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
          <span className="orm-title">官职补缺与百科</span>
          <button className="toolbar-btn" onClick={onClose}>✕</button>
        </div>

        <div className="orm-main-content">
          {/* Left Column: Position List */}
          <div className="orm-sidebar">
            {TREE.map(({ group, leaves }) => (
              <div key={group} className="orm-group">
                <div className="orm-group-label">{group}</div>
                <div className="orm-side-leaves">
                  {leaves.map(leaf => {
                    const holders = ministers.filter(m => m.positions?.some(p => positionMatchesLeaf(p, leaf)) && m.status === 'active')
                    const isActive = expandedLeaf === leaf
                    return (
                      <div
                        key={leaf}
                        className={`orm-side-leaf${isActive ? ' active' : ''}${holders.length === 0 ? ' vacant' : ''}`}
                        onClick={() => setExpandedLeaf(leaf)}
                      >
                        <span className="name">{leaf}</span>
                        <span className="holder-count">
                          {holders.length > 0 ? holders[0].name : '空缺'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>

          {/* Right Column: Detailed View */}
          <div className="orm-details">
            {expandedLeaf ? (
              <>
                <div className="orm-details-header">
                  <h3>{expandedLeaf}</h3>
                  <div className="orm-holders-list">
                    当前任职：
                    {ministers
                      .filter(m => m.positions?.some(p => positionMatchesLeaf(p, expandedLeaf)) && m.status === 'active')
                      .map(m => m.name).join('、') || '暂无'}
                  </div>
                </div>

                {POSITION_DESCRIPTIONS[expandedLeaf] && (
                  <div className="orm-position-encyclopedic">
                    <div className="ency-label">【官职百科】</div>
                    <div className="ency-content">{POSITION_DESCRIPTIONS[expandedLeaf]}</div>
                  </div>
                )}

                <div className="orm-candidates-section">
                  <div className="section-title">任命候补</div>
                  <div className="orm-candidates-list">
                    {getEligibleMinisters(expandedLeaf).length === 0 ? (
                      <div className="orm-empty">无可用合规大臣</div>
                    ) : (
                      getEligibleMinisters(expandedLeaf).map(m => (
                        <button
                          key={m.name}
                          className="orm-candidate-card"
                          disabled={appointing}
                          onClick={() => handleAppoint(m.name, expandedLeaf)}
                        >
                          <div className="c-info">
                            <span className="c-name" style={{ color: FACTION_COLORS[m.faction] ?? 'var(--text-main)' }}>
                              {m.name}
                            </span>
                            {m.positions?.length > 0 && <span className="c-current-pos">({m.positions.join('、')})</span>}
                          </div>
                          <div className="c-abilities">
                            政 {m.abilities.civil} | 武 {m.abilities.military} | 外 {m.abilities.diplomacy}
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="orm-no-selection">
                请从左侧选择一个官职以查看详情或进行任命
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
