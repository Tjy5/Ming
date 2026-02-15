export type DecreeType =
  | 'tax_increase' | 'tax_decrease'
  | 'recruit_troops' | 'disband_troops'
  | 'personnel' | 'diplomacy'
  | 'disaster_relief' | 'harsh_punishment'

export type RegionControl = '朝廷' | '失控' | '沦陷'
export type RegionThreat = 'none' | '后金' | '民变' | '土司' | '海盗'
export type TaxContribution = 'low' | 'medium' | 'high'
export type PersonnelAction = 'appoint' | 'dismiss'
export type DiplomacyTarget = '后金' | '蒙古' | '朝鲜'
export type EventUrgency = '高' | '中' | '低'
export type MinisterStatus = 'active' | 'idle'

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

export interface Minister {
  name: string
  faction: string
  personality_tags: string[]
  abilities: MinisterAbilities
  status: MinisterStatus
}

export interface EventChoice {
  label: string
  description: string
  decrees: StructuredDecree[]
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
}

export interface HistoryEntry {
  year: number
  month: number
  decree_type: string
  decree_desc: string
  delta: Record<string, number>
  narrative: string
}

export interface GameState {
  time: GameTime
  treasury: number
  population: number
  military_supply: number
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
  event_cooldowns: Record<string, number>
  resolved_script_ids: string[]
}

export interface StructuredDecree {
  type: DecreeType
  target?: string | null
  sub_action?: PersonnelAction | null
  parameters?: Record<string, unknown> | null
}

export interface DecreeResponse {
  state: GameState
  delta: Record<string, number>
  attribution: Record<string, Record<string, number>>
  narrative: string
  newly_triggered_events: string[]
  game_time: GameTime
  game_over: { result: 'victory' | 'defeat'; message: string } | null
}

export interface ErrorResponse {
  error_code: string
  message: string
  details?: { ai_narrative?: string } | null
}

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
  portrait_supported: boolean
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

export const REGION_NAMES = ['京畿', '辽东', '陕西', '江南', '中原', '山东', '云贵', '川蜀'] as const
export const DIPLOMACY_TARGETS: DiplomacyTarget[] = ['后金', '蒙古', '朝鲜']

export const TARGET_REQUIRED: Partial<Record<DecreeType, string>> = {
  disaster_relief: 'region',
  personnel: 'person',
  diplomacy: 'diplomacy_target',
}

export interface PreconditionRule {
  field: keyof Pick<GameState, 'treasury' | 'population' | 'military_supply' | 'civil_morale' | 'military_morale' | 'court_prestige'>
  op: '>' | '>='
  threshold: number
}

export const PRECONDITIONS: Record<DecreeType, PreconditionRule[]> = {
  tax_increase: [{ field: 'civil_morale', op: '>', threshold: 10 }],
  tax_decrease: [{ field: 'treasury', op: '>', threshold: 20 }],
  recruit_troops: [{ field: 'treasury', op: '>=', threshold: 20 }, { field: 'population', op: '>=', threshold: 10 }],
  disband_troops: [{ field: 'military_supply', op: '>', threshold: 10 }],
  personnel: [{ field: 'court_prestige', op: '>', threshold: 10 }],
  diplomacy: [{ field: 'treasury', op: '>=', threshold: 10 }],
  disaster_relief: [{ field: 'treasury', op: '>=', threshold: 30 }],
  harsh_punishment: [{ field: 'court_prestige', op: '>', threshold: 5 }],
}

export const PRECONDITION_MESSAGES: Record<DecreeType, string> = {
  tax_increase: '民心不足，恐激民变（需要民心>10）',
  tax_decrease: '国库不足，无力减税（需要钱粮>20）',
  recruit_troops: '钱粮或人口不足，无法征兵（需要钱粮>=20且人口>=10）',
  disband_troops: '军备不足（需要军备>10）',
  personnel: '朝廷威望不足（需要威望>10）',
  diplomacy: '国库不足，无力外交（需要钱粮>=10）',
  disaster_relief: '国库不足，无法赈灾（需要钱粮>=30）',
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
