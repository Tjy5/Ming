import type { GameState, ModalItem } from '../types/game'
import DesktopIcon from './DesktopIcon'

interface Props {
  state: GameState
  loading: boolean
  hasBlockingEvent: boolean
  advanceMonthInFlight: boolean
  currentModal: ModalItem | null
  targetRegion?: string | null
  isLifeStory: boolean
  onOpenEdictModal: () => void
  onAdvanceMonth: () => void
  onOpenTrpg: () => void
}

export default function CommandHud({
  loading,
  hasBlockingEvent,
  advanceMonthInFlight,
  currentModal,
  targetRegion,
  isLifeStory,
  onOpenEdictModal,
  onAdvanceMonth,
  onOpenTrpg,
}: Props) {
  const advanceDisabled =
    loading || !!currentModal || hasBlockingEvent || advanceMonthInFlight

  return (
    <div className="hud-bottom-bar" role="toolbar" aria-label="御前行动指令台">
      {isLifeStory ? (
        <button
          type="button"
          className="hud-trpg-pill"
          onClick={onOpenTrpg}
          title="当前处于人生篇章阶段，进入跑团行动"
          data-hud-fallback-focus="true"
        >
          <DesktopIcon name="dice" />
          <span>跑团篇章进行中 · 进入跑团</span>
        </button>
      ) : (
        <button
          type="button"
          className="hud-edict-btn"
          onClick={onOpenEdictModal}
          disabled={loading || hasBlockingEvent}
          title="展开御笔草诏台，拟定圣旨下达政令 (快捷键: E)"
          aria-label="御笔草诏"
          data-shortcut="E"
          data-hud-fallback-focus="true"
        >
          <DesktopIcon name="document" />
          <span>御笔草诏</span>
          <kbd className="hud-shortcut-badge" aria-hidden="true">E</kbd>
          {targetRegion && <span className="target-pill">📍 {targetRegion}</span>}
        </button>
      )}

      <button
        type="button"
        className="hud-advance-btn"
        disabled={advanceDisabled}
        onClick={onAdvanceMonth}
        title={advanceDisabled ? '请先处理未决事件或等待结算' : '天命流转，推进至下一月份 (快捷键: Space)'}
        aria-label="推进月份"
        data-shortcut="Space"
      >
        {advanceMonthInFlight ? (
          <div className="spinner command-spinner" />
        ) : (
          <DesktopIcon name="clock" />
        )}
        <span>推进月份</span>
        <kbd className="hud-shortcut-badge" aria-hidden="true">Space</kbd>
      </button>
    </div>
  )
}
