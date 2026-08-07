/**
 * 分支选项列表：3-4 个主持人选项，点击 → POST /api/trpg/act。
 * 选项之外由 LifeStoryPage 提供自由行动输入框。
 */
import type { TrpgOption } from '../../types/trpg'

interface Props {
  options: TrpgOption[]
  disabled: boolean
  onSelect: (option: TrpgOption) => void
}

export default function OptionList({ options, disabled, onSelect }: Props) {
  if (!options.length) return null
  return (
    <div className="ls-options">
      {options.map((option) => (
        <button
          type="button"
          key={option.option_id}
          className="ls-option-btn"
          disabled={disabled}
          onClick={() => onSelect(option)}
        >
          <span className="ls-option-label">{option.label}</span>
          {option.description && (
            <span className="ls-option-desc">{option.description}</span>
          )}
        </button>
      ))}
    </div>
  )
}
