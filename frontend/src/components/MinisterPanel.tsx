import { useState, useEffect, useMemo, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import type { Minister, MinisterAbilities, MinisterReaction } from '../types/game'
import { FACTION_COLORS } from '../shared/constants/factions'
import { Portrait } from '../shared/components/Portrait'
import {
  DEFAULT_EXPANDED_FACTIONS,
  filterPanelMinisters,
  getDisplayFactions,
  groupMinistersByFaction,
  toggleExpandedFaction,
} from './ministerPanelLogic'

interface Props {
  ministers?: Minister[] | null
  reactions?: MinisterReaction[]
  onMinisterClick?: (minister: Minister) => void
}

const ABILITY_LABELS: { key: keyof MinisterAbilities; label: string; color: string }[] = [
  { key: 'civil', label: '文', color: 'var(--green)' },
  { key: 'military', label: '武', color: 'var(--red)' },
  { key: 'diplomacy', label: '略', color: 'var(--accent-gold)' },
]

// Helper to detect NOBLE positions by suffix (公、侯、伯)
function isNoblePosition(position: string): boolean {
  return /[公侯伯]$/.test(position)
}

// Helper to classify positions for styling
function getPositionClass(position: string, isEunuch: boolean): string {
  if (isEunuch) return 'mp-pos-eunuch'
  if (isNoblePosition(position)) return 'mp-pos-noble'
  return ''
}

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
  const onMission = minister.status === 'on_mission'
  const [showReaction, setShowReaction] = useState(false)

  const reactionKey = reaction ? `${reaction.minister_name}:${reaction.reaction_type}:${reaction.loyalty_change}` : ''

  const [prevReactionKey, setPrevReactionKey] = useState('')
  if (reactionKey !== prevReactionKey) {
    setPrevReactionKey(reactionKey)
    if (reactionKey) setShowReaction(true)
  }

  useEffect(() => {
    if (!reactionKey) return
    const t = setTimeout(() => setShowReaction(false), 3000)
    return () => clearTimeout(t)
  }, [reactionKey])

  const cls = ['mp-card']
  if (idle) cls.push('mp-idle')
  if (notEntered) cls.push('mp-not-entered')
  if (onMission) cls.push('mp-on-mission')
  if (onClick && !onMission) cls.push('mp-clickable')

  return (
    <div className={cls.join(' ')} onClick={() => !onMission && onClick?.(minister)}>
      <Portrait minister={minister} />
      <div className="mp-info">
        <div className="mp-name">
          {minister.name}
          {minister.is_eunuch && <span className="mp-eunuch-badge">内廷</span>}
        </div>
        {minister.positions?.length > 0 && (
          <div className="mp-positions">
            {minister.positions.map((pos, idx) => (
              <span key={idx} className={`mp-position-tag ${getPositionClass(pos, minister.is_eunuch)}`}>
                {pos}
              </span>
            ))}
          </div>
        )}
        <div className="mp-tags">
          {minister.personality_tags.map(t => (
            <span key={t} className="mp-tag">{t}</span>
          ))}
        </div>
        {minister.historical_note && <div className="mp-historical-note">{minister.historical_note}</div>}
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
      {onMission && <div className="mp-on-mission-badge">出使中</div>}
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
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(DEFAULT_EXPANDED_FACTIONS))

  const toggleFaction = useCallback((fname: string) => {
    setExpanded(prev => toggleExpandedFaction(prev, fname))
  }, [])

  const filtered = useMemo(
    () => filterPanelMinisters(ministers, searchTerm, showNotEntered),
    [ministers, searchTerm, showNotEntered],
  )

  const reactionMap = useMemo(() => {
    const m = new Map<string, MinisterReaction>()
    reactions?.forEach(r => m.set(r.minister_name, r))
    return m
  }, [reactions])

  const grouped = useMemo(() => groupMinistersByFaction(filtered), [filtered])
  const displayFactions = useMemo(() => getDisplayFactions(grouped), [grouped])

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
