import { useState } from 'react'
import { motion } from 'framer-motion'
import type { TurnSummary, RegionChange } from '../types/game'

interface Props {
  summary: TurnSummary
  onClose: () => void
}

function TrendArrow({ before, after, isPercent }: { before: number; after: number; isPercent?: boolean }) {
  const diff = after - before
  if (diff === 0) return <span className="ts-trend-neutral">—</span>
  const display = isPercent ? `${Math.round(Math.abs(diff) * 100)}%` : Math.abs(diff)
  return (
    <span className={diff > 0 ? 'ts-trend-up' : 'ts-trend-down'}>
      {diff > 0 ? '↑' : '↓'}{display}
    </span>
  )
}

const RF_LABELS: Record<string, string> = {
  stability: '稳定度', garrison: '驻军', civil_morale: '民心',
  rebellion_risk: '叛乱度', disaster_level: '灾害', tax_collected: '税收',
  tax_rate: '税率', control: '控制', threat: '威胁', tax_contribution: '贡赋',
}
const INDICATOR_LABELS: Record<string, string> = {
  national_treasury: '国库',
  imperial_treasury: '内帑',
  grain: '粮草',
  population: '人口',
  military_strength: '兵力',
  civil_morale: '民心',
  military_morale: '军心',
  court_prestige: '威望',
  treasury: '钱粮',
  military_supply: '军备',
}
const THREAT_ZH: Record<string, string> = { none: '无' }
const TAX_ZH: Record<string, string> = { low: '低', medium: '中', high: '高' }
const STATUS_ZH: Record<string, string> = { active: '在任', idle: '闲置', removed: '罢免' }

function fmtRV(field: string, v: number | string | null | undefined): string {
  if (v == null) return '—'
  if (field === 'tax_rate') return `${Math.round((v as number) * 100)}%`
  if (field === 'threat') return THREAT_ZH[v as string] ?? (v as string)
  if (field === 'tax_contribution') return TAX_ZH[v as string] ?? (v as string)
  return String(v)
}

type RDiff = { label: string; bStr: string; aStr: string; bNum?: number; aNum?: number }

function getRegionDiffs(r: RegionChange): RDiff[] {
  const out: RDiff[] = []
  const addN = (f: string, b: number | null | undefined, a: number | null | undefined) => {
    if (b == null && a == null) return
    const bv = b ?? 0, av = a ?? 0
    if (bv === av) return
    out.push({ label: RF_LABELS[f] ?? f, bStr: fmtRV(f, bv), aStr: fmtRV(f, av), bNum: bv, aNum: av })
  }
  const addS = (f: string, b: string | null | undefined, a: string | null | undefined) => {
    if (!b && !a) return
    if (b === a) return
    out.push({ label: RF_LABELS[f] ?? f, bStr: fmtRV(f, b), aStr: fmtRV(f, a) })
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

export default function TurnSummaryModal({ summary, onClose }: Props) {
  const [expandedRegions, setExpandedRegions] = useState<Set<string>>(new Set())
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
                  <span className="ts-label">{INDICATOR_LABELS[t.name] ?? t.name}</span>
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
                      <div className="ts-sub">
                        满意度 {f.satisfaction_before} → {f.satisfaction_after}
                        {' '}<TrendArrow before={f.satisfaction_before} after={f.satisfaction_after} />
                      </div>
                      <div className="ts-sub">
                        叛乱风险 {f.rebellion_risk_before} → {f.rebellion_risk_after}
                        {' '}<TrendArrow before={f.rebellion_risk_before} after={f.rebellion_risk_after} />
                      </div>
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
                  {summary.region_changes.map(r => {
                    const diffs = getRegionDiffs(r)
                    if (diffs.length === 0) return null
                    const collapsed = diffs.length > 3 && !expandedRegions.has(r.name)
                    const visible = collapsed ? diffs.slice(0, 3) : diffs
                    return (
                      <div key={r.name} className="ts-change-item">
                        <strong>{r.name}</strong>
                        <div className="ts-region-diffs">
                          {visible.map((d, i) => (
                            <div key={i} className="ts-sub">
                              {d.label} {d.bStr} → {d.aStr}
                              {d.bNum != null && d.aNum != null && <TrendArrow before={d.bNum} after={d.aNum} isPercent={d.label.includes('率')} />}
                            </div>
                          ))}
                          {diffs.length > 3 && (
                            <button
                              className="ts-collapse-toggle"
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
            }
          </div>
          <div className="ts-col">
            <h3>百官动态</h3>
            {summary.minister_changes.length === 0
              ? <div className="ts-empty">百官安分</div>
              : <div className="ts-changes-list">
                  {summary.minister_changes.map(m => (
                    <div key={m.name} className="ts-change-item">
                      <strong>{m.name}</strong>
                      <div className="ts-sub">
                        忠诚 {m.loyalty_before} → {m.loyalty_after}
                        {' '}<TrendArrow before={m.loyalty_before} after={m.loyalty_after} />
                      </div>
                      {m.status_before !== m.status_after && (
                        <div className="ts-sub">状态 {STATUS_ZH[m.status_before] ?? m.status_before} → {STATUS_ZH[m.status_after] ?? m.status_after}</div>
                      )}
                    </div>
                  ))}
                </div>
            }
          </div>
        </div>

        {summary.region_details && summary.region_details.length > 0 && (
          <div className="ts-section ts-attribution">
            <h3>变化归因</h3>
            <ul className="ts-attr-list">
              {summary.region_details.map((d, i) => (
                <li key={i}>
                  {d.region}：{RF_LABELS[d.field] ?? d.field}{' '}
                  <span className={d.delta > 0 ? 'ts-trend-up' : 'ts-trend-down'}>
                    {d.delta > 0 ? '+' : ''}{d.field === 'tax_rate' ? `${Math.round(d.delta * 100)}%` : d.delta}
                  </span>
                  （{d.source}）
                </li>
              ))}
            </ul>
          </div>
        )}

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
