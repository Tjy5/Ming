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
  onOpenAiSettings: () => void
  onOpenChat: () => void
  onOpenContinuity?: () => void
  onOpenGuide?: () => void
}

const RESOURCES: { key: keyof GameState; label: string; max: number; unit: string }[] = [
  { key: 'national_treasury', label: '国库', unit: '万两', max: 1000 },
  { key: 'imperial_treasury', label: '内帑', unit: '万两', max: 500 },
  { key: 'grain', label: '粮草', unit: '万石', max: 5000 },
  { key: 'population', label: '人口', unit: '万人', max: 20000 },
  { key: 'military_strength', label: '兵力', unit: '万人', max: 500 },
  { key: 'civil_morale', label: '民心', unit: '%', max: 100 },
  { key: 'military_morale', label: '军心', unit: '%', max: 100 },
  { key: 'court_prestige', label: '威望', unit: '%', max: 100 },
]

// 08-07-frontend-ui-polish：资源悬停说明（构成/含义）
const RESOURCE_INFO: Record<string, string> = {
  national_treasury: '国库：税收与赏赐之和，减军费与工程开销。',
  imperial_treasury: '内帑：君主私库，用于特殊赏赐与应急。',
  grain: '粮草：军需与赈灾之本，灾年 pivotal。',
  population: '人口：治下编户，影响赋税与兵源。',
  military_strength: '兵力：常备军，守土与征伐之基。',
  civil_morale: '民心：治下安宁度，过低则生民变。',
  military_morale: '军心：将士效命度，关乎战力。',
  court_prestige: '威望：君主号令之重，影响外交与朝堂。',
}

function barColor(val: number, max: number): string {
  const pct = val / max
  if (pct > 0.6) return 'var(--green)'
  if (pct > 0.3) return 'var(--yellow)'
  return 'var(--red)'
}

export default function ResourceBar({ state, prevState, onSave, onShowSaves, onNewGame, onOpenAiSettings, onOpenChat, onOpenContinuity, onOpenGuide }: Props) {
  const [fallbackEnabled, setFallbackEnabled] = useState(false)

  useEffect(() => {
    api.getSettings()
      .then(s => setFallbackEnabled(s.rule_parse_fallback))
      .catch((cause) => {
        // Settings are ancillary to the resource bar, but failures must remain
        // visible so a contract or backend outage is diagnosable.
        console.warn('[resource-bar] failed to load settings', cause)
      })
  }, [])

  const toggleFallback = async () => {
    try {
      const res = await api.updateSettings({ rule_parse_fallback: !fallbackEnabled })
      setFallbackEnabled(res.rule_parse_fallback)
    } catch (cause) {
      console.warn('[resource-bar] failed to update fallback setting', cause)
    }
  }

  return (
    <div className="resource-bar">
      <HistoricalCalendar {...state.time} />
      {RESOURCES.map(({ key, label, max, unit }) => {
        const val = state[key] as number
        const prev = prevState ? (prevState[key] as number) : val
        const diff = val - prev
        const cls = diff > 0 ? 'up' : diff < 0 ? 'down' : ''
        return (
          <div className="resource-item" key={key} title={RESOURCE_INFO[key] || label}>
            <div className="resource-label">
              <span>{label}</span>
              <span className={`val ${cls}`}>{val}<small>{unit}</small></span>
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
        <button className="toolbar-btn" onClick={onOpenChat}>对话模式</button>
        {onOpenContinuity && (
          <button className="toolbar-btn" onClick={onOpenContinuity} title="查看世界分支、书签和活动">世界连续性</button>
        )}
        <button className="toolbar-btn" onClick={onOpenAiSettings}>AI设置</button>
        {onOpenGuide && (
          <button className="toolbar-btn" onClick={onOpenGuide} title="查看界面操作指引">指引</button>
        )}
        <button className="toolbar-btn" onClick={onNewGame}>新局</button>
      </div>
    </div>
  )
}
