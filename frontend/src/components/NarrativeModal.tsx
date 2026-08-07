import { useState } from 'react'
import type { MinisterReaction, TurnSummary, RegionChange } from '../types/game'

const FIELD_LABELS: Record<string, string> = {
  national_treasury: '国库', imperial_treasury: '内帑', grain: '粮草',
  population: '人口', military_strength: '兵力',
  treasury: '钱粮', military_supply: '军备',
  civil_morale: '民心', military_morale: '军心', court_prestige: '威望',
  stability: '稳定度', rebellion_risk: '叛乱度', tax_collected: '税收',
  disaster_level: '灾害', tax_rate: '税率', garrison: '驻军',
  control: '控制', threat: '威胁', tax_contribution: '贡赋',
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

const THREAT_ZH: Record<string, string> = { none: '无' }
const TAX_ZH: Record<string, string> = { low: '低', medium: '中', high: '高' }
const STATUS_ZH: Record<string, string> = { active: '在任', idle: '闲置', removed: '罢免' }

function fmtVal(field: string, v: number | string | null | undefined): string {
  if (v == null) return '—'
  if (field === 'tax_rate') return `${Math.round((v as number) * 100)}%`
  if (field === 'threat') return THREAT_ZH[v as string] ?? (v as string)
  if (field === 'tax_contribution') return TAX_ZH[v as string] ?? (v as string)
  return String(v)
}

type FieldDiff = { label: string; bStr: string; aStr: string; bNum?: number; aNum?: number }

function regionDiffs(r: RegionChange): FieldDiff[] {
  const out: FieldDiff[] = []
  const addN = (f: string, b: number | null | undefined, a: number | null | undefined) => {
    if (b == null && a == null) return
    const bv = b ?? 0, av = a ?? 0
    if (bv === av) return
    out.push({ label: FIELD_LABELS[f] ?? f, bStr: fmtVal(f, bv), aStr: fmtVal(f, av), bNum: bv, aNum: av })
  }
  const addS = (f: string, b: string | null | undefined, a: string | null | undefined) => {
    if (!b && !a) return
    if (b === a) return
    out.push({ label: FIELD_LABELS[f] ?? f, bStr: fmtVal(f, b), aStr: fmtVal(f, a) })
  }
  addN('stability', r.stability_before, r.stability_after)
  addS('control', r.control_before, r.control_after)
  addS('threat', r.threat_before, r.threat_after)
  addN('garrison', r.garrison_before, r.garrison_after)
  addN('civil_morale', r.civil_morale_before, r.civil_morale_after)
  addN('rebellion_risk', r.rebellion_risk_before, r.rebellion_risk_after)
  addN('disaster_level', r.disaster_level_before, r.disaster_level_after)
  addN('tax_collected', r.tax_collected_before, r.tax_collected_after)
  addN('tax_rate', r.tax_rate_before, r.tax_rate_after)
  addS('tax_contribution', r.tax_contribution_before, r.tax_contribution_after)
  return out
}

function Trend({ b, a }: { b: number; a: number }) {
  const d = a - b
  if (d === 0) return null
  return <span className={d > 0 ? 'trend-up' : 'trend-down'}>{d > 0 ? ' ▲' : ' ▼'}</span>
}

interface Props {
  narrative: string
  delta: Record<string, number>
  ministerReactions?: MinisterReaction[]
  turnSummary?: TurnSummary
  onClose: () => void
}

export default function NarrativeModal({ narrative, delta, ministerReactions = [], turnSummary, onClose }: Props) {
  const entries = Object.entries(delta).filter(([, v]) => v !== 0)
  const [deltaOpen, setDeltaOpen] = useState(entries.length > 0)
  const [summaryOpen, setSummaryOpen] = useState(true)
  const [expandedRegions, setExpandedRegions] = useState<Set<string>>(new Set())

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal narrative-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="narrative-header">令谕已下</h3>
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
                          {FIELD_LABELS[t.name] ?? t.name}: {t.before} → {t.after}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {turnSummary.faction_changes.length > 0 && (
                  <div className="narrative-summary-block">
                    <div className="narrative-summary-title">派系变化</div>
                    <ul className="narrative-summary-list">
                      {turnSummary.faction_changes.map(f => (
                        <li key={f.name}>
                          <strong>{f.name}</strong>：满意度 {f.satisfaction_before}→{f.satisfaction_after}
                          <Trend b={f.satisfaction_before} a={f.satisfaction_after} />
                          {' / '}叛乱风险 {f.rebellion_risk_before}→{f.rebellion_risk_after}
                          <Trend b={f.rebellion_risk_before} a={f.rebellion_risk_after} />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {turnSummary.region_changes.length > 0 && (
                  <div className="narrative-summary-block">
                    <div className="narrative-summary-title">地方变化</div>
                    <div className="narrative-summary-regions">
                      {turnSummary.region_changes.map(r => {
                        const diffs = regionDiffs(r)
                        if (diffs.length === 0) return null
                        const collapsed = diffs.length > 3 && !expandedRegions.has(r.name)
                        const visible = collapsed ? diffs.slice(0, 3) : diffs
                        return (
                          <div key={r.name} className="region-change-item">
                            <strong>{r.name}</strong>
                            <div className="region-diffs">
                              {visible.map((d, i) => (
                                <span key={i} className="region-diff-entry">
                                  {d.label} {d.bStr}→{d.aStr}
                                  {d.bNum != null && d.aNum != null && <Trend b={d.bNum} a={d.aNum} />}
                                </span>
                              ))}
                              {diffs.length > 3 && (
                                <button
                                  className="collapse-toggle"
                                  onClick={() => setExpandedRegions(s => {
                                    const n = new Set(s)
                                    if (collapsed) n.add(r.name)
                                    else n.delete(r.name)
                                    return n
                                  })}
                                >
                                  {collapsed ? `查看详情（+${diffs.length - 3}项）` : '收起'}
                                </button>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {turnSummary.minister_changes.length > 0 && (
                  <div className="narrative-summary-block">
                    <div className="narrative-summary-title">百官变化</div>
                    <ul className="narrative-summary-list">
                      {turnSummary.minister_changes.map(m => (
                        <li key={m.name}>
                          <strong>{m.name}</strong>：忠诚 {m.loyalty_before}→{m.loyalty_after}
                          <Trend b={m.loyalty_before} a={m.loyalty_after} />
                          {m.status_before !== m.status_after && (
                            <span> / 状态 {STATUS_ZH[m.status_before] ?? m.status_before}→{STATUS_ZH[m.status_after] ?? m.status_after}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {turnSummary.region_details && turnSummary.region_details.length > 0 && (
                  <div className="narrative-summary-block">
                    <div className="narrative-summary-title">变化归因</div>
                    <ul className="narrative-summary-list">
                      {turnSummary.region_details.map((d, i) => (
                        <li key={i}>
                          {d.region}：{FIELD_LABELS[d.field] ?? d.field}{' '}
                          <span className={d.delta > 0 ? 'delta-pos' : 'delta-neg'}>
                            {d.delta > 0 ? '+' : ''}{d.field === 'tax_rate' ? `${Math.round(d.delta * 100)}%` : d.delta}
                          </span>
                          （{d.source}）
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

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
