import type { Minister } from '../types/game'

interface Props {
  ministers: Minister[]
}

export default function MissionPanel({ ministers }: Props) {
  const onMission = ministers.filter(m => m.status === 'on_mission' && m.current_mission)
  if (!onMission.length) return null

  return (
    <div className="mission-panel">
      <div className="mp-faction-header" style={{ marginBottom: '8px', borderLeft: '3px solid var(--accent-gold)' }}>
        <span>大臣工作进度</span>
      </div>
      {onMission.map(m => {
        const ms = m.current_mission!
        const pct = Math.min(100, Math.round((ms.progress_months / ms.total_months) * 100))
        const remaining = ms.total_months - ms.progress_months
        return (
          <div key={m.name} className="mission-item">
            <span className="mission-minister">{m.name}</span>
            <span className="mission-name">{ms.name}</span>
            <div className="progress-track mission-progress">
              <div className="progress-fill" style={{ width: `${pct}%`, backgroundColor: 'var(--accent-gold)' }} />
            </div>
            <span className="mission-remaining">剩{remaining}月</span>
          </div>
        )
      })}
    </div>
  )
}
