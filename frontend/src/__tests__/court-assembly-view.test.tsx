// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import CourtAssemblyView from '../components/CourtAssemblyView'
import type { CourtAssembly, DecreeResponse, GameState } from '../types/game'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

vi.mock('../api/client', () => ({
  api: {
    adoptSuggestion: vi.fn(),
    startAssembly: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number
    body: { message: string }

    constructor(status: number, body: { message: string }) {
      super(body.message)
      this.status = status
      this.body = body
    }
  },
}))

const adoptSuggestionMock = vi.mocked(api.adoptSuggestion)
const startAssemblyMock = vi.mocked(api.startAssembly)

function gameState(): GameState {
  return {
    time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    phase: 'governance',
    chapter: 'warlord',
    chapter_turns: 0,
    national_treasury: 22,
    imperial_treasury: 8,
    grain: 420,
    population: 1600,
    military_strength: 18,
    civil_morale: 62,
    military_morale: 68,
    court_prestige: 62,
    factions: [],
    regions: [],
    ministers: [],
    active_events: [],
    history_log: [],
    decree_count: 1,
    decrees_this_month: {},
    event_cooldowns: {},
    resolved_script_ids: [],
  }
}

function assemblyParticipantRegistry(count: number): NonNullable<GameState['entity_registry']> {
  return Object.fromEntries(Array.from({ length: count }, (_, index) => [
    `participant-${index}`,
    {
      entity_id: `participant-${index}`,
      display_name: `议政主体${index}`,
      entity_type: 'institution',
      status: 'active',
      available: true,
      source: { kind: 'system', summary: 'test assembly participant' },
      institution_kind: 'council',
      permissions: [{
        permission_id: `permission-${index}`,
        capability: 'governance.assembly.participate',
      }],
    },
  ]))
}

function assembly(): CourtAssembly {
  return {
    phase: 'debate',
    topic: '是否加征赋税',
    current_topic: '是否加征赋税',
    decree_type: 'tax_increase',
    participants: [],
    petitions: [],
    speeches: [],
    votes: [],
    suggestions: [{
      title: '朝议方案1',
      description: '这是行动建议而非结果承诺；提交后将依据当前世界重新结算。',
      related_decree: { type: 'tax_increase' },
      supporter_names: ['徐达'],
      suggestion_id: 'suggestion-1',
      source_game_id: 'game-1',
      source_branch_id: 'branch-1',
      source_version_id: 'version-1',
      rationale_factors: [
        { fact_reference: 'version:version-1', label: '来源版本', value: 'version-1' },
        { fact_reference: 'assembly:topic', label: '当前议题', value: '是否加征赋税' },
        { fact_reference: 'entity:xu-da:availability', label: '当前在朝支持者', value: '徐达' },
      ],
    }],
    debate_text: '朝议已完成。',
    consensus: 'support',
    silenced: false,
    rage_used: false,
    silenced_factions: [],
    final_decision: null,
  }
}

function adoptionResponse(mode: 'original' | 'edited' | 'free_input'): DecreeResponse {
  return {
    state: gameState(),
    delta: { national_treasury: 4 },
    attribution: {},
    narrative: '政令已依据当前世界结算执行。',
    newly_triggered_events: [],
    game_time: gameState().time,
    game_over: null,
    minister_reactions: [],
    turn_summary: null,
    memorial_triggers: [],
    suggestion_adoption_mode: mode,
    suggestion_id: mode === 'free_input' ? null : 'suggestion-1',
    suggestion_source_version_id: mode === 'free_input' ? null : 'version-1',
    suggestion_evaluation_version_id: 'version-2',
    suggestion_was_stale: mode !== 'free_input',
    suggestion_rationale_factors: [],
  }
}

function renderAssembly() {
  const onStateUpdate = vi.fn()
  const onAdoptionResult = vi.fn()
  const onClose = vi.fn()
  render(
    <CourtAssemblyView
      assembly={assembly()}
      onStateUpdate={onStateUpdate}
      onAdoptionResult={onAdoptionResult}
      onClose={onClose}
      asModal
    />,
  )
  return { onStateUpdate, onAdoptionResult, onClose }
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
})

describe('CourtAssemblyView 候选依据与采用模式', () => {
  it('disables convening when fewer than ten active ministers are available', () => {
    render(
      <CourtAssemblyView
        state={gameState()}
        capabilities={{ debate_supported: true, assembly_supported: true, memorial_enabled: true }}
        loading={false}
        onStateUpdate={vi.fn()}
      />,
    )

    expect(screen.getByText('在朝大臣不足 10 人，无法召开朝会')).toBeTruthy()
    const conveneButton = screen.getByRole('button', { name: '召开朝会' }) as HTMLButtonElement
    expect(conveneButton.disabled).toBe(true)

    fireEvent.click(conveneButton)

    expect(startAssemblyMock).not.toHaveBeenCalled()
  })

  it('counts eligible registry actors when deciding whether the backend participant minimum is met', async () => {
    startAssemblyMock.mockResolvedValue({
      ...assembly(),
      phase: 'petition',
    })
    render(
      <CourtAssemblyView
        state={{ ...gameState(), entity_registry: assemblyParticipantRegistry(10) }}
        capabilities={{ debate_supported: true, assembly_supported: true, memorial_enabled: true }}
        loading={false}
        onStateUpdate={vi.fn()}
      />,
    )

    expect(screen.queryByText('在朝大臣不足 10 人，无法召开朝会')).toBeNull()
    const conveneButton = screen.getByRole('button', { name: '召开朝会' }) as HTMLButtonElement
    expect(conveneButton.disabled).toBe(false)

    await act(async () => {
      fireEvent.click(conveneButton)
    })

    expect(startAssemblyMock).toHaveBeenCalledTimes(1)
  })

  it('does not block a versioned registry vacuum that the backend restores through continuity', async () => {
    startAssemblyMock.mockResolvedValue({
      ...assembly(),
      phase: 'petition',
    })
    const nonParticipantRegistry = assemblyParticipantRegistry(1)
    Object.values(nonParticipantRegistry)[0].permissions = []
    render(
      <CourtAssemblyView
        state={{
          ...gameState(),
          world_metadata: {
            schema_version: 1,
            calendar_schema_version: 'yuanming-calendar-v1',
            game_id: 'game-1',
            branch_id: 'branch-1',
            version_id: 'version-1',
            source_kind: 'settlement',
          },
          entity_registry: nonParticipantRegistry,
        }}
        capabilities={{ debate_supported: true, assembly_supported: true, memorial_enabled: true }}
        loading={false}
        onStateUpdate={vi.fn()}
      />,
    )

    const conveneButton = screen.getByRole('button', { name: '召开朝会' }) as HTMLButtonElement
    expect(conveneButton.disabled).toBe(false)
    await act(async () => {
      fireEvent.click(conveneButton)
    })
    expect(startAssemblyMock).toHaveBeenCalledTimes(1)
  })

  it('treats an empty registry as a legacy roster instead of a continuity vacuum', () => {
    render(
      <CourtAssemblyView
        state={{ ...gameState(), entity_registry: {} }}
        capabilities={{ debate_supported: true, assembly_supported: true, memorial_enabled: true }}
        loading={false}
        onStateUpdate={vi.fn()}
      />,
    )

    expect(screen.getByText('在朝大臣不足 10 人，无法召开朝会')).toBeTruthy()
    expect((screen.getByRole('button', { name: '召开朝会' }) as HTMLButtonElement).disabled).toBe(true)
    expect(startAssemblyMock).not.toHaveBeenCalled()
  })

  it('excludes registry entries outside the backend actor projection', () => {
    const officeRegistry = assemblyParticipantRegistry(10)
    for (const entity of Object.values(officeRegistry)) {
      entity.entity_type = 'office'
    }
    render(
      <CourtAssemblyView
        state={{ ...gameState(), entity_registry: officeRegistry }}
        capabilities={{ debate_supported: true, assembly_supported: true, memorial_enabled: true }}
        loading={false}
        onStateUpdate={vi.fn()}
      />,
    )

    expect(screen.getByText('在朝大臣不足 10 人，无法召开朝会')).toBeTruthy()
    expect((screen.getByRole('button', { name: '召开朝会' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('renders safe factors in a folded detail and submits original provenance', async () => {
    adoptSuggestionMock.mockResolvedValue(adoptionResponse('original'))
    const { onAdoptionResult, onClose } = renderAssembly()

    expect(screen.getByText('朝议方案1')).toBeTruthy()
    expect(screen.getByText(/仅供启发/)).toBeTruthy()
    expect(screen.queryByText(/RAW_PRIVATE_REASONING|RAW_PROVIDER/)).toBeNull()
    const details = screen.getByText('查看可核验依据').closest('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    fireEvent.click(screen.getByText('查看可核验依据'))
    expect(details.open).toBe(true)
    expect(screen.getByText('当前在朝支持者：')).toBeTruthy()
    expect(screen.getByText('徐达')).toBeTruthy()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '原样采用' }))
    })

    expect(adoptSuggestionMock).toHaveBeenCalledWith({
      mode: 'original',
      suggestion_index: 0,
      suggestion_id: 'suggestion-1',
      source_version_id: 'version-1',
    }, expect.any(AbortSignal))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onAdoptionResult).toHaveBeenCalledWith(expect.objectContaining({
      suggestion_adoption_mode: 'original',
      narrative: '政令已依据当前世界结算执行。',
    }))
  })

  it('edits the player intent while preserving candidate provenance', async () => {
    adoptSuggestionMock.mockResolvedValue(adoptionResponse('edited'))
    renderAssembly()

    fireEvent.click(screen.getByRole('button', { name: '编辑采用' }))
    const editor = screen.getByLabelText(/编辑行动意图/) as HTMLTextAreaElement
    fireEvent.change(editor, { target: { value: '先核查民户，再分区加征' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '确认编辑并采用' }))
    })

    expect(adoptSuggestionMock).toHaveBeenCalledWith({
      mode: 'edited',
      suggestion_index: 0,
      suggestion_id: 'suggestion-1',
      source_version_id: 'version-1',
      edited_text: '先核查民户，再分区加征',
    }, expect.any(AbortSignal))
  })

  it('keeps free input available outside the candidate whitelist', async () => {
    adoptSuggestionMock.mockResolvedValue(adoptionResponse('free_input'))
    renderAssembly()

    const freeInput = screen.getByLabelText('不采用候选，自由输入行动')
    fireEvent.change(freeInput, { target: { value: '开仓募工，修筑河堤' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '提交自由行动' }))
    })

    expect(adoptSuggestionMock).toHaveBeenCalledWith({
      mode: 'free_input',
      free_text: '开仓募工，修筑河堤',
    }, expect.any(AbortSignal))
  })
})
