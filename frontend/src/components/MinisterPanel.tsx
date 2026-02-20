import { useState, useEffect, useMemo, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Minister, MinisterAbilities, MinisterReaction } from '../types/game'
import { FACTION_COLORS } from '../shared/constants/factions'
import { Portrait } from '../shared/components/Portrait'

interface Props {
  ministers?: Minister[] | null
  reactions?: MinisterReaction[]
  onMinisterClick?: (minister: Minister) => void
}

const FACTION_ORDER = [
  '东林党', '阉党残余', '勋贵集团', '辽东边将',
  '中原剿匪系', '温体仁派', '周延儒派', '中立派',
]

const ABILITY_LABELS: { key: keyof MinisterAbilities; label: string; color: string }[] = [
  { key: 'civil', label: '文', color: 'var(--green)' },
  { key: 'military', label: '武', color: 'var(--red)' },
  { key: 'diplomacy', label: '略', color: 'var(--accent-gold)' },
]

function loyaltyColor(v: number) {
  if (v > 60) return 'var(--green)'
  if (v >= 30) return 'var(--yellow)'
  return 'var(--red)'
}

function MinisterCard({ minister, reaction, onClick }: {
  minister: Minister
  reaction?: MinisterReaction
  onClick?: (m: Minister) => void
}) {
  const idle = minister.status === 'idle'
  const notEntered = minister.status === 'not_yet_entered'
  const [showReaction, setShowReaction] = useState(false)

  const reactionKey = reaction ? `${reaction.minister_name}:${reaction.reaction_type}:${reaction.loyalty_change}` : ''

  useEffect(() => {
    if (!reactionKey) return
    setShowReaction(true)
    const t = setTimeout(() => setShowReaction(false), 3000)
    return () => clearTimeout(t)
  }, [reactionKey])

  const cls = ['mp-card']
  if (idle) cls.push('mp-idle')
  if (notEntered) cls.push('mp-not-entered')
  if (onClick) cls.push('mp-clickable')

  return (
    <div className={cls.join(' ')} onClick={() => onClick?.(minister)}>
      <Portrait minister={minister} />
      <div className="mp-info">
        <div className="mp-name">
          {minister.name}
          {minister.position && <span className="mp-position">{minister.position}</span>}
        </div>
        <div className="mp-tags">
          {minister.personality_tags.map(t => (
            <span key={t} className="mp-tag">{t}</span>
          ))}
        </div>
        <div className="mp-abilities">
          {ABILITY_LABELS.map(({ key, label, color }) => (
            <div key={key} className="mp-ability-row">
              <span className="mp-ability-label">{label}</span>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{ width: `${minister.abilities[key]}%`, backgroundColor: color }}
                />
              </div>
              <span className="mp-ability-val">{minister.abilities[key]}</span>
            </div>
          ))}
          <div className={`mp-ability-row mp-loyalty-bar${minister.loyalty < 30 ? ' loyalty-low' : ''}`} style={{ marginTop: 2 }}>
            <span className="mp-ability-label">忠</span>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${minister.loyalty}%`, backgroundColor: loyaltyColor(minister.loyalty) }}
              />
            </div>
            <span className="mp-ability-val">{minister.loyalty}</span>
          </div>
        </div>
      </div>
      {idle && <div className="mp-idle-badge">赋闲</div>}
      {notEntered && <div className="mp-not-entered-badge">未入朝</div>}
      <AnimatePresence>
        {showReaction && reaction && (
          <motion.div
            className={`mp-reaction-icon ${reaction.reaction_type === 'support' ? 'mp-reaction-support' : 'mp-reaction-oppose'}`}
            initial={{ opacity: 0, scale: 0 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
          >
            {reaction.reaction_type === 'support' ? '↑' : '↓'}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function MinisterPanel({ ministers, reactions, onMinisterClick }: Props) {
  const [searchTerm, setSearchTerm] = useState('')
  const [showNotEntered, setShowNotEntered] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(FACTION_ORDER.slice(0, 3)))

  const toggleFaction = useCallback((fname: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(fname)) next.delete(fname)
      else next.add(fname)
      return next
    })
  }, [])

  const filtered = useMemo(() => {
    if (!Array.isArray(ministers)) return []
    return ministers.filter(m => {
      if (m.status === 'removed') return false
      if (!showNotEntered && m.status === 'not_yet_entered') return false
      if (searchTerm) {
        const q = searchTerm.toLowerCase()
        return m.name.toLowerCase().includes(q) || m.position.toLowerCase().includes(q)
      }
      return true
    })
  }, [ministers, searchTerm, showNotEntered])

  const reactionMap = useMemo(() => {
    const m = new Map<string, MinisterReaction>()
    reactions?.forEach(r => m.set(r.minister_name, r))
    return m
  }, [reactions])

  const grouped = useMemo(() => {
    return filtered.reduce<Record<string, Minister[]>>((acc, m) => {
      ;(acc[m.faction] ??= []).push(m)
      return acc
    }, {})
  }, [filtered])

  const knownFactions = FACTION_ORDER.filter(f => grouped[f]?.length)
  const unknownFactions = Object.keys(grouped)
    .filter(f => !FACTION_ORDER.includes(f))
    .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  const displayFactions = [...knownFactions, ...unknownFactions]

  if (!displayFactions.length && !searchTerm) {
    return <div className="minister-panel minister-panel-empty">暂无大臣数据</div>
  }

  return (
    <div className="minister-panel">
      <div className="mp-controls">
        <input
          className="mp-search"
          placeholder="搜索姓名/官职..."
          value={searchTerm}
          onChange={e => setSearchTerm(e.target.value)}
        />
        <label className="mp-toggle">
          <input type="checkbox" checked={showNotEntered} onChange={e => setShowNotEntered(e.target.checked)} />
          <span>未登场</span>
        </label>
      </div>

      {displayFactions.map(fname => {
        const members = grouped[fname]
        if (!members?.length) return null
        const isExpanded = expanded.has(fname)
        return (
          <div key={fname} className="mp-faction-group">
            <div
              className="mp-faction-header"
              style={{ borderLeftColor: FACTION_COLORS[fname] ?? '#555' }}
              onClick={() => toggleFaction(fname)}
            >
              <span>{fname} ({members.length})</span>
              <span className="mp-faction-arrow">{isExpanded ? '▼' : '▶'}</span>
            </div>
            {isExpanded && members.map(m => (
              <MinisterCard key={m.name} minister={m} reaction={reactionMap.get(m.name)} onClick={onMinisterClick} />
            ))}
          </div>
        )
      })}

      {displayFactions.length === 0 && searchTerm && (
        <div className="mp-no-result">无匹配结果</div>
      )}
    </div>
  )
}
