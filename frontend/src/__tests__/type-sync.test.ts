import { describe, expect, expectTypeOf, it } from 'vitest'
import type {
  ApiEventChoice,
  ApiGameState,
  ApiTurnSummary,
  EventChoice,
  GameEvent,
  GameState,
  ModalItem,
  TurnSummary,
} from '../types/game'

function assertNever(value: never): never {
  throw new Error(`Unhandled modal item: ${JSON.stringify(value)}`)
}

function modalPayloadKind(item: ModalItem): string {
  switch (item.type) {
    case 'game_over':
      return item.payload.result
    case 'script_event_blocking':
    case 'script_event':
      return item.payload.script_id ?? 'script'
    case 'narrative':
      return item.payload.narrative
    case 'turn_summary':
      return item.payload.commentary
    case 'memorial':
      return String(item.payload.length)
    case 'assembly':
      return item.payload.topic
    default:
      return assertNever(item)
  }
}

describe('OpenAPI type bridge', () => {
  it('keeps generated GameState fields compatible with app GameState', () => {
    expectTypeOf<ApiGameState['memorial_cooldowns']>().toMatchTypeOf<GameState['memorial_cooldowns']>()
    expectTypeOf<ApiGameState['consecutive_waits']>().toMatchTypeOf<GameState['consecutive_waits']>()
    expectTypeOf<ApiGameState['loyalty_zero_triggered']>().toMatchTypeOf<GameState['loyalty_zero_triggered']>()
    expectTypeOf<ApiGameState['minister_conversations']>().toMatchTypeOf<GameState['minister_conversations']>()
    expectTypeOf<ApiGameState['trigger_decisions']>().toMatchTypeOf<GameState['trigger_decisions']>()
  })

  it('keeps generated TurnSummary and EventChoice fields compatible', () => {
    expectTypeOf<ApiTurnSummary['action_implications']>().toMatchTypeOf<TurnSummary['action_implications']>()
    expectTypeOf<ApiEventChoice['loyalty_effects']>().toMatchTypeOf<EventChoice['loyalty_effects']>()
    expectTypeOf<ApiEventChoice['state_effects']>().toMatchTypeOf<EventChoice['state_effects']>()
  })

  it('narrows ModalItem payloads by type', () => {
    const event: GameEvent = {
      name: 'event',
      description: 'event',
      urgency: '中',
      triggered_year: 1628,
      triggered_month: 1,
      rich_description: '',
      choices: [],
      is_scripted: true,
      is_blocking: false,
      script_id: 'event-1',
    }
    const item: ModalItem = { type: 'script_event', priority: 1, payload: event }

    expect(modalPayloadKind(item)).toBe('event-1')
  })
})
