/**
 * D100 检定结果展示：骰面 + 目标值 + 分级提示。
 * 四档分级（大成功/成功/失败/大失败）以配色与文案区分；
 * 动画采用 CSS 关键帧（key 随骰子实例变化重放），实现简单的掷骰动效。
 */
import type { RollResult } from '../../types/trpg'
import { rollSummary, tierClass, tierLabel, tierMessage } from './trpgLogic'

interface Props {
  roll: RollResult | null
}

export default function DiceRollView({ roll }: Props) {
  if (!roll) {
    return (
      <div className="ls-dice is-idle" aria-live="polite">
        <span className="ls-dice-placeholder">D100 · 等待检定</span>
      </div>
    )
  }

  const cls = tierClass(roll.tier)
  return (
    <div className={`ls-dice ${cls}`} key={`${roll.roll}-${roll.target}-${roll.tier}`} aria-live="polite">
      <div className="ls-dice-cube">
        <span className="ls-dice-number">{roll.roll}</span>
        <span className="ls-dice-side">/ 100</span>
      </div>
      <div className="ls-dice-info">
        <strong className="ls-dice-tier">{tierLabel(roll.tier)}</strong>
        <span className="ls-dice-summary">{rollSummary(roll)}</span>
        <em className="ls-dice-message">{tierMessage(roll.tier)}</em>
      </div>
    </div>
  )
}
