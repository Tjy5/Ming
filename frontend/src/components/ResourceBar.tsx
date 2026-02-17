import { useState, useEffect } from 'react'
import type { GameState } from '../types/game'
import { api } from '../api/client'
import HistoricalCalendar from './HistoricalCalendar'

interface Props {
  state: GameState
  prevState: GameState | null
  onSave: () => void
  onShowSaves: () => void
  onNewGame: () => void
}

const RESOURCES: { key: keyof GameState; label: string; max: number }[] = [
  { key: 'treasury', label: '钱粮', max: 200 },
  { key: 'population', label: '人口', max: 200 },
  { key: 'military_supply', label: '军备', max: 200 },
  { key: 'civil_morale', label: '民心', max: 100 },
  { key: 'military_morale', label: '军心', max: 100 },
  { key: 'court_prestige', label: '威望', max: 100 },
]

function barColor(val: number, max: number): string {
  const pct = val / max
  if (pct > 0.6) return 'var(--green)'
  if (pct > 0.3) return 'var(--yellow)'
  return 'var(--red)'
}

export default function ResourceBar({ state, prevState, onSave, onShowSaves, onNewGame }: Props) {
  const [fallbackEnabled, setFallbackEnabled] = useState(false)

  useEffect(() => {
    api.getSettings().then(s => setFallbackEnabled(s.rule_parse_fallback)).catch(() => { })
  }, [])

  const toggleFallback = async () => {
    try {
      const res = await api.updateSettings({ rule_parse_fallback: !fallbackEnabled })
      setFallbackEnabled(res.rule_parse_fallback)
    } catch {
      // ignore
    }
  }

  return (
    <div className="resource-bar">
      <HistoricalCalendar {...state.time} />
      {RESOURCES.map(({ key, label, max }) => {
        const val = state[key] as number
        const prev = prevState ? (prevState[key] as number) : val
        const diff = val - prev
        const cls = diff > 0 ? 'up' : diff < 0 ? 'down' : ''
        return (
          <div className="resource-item" key={key}>
            <div className="resource-label">
              <span>{label}</span>
              <span className={`val ${cls}`}>{val}</span>
            </div>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${(val / max) * 100}%`, backgroundColor: barColor(val, max) }}
              />
            </div>
          </div>
        )
      })}
      <div className="toolbar-actions">
        <button
          className={`toolbar-btn${fallbackEnabled ? ' active-toggle' : ''}`}
          onClick={toggleFallback}
          title={fallbackEnabled ? '本地规则兜底已开启' : '本地规则兜底已关闭'}
        >
          {fallbackEnabled ? '兜底:开' : '兜底:关'}
        </button>
        <button className="toolbar-btn" onClick={onSave}>存档</button>
        <button className="toolbar-btn" onClick={onShowSaves}>读档</button>
        <button className="toolbar-btn" onClick={onNewGame}>新局</button>
      </div>
    </div>
  )
}
