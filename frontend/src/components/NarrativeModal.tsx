import { useState } from 'react'
import type { MinisterReaction, TurnSummary } from '../types/game'

const FIELD_LABELS: Record<string, string> = {
  treasury: '钱粮', population: '人口', military_supply: '军备',
  civil_morale: '民心', military_morale: '军心', court_prestige: '威望',
  stability: '稳定度', rebellion_risk: '叛乱度', tax_collected: '税收',
  disaster_level: '灾害', tax_rate: '税率', garrison: '驻军',
  satisfaction: '满意度',
}

function resolveLabel(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]
  for (const field in FIELD_LABELS) {
    if (key.endsWith(`_${field}`)) {
      const prefix = key.slice(0, key.length - field.length - 1)
      return `${prefix}${FIELD_LABELS[field]}`
    }
  }
  return key
}

interface Props {
  narrative: string
  delta: Record<string, number>
  ministerReactions?: MinisterReaction[]
  turnSummary?: TurnSummary
  onClose: () => void
}

export default function NarrativeModal({ narrative, delta, ministerReactions = [], turnSummary, onClose }: Props) {
  const [deltaOpen, setDeltaOpen] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(true)
  const entries = Object.entries(delta).filter(([, v]) => v !== 0)

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal narrative-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="narrative-header">圣旨已下</h3>
        <p className="narrative-text">{narrative}</p>

        {turnSummary && (
          <div className="narrative-summary">
            <button
              type="button"
              className="narrative-summary-toggle"
              aria-expanded={summaryOpen}
              onClick={() => setSummaryOpen((prev) => !prev)}
            >
              <span>{summaryOpen ? '▼' : '▶'}</span>
              朝政简报 · {turnSummary.era_name}{turnSummary.era_year}年{turnSummary.month}月
            </button>
            {summaryOpen && (
              <div className="narrative-summary-body">
                {turnSummary.commentary && (
                  <div className="narrative-summary-commentary">"{turnSummary.commentary}"</div>
                )}

                <div className="narrative-summary-block">
                  <div className="narrative-summary-title">大事记</div>
                  {turnSummary.major_events.length === 0 ? (
                    <div className="narrative-summary-empty">无重大事件</div>
                  ) : (
                    <ul className="narrative-summary-list">
                      {turnSummary.major_events.map((ev, i) => (
                        <li key={`${ev}-${i}`}>{ev}</li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="narrative-summary-block">
                  <div className="narrative-summary-title">国策指标</div>
                  {turnSummary.indicator_trends.length === 0 ? (
                    <div className="narrative-summary-empty">无明显变化</div>
                  ) : (
                    <ul className="narrative-summary-list">
                      {turnSummary.indicator_trends.map((t) => (
                        <li key={t.name}>
                          {t.name}: {t.before} → {t.after}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="narrative-summary-meta">
                  <span>党争变化 {turnSummary.faction_changes.length} 项</span>
                  <span>地方变化 {turnSummary.region_changes.length} 项</span>
                  <span>百官变化 {turnSummary.minister_changes.length} 项</span>
                </div>

                {turnSummary.pending_memorials_count > 0 && (
                  <div className="narrative-summary-hint">
                    ⚠ 尚有 {turnSummary.pending_memorials_count} 份奏折待批复
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {entries.length > 0 && (
          <div className="narrative-delta">
            <button type="button" className="narrative-delta-toggle" aria-expanded={deltaOpen} onClick={() => setDeltaOpen(p => !p)}>
              <span>{deltaOpen ? '▼' : '▶'}</span> 详细数据
            </button>
            {deltaOpen && (
              <ul className="delta-list">
                {entries.map(([key, val]) => (
                  <li key={key}>
                    <span>{resolveLabel(key)}</span>
                    <span className={val > 0 ? 'delta-pos' : 'delta-neg'}>
                      {val > 0 ? '+' : ''}{val}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {ministerReactions.length > 0 && (
          <div className="narrative-reactions">
            {ministerReactions.map((r) => (
              <div key={`${r.minister_name}-${r.reaction_type}`} className={`narrative-reaction ${r.reaction_type === 'support' ? 'reaction-support' : 'reaction-oppose'}`}>
                <div className="narrative-reaction-head">
                  <span className="narrative-reaction-name">{r.minister_name}<small>（{r.faction}）</small></span>
                  {r.loyalty_change !== 0 && (
                    <span className={r.loyalty_change > 0 ? 'delta-pos' : 'delta-neg'}>
                      {r.loyalty_change > 0 ? '+' : ''}{r.loyalty_change}
                    </span>
                  )}
                </div>
                <div className="narrative-reaction-text">{r.reaction_text}</div>
              </div>
            ))}
          </div>
        )}

        <div className="modal-actions">
          <button className="modal-btn primary" onClick={onClose}>知道了</button>
        </div>
      </div>
    </div>
  )
}
