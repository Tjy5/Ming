/**
 * 角色卡面板：六维属性 / 技能 / 特质 / 状态 + 成长点提示。
 * 数据来源 GET /api/trpg/character（玩家角色卡）。
 */
import type { ApiCharacterSheet, ApiGrowthEntry } from '../../types/trpg'

const ATTR_ORDER = ['政治', '军事', '学识', '交际', '体力', '胆略'] as const

interface Props {
  sheet: ApiCharacterSheet | null
  /** 最近一次成长记录（act 响应 growth 字段 / growth_log 末条） */
  latestGrowth: ApiGrowthEntry | null
}

function attrBarClass(value: number): string {
  if (value >= 60) return 'is-high'
  if (value >= 30) return 'is-mid'
  return 'is-low'
}

export default function CharacterPanel({ sheet, latestGrowth }: Props) {
  if (!sheet) {
    return (
      <aside className="ls-character-panel">
        <div className="ls-panel-title">角色卡</div>
        <p className="ls-empty-note">角色卡尚未生成…</p>
      </aside>
    )
  }

  const attrs = sheet.attrs ?? {}
  const skills = Object.entries(sheet.skills ?? {})

  return (
    <aside className="ls-character-panel">
      <div className="ls-panel-title">角色卡 · {sheet.name}</div>

      {sheet.background && (
        <p className="ls-character-bg">{sheet.background}</p>
      )}

      <div className="ls-section">
        <div className="ls-section-label">属性</div>
        <div className="ls-attr-list">
          {ATTR_ORDER.map((name) => {
            const value = attrs[name] ?? 0
            return (
              <div className="ls-attr-row" key={name}>
                <span className="ls-attr-name">{name}</span>
                <div className="ls-attr-track">
                  <div
                    className={`ls-attr-fill ${attrBarClass(value)}`}
                    style={{ width: `${Math.max(2, value)}%` }}
                  />
                </div>
                <span className="ls-attr-value">{value}</span>
              </div>
            )
          })}
        </div>
      </div>

      {skills.length > 0 && (
        <div className="ls-section">
          <div className="ls-section-label">技能</div>
          <div className="ls-skill-list">
            {skills.map(([name, value]) => (
              <span className="ls-skill-chip" key={name}>
                {name} <em>{value}</em>
              </span>
            ))}
          </div>
        </div>
      )}

      {!!sheet.traits?.length && (
        <div className="ls-section">
          <div className="ls-section-label">特质</div>
          <div className="ls-tag-list">
            {sheet.traits.map((t) => <span className="ls-tag is-trait" key={t}>{t}</span>)}
          </div>
        </div>
      )}

      {!!sheet.status?.length && (
        <div className="ls-section">
          <div className="ls-section-label">状态</div>
          <div className="ls-tag-list">
            {sheet.status.map((t) => <span className="ls-tag is-status" key={t}>{t}</span>)}
          </div>
        </div>
      )}

      <div className="ls-section ls-growth">
        <div className="ls-section-label">成长</div>
        <p className="ls-growth-points">
          成长点 <strong>{sheet.growth_points}</strong>
          <span className="ls-growth-sub">
            （技能点余 {sheet.skill_points}，每 5 点折算 1 成长点）
          </span>
        </p>
        {latestGrowth && (
          <p className="ls-growth-last">
            最近成长：{latestGrowth.source}
            {latestGrowth.attr_name && latestGrowth.attr_gain > 0
              ? ` · ${latestGrowth.attr_name} +${latestGrowth.attr_gain}`
              : ''}
            {latestGrowth.skill_points > 0 ? ` · 技能点 +${latestGrowth.skill_points}` : ''}
          </p>
        )}
      </div>
    </aside>
  )
}
