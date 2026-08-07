/**
 * 跑团叙事页纯逻辑：检定分级展示、选项→行动请求构建、phase 路由判定、
 * 叙事流条目拼装。独立于 React，便于 vitest 单测（与现有测试组织方式一致）。
 */
import type { GameState, HistoryEntry } from '../../types/game'
import type { ActPayload, ActResponse, RollResult, RollTier, TrpgOption } from '../../types/trpg'
import { TIER_LABELS } from '../../types/trpg'

// ── 检定分级展示 ─────────────────────────────────────────

/** 分级 → CSS 修饰类（配色区分见 life-story.css） */
export function tierClass(tier: RollTier): string {
  switch (tier) {
    case 'critical_success': return 'is-critical-success'
    case 'success': return 'is-success'
    case 'failure': return 'is-failure'
    case 'critical_failure': return 'is-critical-failure'
  }
}

/** 分级 → 提示文案（与后端 TIER_LABELS 对应，补充戏剧化说明） */
export function tierMessage(tier: RollTier): string {
  switch (tier) {
    case 'critical_success': return '天命所钟，事半功倍！'
    case 'success': return '举措得宜，顺利达成。'
    case 'failure': return '事与愿违，未竟全功。'
    case 'critical_failure': return '祸从天降，局势陡变！'
  }
}

export function tierLabel(tier: RollTier): string {
  return TIER_LABELS[tier]
}

/** 检定摘要行：如「胆略 检定 · 骰面 37 / 目标 55」 */
export function rollSummary(roll: RollResult): string {
  const who = [roll.attr_name, roll.skill_name].filter(Boolean).join('·')
  return `${who || '检定'} · 骰面 ${roll.roll} / 目标 ${roll.target}`
}

// ── 选项 → 行动请求 ──────────────────────────────────────

/**
 * 分支选项点击 → act 请求体。
 * 契约说明：后端 ActRequest 暂无 option_id 字段（见阶段C 报告遗留事项），
 * 以选项文案作为行动文本传递，option_id 由调用方自行记录。
 */
export function buildActFromOption(option: TrpgOption): ActPayload {
  const text = option.description
    ? `${option.label}——${option.description}`
    : option.label
  return { action_text: text }
}

/** 自由行动输入 → act 请求体 */
export function buildActFromFreeText(text: string): ActPayload | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  return { action_text: trimmed }
}

// ── phase 路由判定 ───────────────────────────────────────

export type PhaseRoute = 'loading' | 'life_story' | 'governance'

/** 全局 phase 分流：无 state 时为 loading，否则按后端 state.phase 路由 */
export function resolvePhaseRoute(state: Pick<GameState, 'phase'> | null): PhaseRoute {
  if (!state) return 'loading'
  return state.phase === 'life_story' ? 'life_story' : 'governance'
}

/** act 响应是否触发 phase 切换（life_story → governance） */
export function detectPhaseSwitch(current: GameState['phase'], response: Pick<ActResponse, 'phase'>): boolean {
  return current !== response.phase
}

// ── 叙事流条目 ───────────────────────────────────────────

export type FeedItem =
  | { kind: 'action'; id: string; text: string }
  | {
    kind: 'narrative'
    id: string
    text: string
    roll: RollResult | null
    chapterTitle: string
    source: string
  }

export const TRPG_HISTORY_TYPE = 'trpg_act'

let feedSeq = 0
export function nextFeedId(prefix: string): string {
  feedSeq += 1
  return `${prefix}_${feedSeq}`
}

/** 从治理存档历史中回放跑团叙事（进入页面时播种 feed） */
export function feedFromHistory(entries: HistoryEntry[]): FeedItem[] {
  const items: FeedItem[] = []
  for (const entry of entries) {
    if (entry.decree_type !== TRPG_HISTORY_TYPE) continue
    if (entry.decree_desc) {
      items.push({ kind: 'action', id: nextFeedId('act'), text: entry.decree_desc })
    }
    if (entry.narrative) {
      items.push({
        kind: 'narrative',
        id: nextFeedId('nar'),
        text: entry.narrative,
        roll: null,
        chapterTitle: '',
        source: 'history',
      })
    }
  }
  return items
}

/** act 响应 → 追加玩家行动卡 + 检定/叙事卡 */
export function appendActResult(
  feed: FeedItem[],
  actionText: string,
  res: ActResponse,
): FeedItem[] {
  return [
    ...feed,
    { kind: 'action', id: nextFeedId('act'), text: actionText },
    {
      kind: 'narrative',
      id: nextFeedId('nar'),
      text: res.narrative,
      roll: res.roll,
      chapterTitle: res.chapter_title,
      source: res.source,
    },
  ]
}
