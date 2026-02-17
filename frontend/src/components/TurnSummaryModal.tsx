import { motion } from 'framer-motion'
import type { TurnSummary } from '../types/game'

interface Props {
  summary: TurnSummary
  onClose: () => void
}

function TrendArrow({ before, after }: { before: number; after: number }) {
  const diff = after - before
  if (diff === 0) return <span className="ts-trend-neutral">—</span>
  return (
    <span className={diff > 0 ? 'ts-trend-up' : 'ts-trend-down'}>
      {diff > 0 ? '↑' : '↓'}{Math.abs(diff)}
    </span>
  )
}

export default function TurnSummaryModal({ summary, onClose }: Props) {
  return (
    <div className="modal-overlay">
      <motion.div
        className="modal turn-summary-modal"
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
      >
        <div className="ts-header">
          <h2>朝政简报 · {summary.era_name}{summary.era_year}年{summary.month}月</h2>
        </div>

        {summary.commentary && (
          <div className="ts-commentary">"{summary.commentary}"</div>
        )}

        <div className="ts-section">
          <h3>大事记</h3>
          {summary.major_events.length === 0
            ? <div className="ts-empty">无重大事件</div>
            : <ul className="ts-event-list">
                {summary.major_events.map((ev, i) => (
                  <li key={i}><span className="ts-bullet">✦</span>{ev}</li>
                ))}
              </ul>
          }
        </div>
        <div className="ts-grid-row">
          <div className="ts-col">
            <h3>国策指标</h3>
            <div className="ts-indicators">
              {summary.indicator_trends.map(t => (
                <div key={t.name} className="ts-indicator-row">
                  <span className="ts-label">{t.name}</span>
                  <span className="ts-val">{t.before} → {t.after} <TrendArrow before={t.before} after={t.after} /></span>
                </div>
              ))}
            </div>
          </div>
          <div className="ts-col">
            <h3>党争动态</h3>
            {summary.faction_changes.length === 0
              ? <div className="ts-empty">无明显变化</div>
              : <div className="ts-changes-list">
                  {summary.faction_changes.map(f => (
                    <div key={f.name} className="ts-change-item">
                      <strong>{f.name}</strong>
                      <div className="ts-sub">满意度 {f.satisfaction_before} → {f.satisfaction_after}</div>
                    </div>
                  ))}
                </div>
            }
          </div>
        </div>
        <div className="ts-grid-row">
          <div className="ts-col">
            <h3>地方局势</h3>
            {summary.region_changes.length === 0
              ? <div className="ts-empty">天下太平</div>
              : <div className="ts-changes-list">
                  {summary.region_changes.slice(0, 4).map(r => (
                    <div key={r.name} className="ts-change-item">
                      <strong>{r.name}</strong>
                      <div className="ts-sub">稳定 {r.stability_before} → {r.stability_after}</div>
                      {r.control_before !== r.control_after && <div className="ts-alert">控制权变更: {r.control_after}</div>}
                    </div>
                  ))}
                  {summary.region_changes.length > 4 && <div className="ts-more">...等{summary.region_changes.length}处变动</div>}
                </div>
            }
          </div>
          <div className="ts-col">
            <h3>百官动态</h3>
            {summary.minister_changes.length === 0
              ? <div className="ts-empty">百官安分</div>
              : <div className="ts-changes-list">
                  {summary.minister_changes.slice(0, 4).map(m => (
                    <div key={m.name} className="ts-change-item">
                      <strong>{m.name}</strong>
                      <div className="ts-sub">忠诚 {m.loyalty_before} → {m.loyalty_after}</div>
                    </div>
                  ))}
                </div>
            }
          </div>
        </div>

        <div className="ts-footer">
          {summary.pending_memorials_count > 0 && (
            <div className="ts-hint">⚠ 尚有 {summary.pending_memorials_count} 份奏折待批复</div>
          )}
          <button className="ts-close-btn" onClick={onClose}>朕已阅</button>
        </div>
      </motion.div>
    </div>
  )
}
