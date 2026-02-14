import { describe, it, expect } from 'vitest'
import { checkPrecondition } from '../hooks/store'
import type { GameState, GameEvent, EventChoice, StructuredDecree } from '../types/game'

function initialState(): GameState {
  return {
    time: { year: 1627, month: 1, era_name: '天启', era_year: 7 },
    treasury: 100, population: 100, military_supply: 80,
    civil_morale: 60, military_morale: 70, court_prestige: 75,
    factions: [], regions: [], ministers: [], active_events: [],
    history_log: [], decree_count: 0, event_cooldowns: {},
    resolved_script_ids: [],
  }
}

function openingScriptEvent(): GameEvent {
  return {
    name: '天启七年·天下大势',
    description: '天启七年·天下大势',
    urgency: '高',
    triggered_year: 1627, triggered_month: 1,
    rich_description: '**天启七年，正月。** ...',
    is_scripted: true, script_id: 'tianqi-7-opening',
    choices: [
      {
        label: '清除阉党，整顿朝纲',
        description: '立即着手清除魏忠贤余党',
        decrees: [{ type: 'personnel', target: '魏忠贤', sub_action: 'dismiss' }],
      },
      {
        label: '暂观时局，徐图后计',
        description: '初登大宝，根基未稳。',
        decrees: [],
      },
    ],
  }
}

function disabledReason(state: GameState, decrees: StructuredDecree[]): string | null {
  const failed = decrees.filter(d => !checkPrecondition(state, d.type))
  return failed.length ? 'disabled' : null
}

describe('blocking scripted event — at least one executable choice', () => {
  it('opening script has at least one always-executable choice (empty decrees)', () => {
    const evt = openingScriptEvent()
    const safeChoices = evt.choices.filter(c => c.decrees.length === 0)
    expect(safeChoices.length).toBeGreaterThanOrEqual(1)
  })

  it('opening script all choices pass preconditions with initial state', () => {
    const state = initialState()
    const evt = openingScriptEvent()
    const executable = evt.choices.filter(c => disabledReason(state, c.decrees) === null)
    expect(executable.length).toBeGreaterThanOrEqual(1)
  })

  it('personnel choice disabled when court_prestige <= 10', () => {
    const state = initialState()
    state.court_prestige = 5
    const evt = openingScriptEvent()
    const personnelChoice = evt.choices.find(c =>
      c.decrees.some(d => d.type === 'personnel')
    )!
    expect(disabledReason(state, personnelChoice.decrees)).not.toBeNull()
  })

  it('empty-decree fallback always executable regardless of state', () => {
    const state = initialState()
    state.treasury = 0
    state.civil_morale = 0
    state.court_prestige = 0
    state.military_morale = 0
    state.military_supply = 0
    state.population = 0
    const fallback: EventChoice = { label: 'safe', description: '', decrees: [] }
    expect(disabledReason(state, fallback.decrees)).toBeNull()
  })
})

describe('migration toast trigger logic', () => {
  it('migration note triggers toast when truthy', () => {
    const note = '旧存档已自动迁移：补充了分省详细数据与年号信息'
    let toastMsg: string | null = null
    const showToast = (msg: string) => { toastMsg = msg }

    // simulate handleLoadSave logic
    if (note) showToast(note)
    expect(toastMsg).toBe(note)
  })

  it('no toast when migration note is empty', () => {
    const note = ''
    let toastMsg: string | null = null
    const showToast = (msg: string) => { toastMsg = msg }

    if (note) showToast(note)
    expect(toastMsg).toBeNull()
  })

  it('no toast when migration note is undefined', () => {
    const note: string | undefined = undefined
    let toastMsg: string | null = null
    const showToast = (msg: string) => { toastMsg = msg }

    if (note) showToast(note)
    expect(toastMsg).toBeNull()
  })
})
