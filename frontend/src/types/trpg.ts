/**
 * TRPG（跑团引擎）前端类型：与 backend/models/trpg.py 及 api/trpg.py 的
 * 请求/响应契约对齐。请求体类型（ActRequest/CharacterSheet/GrowthEntry）
 * 直接桥接 openapi 生成类型；响应体后端未声明 response_model，故此处按
 * api/trpg.py 实际返回结构手工定义（见阶段C 报告"遗留事项"）。
 */
import type { components as OpenApiComponents } from './generated'
import type { GameTime } from './game'

type OpenApiSchemas = OpenApiComponents['schemas']

export type ApiActRequest = OpenApiSchemas['ActRequest']
export type ApiCharacterSheet = OpenApiSchemas['CharacterSheet']
export type ApiGrowthEntry = OpenApiSchemas['GrowthEntry']

// ── 常量 ─────────────────────────────────────────────────

export type GamePhase = 'life_story' | 'governance'

/** D100 检定结果四档分级（与后端 VALID_TIERS 对齐） */
export type RollTier =
  | 'critical_success'
  | 'success'
  | 'failure'
  | 'critical_failure'

export const TIER_LABELS: Record<RollTier, string> = {
  critical_success: '大成功',
  success: '成功',
  failure: '失败',
  critical_failure: '大失败',
}

// ── 检定结果 ─────────────────────────────────────────────

export interface RollResult {
  /** 骰面 1-100 */
  roll: number
  /** 属性半值+技能半值+DC 修正后的目标值 */
  target: number
  tier: RollTier
  /** DC 难度修正（简易+20/常规0/困难-20/极难-40） */
  dc: number
  attr_name: string | null
  skill_name: string | null
}

// ── 分支选项 ─────────────────────────────────────────────

export interface TrpgOption {
  /** 稳定英文 ID（规则回退确定性要求；AI 生成时亦有） */
  option_id: string
  label: string
  description: string
}

// ── GET /api/trpg/character 响应 ────────────────────────

export interface CharacterResponse {
  player: ApiCharacterSheet | null
  key_figures: ApiCharacterSheet[]
  growth_log: ApiGrowthEntry[]
  phase: GamePhase
  chapter: string
  chapter_title: string
}

// ── POST /api/trpg/act 请求/响应 ────────────────────────

export interface ActPayload {
  action_text: string
  skill?: string | null
  attr?: string | null
  difficulty?: string
}

export interface PacingStatus {
  turns_taken: number
  min_turns: number
  max_turns: number
  may_advance: boolean
  must_advance: boolean
}

export interface ConvergenceHook {
  hook: string
  milestone: string | null
  fallback_year: number
  message: string
}

export interface ActResponse {
  roll: RollResult
  narrative: string
  options: TrpgOption[]
  state_changes: Record<string, unknown>
  /** ai / rule_fallback */
  source: string
  phase: GamePhase
  chapter: string
  chapter_title: string
  chapter_turns: number
  pacing: PacingStatus
  frozen: boolean
  growth: ApiGrowthEntry | null
  convergence_hook: ConvergenceHook | null
  time: GameTime
}
