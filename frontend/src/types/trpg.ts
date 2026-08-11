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
export type NarrativeRegenerationRequest = OpenApiSchemas['NarrativeRegenerationRequest']
export type NarrativeRegenerationResponse = OpenApiSchemas['NarrativeGenerationResult']

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
  /** 可选：关联里程碑 ID（选中后调 milestones/{id}/complete 而非 /act） */
  milestone_id?: string | null
  /** 可选：1360 收束抉择标记（accept=接受招揽 / refuse=继续流窜，路由到 /converge） */
  convergence?: 'accept' | 'refuse'
}

/** 1360 收束抉择：接受招揽切换 governance；拒绝归附则继续流亡世界线 */
export type ConvergeChoice = 'accept' | 'refuse'

/** POST /api/trpg/converge 响应（与 /act 同构字段子集 + 结局信息） */
export interface ConvergeResponse {
  choice: ConvergeChoice
  narrative: string
  /** 仅未来已提交的终局 settlement 可携带；当前两种收束选择均为 null */
  game_over: { result: 'victory' | 'defeat'; message: string } | null
  /** 接受招揽时为 yingtian-founding（已达成，409 闸口拦截重复完成） */
  converged_milestone: string | null
  phase: GamePhase
  chapter: string
  chapter_title: string
  chapter_turns: number
  pacing: PacingStatus
  frozen: boolean
  time: GameTime
}

/** POST /api/trpg/milestones/{id}/complete 响应（与 /act 同构字段子集） */
export interface MilestoneCompleteResponse {
  milestone: string
  title: string
  narrative: string
  transition: {
    from_chapter: string
    to_chapter: string
    year: number
    summary: string
  } | null
  growth: ApiGrowthEntry | null
  phase: GamePhase
  chapter: string
  chapter_title: string
  chapter_turns: number
  pacing: PacingStatus
  frozen: boolean
  time: GameTime
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

export type ActPayload = ApiActRequest

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
  narrative_status: NarrativeRegenerationResponse['narrative_status']
  narrative_path_id: NarrativeRegenerationRequest['path_id']
  settlement_id: string | null
  context_version_id: string | null
  narrative_artifact_id: string | null
  narrative_request_id: string
  narrative_progress: NonNullable<NarrativeRegenerationResponse['progress_stages']>
  options: TrpgOption[]
  state_changes: Record<string, unknown>
  state_changes_result: { applied: string[]; ignored: string[] }
  option_id: string | null
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
