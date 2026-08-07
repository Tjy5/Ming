import type { components as OpenApiComponents } from './generated'

type OpenApiSchemas = OpenApiComponents['schemas']

export type ApiGameState = OpenApiSchemas['GameState']
export type ApiTurnSummary = OpenApiSchemas['TurnSummary']
export type ApiEventChoice = OpenApiSchemas['EventChoice']
export type ApiDecreeResponse = OpenApiSchemas['DecreeResponse']

export type DecreeType =
  | 'tax_increase' | 'tax_decrease'
  | 'recruit_troops' | 'disband_troops'
  | 'personnel' | 'diplomacy'
  | 'disaster_relief' | 'harsh_punishment'

export type RegionControl = '朝廷' | '失控' | '沦陷'
export type RegionThreat = 'none' | '元军' | '汉军' | '吴军' | '民变' | '土司' | '海盗'
export type TaxContribution = 'low' | 'medium' | 'high'
export type PersonnelAction = 'appoint' | 'dismiss' | 'execute'
export type DiplomacyTarget = '龙凤政权' | '汉政权' | '吴政权' | '元廷' | '东南群雄'
export type EventUrgency = '高' | '中' | '低'
export type MinisterStatus = 'active' | 'idle' | 'removed' | 'not_yet_entered' | 'on_mission'
export type AssemblyPhase = 'idle' | 'petition' | 'debate' | 'vote' | 'decree'

export interface GameTime {
  year: number
  month: number
  era_name: string
  era_year: number
}

export interface Faction {
  name: string
  satisfaction: number
  influence: number
  rebellion_risk: number
}

export interface Region {
  name: string
  stability: number
  garrison: number
  control: RegionControl
  threat: RegionThreat
  tax_contribution: TaxContribution
  civil_morale: number
  rebellion_risk: number
  tax_rate: number
  tax_collected: number
  disaster_level: number
}

export interface MinisterAbilities {
  civil: number
  military: number
  diplomacy: number
}

export interface MissionState {
  name: string
  progress_months: number
  total_months: number
  cost: number
  effects: Record<string, number | string>
}

export interface Minister {
  name: string
  faction: string
  personality_tags: string[]
  abilities: MinisterAbilities
  status: MinisterStatus
  loyalty: number
  positions: string[]
  is_eunuch: boolean
  entry_year: number
  entry_month: number
  historical_note: string
  biography?: string
  major_contributions?: string[]
  current_mission?: MissionState | null
}

export interface EventChoice {
  label: string
  description: string
  decrees: StructuredDecree[]
  loyalty_effects?: [string, number][]
  state_effects?: Partial<Record<string, number | string | boolean>>
}

export interface GameEvent {
  name: string
  description: string
  urgency: EventUrgency
  triggered_year: number
  triggered_month: number
  rich_description: string
  choices: EventChoice[]
  is_scripted: boolean
  is_blocking: boolean
  script_id: string | null
  historical_hint?: string
  historical_basis?: string
}

export interface HistoryEntry {
  year: number
  month: number
  decree_type: string
  decree_desc: string
  delta: Record<string, number>
  narrative: string
}

export interface TriggerDecision {
  should_trigger: boolean
  reason: string
  timestamp: string
}

export interface GameState {
  time: GameTime
  // phase state machine: life_story (跑团叙事) / governance (治理模拟)，由后端驱动
  phase: 'life_story' | 'governance'
  // 人生篇章 id：childhood/monk_wanderer/enlistment/warlord
  chapter: string
  chapter_turns: number
  national_treasury: number
  imperial_treasury: number
  grain: number
  population: number
  military_strength: number
  civil_morale: number
  military_morale: number
  court_prestige: number
  factions: Faction[]
  regions: Region[]
  ministers: Minister[]
  active_events: GameEvent[]
  history_log: HistoryEntry[]
  history_total_count?: number
  decree_count: number
  decrees_this_month: Record<string, boolean>
  event_cooldowns: Record<string, number>
  resolved_script_ids: string[]
  memorials?: Memorial[]
  last_assembly?: CourtAssembly | null
  last_assembly_month?: number
  memorial_cooldowns?: Record<string, number>
  consecutive_waits?: number
  loyalty_zero_triggered?: string[]
  minister_conversations?: Record<string, ConversationMessage[]>
  trigger_decisions?: Record<string, TriggerDecision>
}

export interface StructuredDecree {
  type: DecreeType
  target?: string | null
  sub_action?: PersonnelAction | null
  parameters?: Record<string, unknown> | null
}

export type MemorialStatus = 'pending' | 'approved' | 'rejected' | 'deferred'

export interface Memorial {
  id: string
  author_name: string
  author_faction: string
  title: string
  content: string
  suggested_decrees: StructuredDecree[]
  trigger_reason: string
  urgency: string
  created_year: number
  created_month: number
  status: MemorialStatus
  resolution_result?: MemorialResolutionResult | null
}

export interface MinisterReaction {
  minister_name: string
  faction: string
  reaction_type: string
  reaction_text: string
  loyalty_change: number
}

export interface MemorialResolutionResult {
  action: 'approved' | 'rejected' | 'deferred'
  narrative?: string | null
  delta?: Record<string, number> | null
  minister_reactions?: MinisterReaction[] | null
}

export interface AssemblyParticipant {
  name: string
  faction: string
  position: string
  argument_text: string
}

export interface PolicySuggestion {
  title: string
  description: string
  related_decree: StructuredDecree
  supporter_names: string[]
}

export interface AssemblyPetition {
  minister_name: string
  content: string
  urgency: '高' | '中' | '低'
}

export interface AssemblySpeech {
  minister_name: string
  faction: string
  content: string
  stance: '赞成' | '反对' | '中立'
}

export interface AssemblyVote {
  minister_name: string
  vote: '赞成' | '反对' | '弃权'
  reason: string
}

export interface CourtAssembly {
  topic: string
  current_topic?: string
  decree_type: DecreeType | null
  phase?: AssemblyPhase
  participants: AssemblyParticipant[]
  petitions?: AssemblyPetition[]
  speeches?: AssemblySpeech[]
  votes?: AssemblyVote[]
  suggestions: PolicySuggestion[]
  debate_text: string
  consensus: string
  silenced: boolean
  rage_used?: boolean
  silenced_factions?: string[]
  final_decision?: string | null
}

export interface IndicatorTrend {
  name: string
  before: number
  after: number
}

export interface FactionChange {
  name: string
  satisfaction_before: number
  satisfaction_after: number
  rebellion_risk_before: number
  rebellion_risk_after: number
}

export interface RegionChange {
  name: string
  stability_before: number
  stability_after: number
  control_before: string
  control_after: string
  threat_before: string
  threat_after: string
  garrison_before?: number | null
  garrison_after?: number | null
  civil_morale_before?: number | null
  civil_morale_after?: number | null
  rebellion_risk_before?: number | null
  rebellion_risk_after?: number | null
  disaster_level_before?: number | null
  disaster_level_after?: number | null
  tax_collected_before?: number | null
  tax_collected_after?: number | null
  tax_rate_before?: number | null
  tax_rate_after?: number | null
  tax_contribution_before?: string | null
  tax_contribution_after?: string | null
}

export interface MinisterChange {
  name: string
  loyalty_before: number
  loyalty_after: number
  status_before: string
  status_after: string
}

export interface RegionDetail {
  region: string
  field: string
  delta: number
  source: string
}

export interface TurnSummary {
  year: number
  month: number
  era_name: string
  era_year: number
  commentary: string
  major_events: string[]
  indicator_trends: IndicatorTrend[]
  faction_changes: FactionChange[]
  region_changes: RegionChange[]
  minister_changes: MinisterChange[]
  pending_memorials_count: number
  region_details?: RegionDetail[] | null
  action_implications?: string[]
}

export type ModalType =
  | 'game_over'
  | 'script_event_blocking'
  | 'narrative'
  | 'turn_summary'
  | 'memorial'
  | 'assembly'
  | 'script_event'

interface BaseModalItem {
  priority: number
}

export type ModalItem =
  | (BaseModalItem & { type: 'game_over'; payload: { result: 'victory' | 'defeat'; message: string } })
  | (BaseModalItem & { type: 'script_event_blocking'; payload: GameEvent })
  | (BaseModalItem & { type: 'narrative'; payload: { narrative: string; delta: Record<string, number>; ministerReactions?: MinisterReaction[]; turnSummary?: TurnSummary } })
  | (BaseModalItem & { type: 'turn_summary'; payload: TurnSummary })
  | (BaseModalItem & { type: 'memorial'; payload: Memorial[] })
  | (BaseModalItem & { type: 'assembly'; payload: CourtAssembly })
  | (BaseModalItem & { type: 'script_event'; payload: GameEvent })

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'minister'
  content: string
  timestamp: string | number
}

export interface DecreeResponse {
  state: GameState
  delta: Record<string, number>
  attribution: Record<string, Record<string, number>>
  narrative: string
  newly_triggered_events: string[]
  game_time: GameTime
  game_over: { result: 'victory' | 'defeat'; message: string } | null
  minister_reactions: MinisterReaction[]
  turn_summary: TurnSummary | null
  memorial_triggers: Memorial[]
}

export interface MemorialResolveResponse {
  state: GameState
  action: string
  narrative?: string
  delta?: Record<string, number>
  minister_reactions?: MinisterReaction[]
}

export interface ErrorResponse {
  error_code: string
  message: string
  details?: Record<string, unknown> | null
}

export interface DialogueMessage {
  role: 'user' | 'minister'
  content: string
  timestamp?: number
}

export interface DialogueResponse {
  reply: string
  loyalty_change: number
  mood: string
  conversation_id: string
  state: GameState
}

export type ChatIntent = 'query' | 'execute' | 'advance_month'

export interface ChatGameOver {
  result: 'victory' | 'defeat'
  message: string
}

export interface ChatDonePayload {
  reply: string
  state: GameState
  effects_applied: boolean
  narrative?: string
  intent?: ChatIntent
  minister_reactions?: MinisterReaction[]
  triggered_events?: string[]
  new_ministers?: string[]
  game_over?: ChatGameOver | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  intent?: ChatIntent
  effectsApplied?: boolean
  effectsSummary?: string
  effectsDelta?: Record<string, number>
  ministerReactions?: MinisterReaction[]
  triggeredEvents?: string[]
  newMinisters?: string[]
  gameOver?: ChatGameOver | null
}

export type ChatStreamEvent =
  | { event: 'intent'; data: { intent: ChatIntent; confidence: number; reason: string } }
  | { event: 'narrative_chunk'; data: { chunk: string } }
  | { event: 'effects'; data: { delta: Record<string, number>; summary: string } }
  | { event: 'reactions'; data: { minister_reactions: MinisterReaction[] } }
  | { event: 'state'; data: { state: GameState } }
  | { event: 'done'; data: ChatDonePayload }
  | { event: 'error'; data: { status: number; detail: ErrorResponse } }

export interface DebateMinister {
  name: string
  faction: string
  position_summary: string
}

export interface DebateResult {
  debate_text: string
  minister_a: DebateMinister
  minister_b: DebateMinister
  option_a: StructuredDecree
  option_b: StructuredDecree
  keywords: string[]
}

export interface Capabilities {
  debate_supported: boolean

  assembly_supported: boolean
  memorial_enabled: boolean
}

export const DEFAULT_CAPABILITIES: Capabilities = { debate_supported: false, assembly_supported: false, memorial_enabled: false }

export type AIProvider = 'mock' | 'openai' | 'google' | 'h' | 'Z' | (string & {})

export interface AISettings {
  provider: AIProvider
  provider_type?: string
  api_key: string
  base_url: string
  model: string
  simple_model?: string
  enable_thinking?: boolean
  enable_thinking_simple?: boolean
  thinking_config?: Record<string, string | boolean | number>
  thinking_config_simple?: Record<string, string | boolean | number>
  provider_options: AIProvider[]
}

export interface AIModelListResponse {
  provider: AIProvider
  models: string[]
  source: string
}

export interface SaveEntry {
  id: number
  name: string
  game_time: string
  created_at: string
}

export interface HistoryPage {
  total: number
  offset: number
  limit: number
  entries: HistoryEntry[]
}

export const DECREE_LABELS: Record<DecreeType, string> = {
  tax_increase: '加税',
  tax_decrease: '减税',
  recruit_troops: '增兵',
  disband_troops: '裁兵',
  personnel: '任免',
  diplomacy: '外交',
  disaster_relief: '赈灾',
  harsh_punishment: '严刑',
}

export const DECREE_TYPES: DecreeType[] = [
  'tax_increase', 'tax_decrease', 'recruit_troops', 'disband_troops',
  'personnel', 'diplomacy', 'disaster_relief', 'harsh_punishment',
]

export const REGION_NAMES = ['应天', '太平', '镇江', '两淮', '杭州', '武昌', '平江', '大都'] as const
export const DIPLOMACY_TARGETS: DiplomacyTarget[] = ['龙凤政权', '汉政权', '吴政权', '元廷', '东南群雄']

export const TARGET_REQUIRED: Partial<Record<DecreeType, string>> = {
  disaster_relief: 'region',
  personnel: 'person',
  diplomacy: 'diplomacy_target',
}

export interface PreconditionRule {
  field: keyof Pick<GameState, 'national_treasury' | 'imperial_treasury' | 'grain' | 'population' | 'military_strength' | 'civil_morale' | 'military_morale' | 'court_prestige'>
  op: '>' | '>='
  threshold: number
}

export const PRECONDITIONS: Record<DecreeType, PreconditionRule[]> = {
  tax_increase: [{ field: 'civil_morale', op: '>', threshold: 5 }],
  tax_decrease: [{ field: 'national_treasury', op: '>', threshold: 8 }],
  recruit_troops: [{ field: 'national_treasury', op: '>=', threshold: 8 }, { field: 'population', op: '>=', threshold: 1200 }],
  disband_troops: [{ field: 'military_strength', op: '>', threshold: 8 }],
  personnel: [{ field: 'court_prestige', op: '>', threshold: 10 }],
  diplomacy: [{ field: 'national_treasury', op: '>=', threshold: 5 }],
  disaster_relief: [{ field: 'national_treasury', op: '>=', threshold: 6 }, { field: 'grain', op: '>=', threshold: 120 }],
  harsh_punishment: [{ field: 'court_prestige', op: '>', threshold: 5 }],
}

export const PRECONDITION_MESSAGES: Record<DecreeType, string> = {
  tax_increase: '民心过低，仓促加税恐激民变（需要民心>5）',
  tax_decrease: '国库存银不足，无力减税（需要国库>8万两）',
  recruit_troops: '银粮或人口不足，无法征兵（需要国库>=8万两且人口>=1200万人）',
  disband_troops: '兵力不足（需要兵力>8万人）',
  personnel: '朝廷威望不足（需要威望>10）',
  diplomacy: '国库存银不足，无力外交（需要国库>=5万两）',
  disaster_relief: '银粮不足，无法赈灾（需要国库>=6万两且粮草>=120万石）',
  harsh_punishment: '朝廷威望不足（需要威望>5）',
}

export const DEBATE_TOPICS: Record<DecreeType, { topic: string; decreeType: DecreeType }[]> = {
  tax_increase: [{ topic: '是否加征赋税以充实国库', decreeType: 'tax_increase' }],
  tax_decrease: [{ topic: '是否减免赋税与民休息', decreeType: 'tax_decrease' }],
  recruit_troops: [{ topic: '是否征兵备战', decreeType: 'recruit_troops' }],
  disband_troops: [{ topic: '是否裁撤冗兵', decreeType: 'disband_troops' }],
  personnel: [{ topic: '朝廷人事任免', decreeType: 'personnel' }],
  diplomacy: [{ topic: '外交邦交策略', decreeType: 'diplomacy' }],
  disaster_relief: [{ topic: '赈灾方略', decreeType: 'disaster_relief' }],
  harsh_punishment: [{ topic: '严刑峻法之议', decreeType: 'harsh_punishment' }],
}
