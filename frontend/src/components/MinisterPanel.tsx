import { useState } from 'react'
import type { Minister, MinisterAbilities } from '../types/game'
import { getPortraitUrl } from '../utils/portraits'

interface Props {
  ministers?: Minister[] | null
}

const FACTION_COLORS: Record<string, string> = {
  '东林党': '#4a7c59',
  '阉党残余': '#8b4513',
  '勋贵集团': '#6b5b95',
  '边将势力': '#4682b4',
}

const ABILITY_LABELS: { key: keyof MinisterAbilities; label: string; color: string }[] = [
  { key: 'civil', label: '文', color: 'var(--green)' },
  { key: 'military', label: '武', color: 'var(--red)' },
  { key: 'diplomacy', label: '略', color: 'var(--accent-gold)' },
]

function Placeholder({ name, faction }: { name: string; faction: string }) {
  const bg = FACTION_COLORS[faction] ?? '#555'
  return (
    <div className="mp-avatar mp-placeholder" style={{ backgroundColor: bg }}>
      {name.charAt(0) || '?'}
    </div>
  )
}

function Portrait({ minister }: { minister: Minister }) {
  const [loadFailed, setLoadFailed] = useState(false)

  if (loadFailed) {
    return <Placeholder name={minister.name} faction={minister.faction} />
  }

  return (
    <img
      className="mp-avatar"
      src={getPortraitUrl(minister.name)}
      alt={minister.name}
      onError={() => setLoadFailed(true)}
    />
  )
}

function MinisterCard({ minister }: { minister: Minister }) {
  const idle = minister.status === 'idle'
  return (
    <div className={`mp-card${idle ? ' mp-idle' : ''}`}>
      <Portrait minister={minister} />
      <div className="mp-info">
        <div className="mp-name">{minister.name}</div>
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
        </div>
      </div>
      {idle && <div className="mp-idle-badge">赋闲</div>}
    </div>
  )
}

export default function MinisterPanel({ ministers }: Props) {
  const safeMinisters = Array.isArray(ministers) ? ministers : []
  const grouped = safeMinisters.reduce<Record<string, Minister[]>>((acc, m) => {
    ;(acc[m.faction] ??= []).push(m)
    return acc
  }, {})

  const knownFactionOrder = ['东林党', '阉党残余', '勋贵集团', '边将势力']
  const knownFactions = knownFactionOrder.filter(fname => grouped[fname]?.length)
  const unknownFactions = Object.keys(grouped)
    .filter(fname => !knownFactionOrder.includes(fname))
    .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  const displayFactions = [...knownFactions, ...unknownFactions]

  if (!displayFactions.length) {
    return <div className="minister-panel minister-panel-empty">暂无大臣数据</div>
  }

  return (
    <div className="minister-panel">
      {displayFactions.map(fname => {
        const members = grouped[fname]
        if (!members?.length) return null
        return (
          <div key={fname} className="mp-faction-group">
            <div className="mp-faction-header" style={{ borderLeftColor: FACTION_COLORS[fname] ?? '#555' }}>
              {fname}
            </div>
            {members.map(m => (
              <MinisterCard key={m.name} minister={m} />
            ))}
          </div>
        )
      })}
    </div>
  )
}
