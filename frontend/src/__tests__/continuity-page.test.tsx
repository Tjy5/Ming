// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import ContinuityPage from '../pages/ContinuityPage'
import { useStore } from '../hooks/store'
import type { GameState } from '../types/game'

vi.mock('../api/worlds', () => ({
  worldsApi: {
    listBranches: vi.fn().mockResolvedValue({ branches: [{ game_id: 'g1', branch_id: 'b1', head_version_id: 'v1', created_at: '2026-01-01T00:00:00Z', status: 'active' }] }),
    listVersions: vi.fn().mockResolvedValue({ versions: [{ game_id: 'g1', branch_id: 'b1', version_id: 'v1', created_at: '2026-01-01T00:00:00Z', protected: true }] }),
    listBookmarks: vi.fn().mockResolvedValue({ bookmarks: [] }),
    retentionReport: vi.fn().mockResolvedValue({ game_id: 'g1', branch_id: 'b1', recent_limit: 100, protected_version_ids: ['v1'], monthly_recovery_version_ids: [], delete_version_ids: [] }),
    createBookmark: vi.fn().mockResolvedValue({ bookmark: { bookmark_id: 'bm1', game_id: 'g1', branch_id: 'b1', version_id: 'v1', name: '朝议', created_at: '2026-01-01T00:00:00Z' } }),
    deleteBookmark: vi.fn().mockResolvedValue(null),
    switchBranch: vi.fn(),
    forkVersion: vi.fn(),
    continueActivity: vi.fn(),
    getSettlement: vi.fn(),
  },
}))

afterEach(() => {
  cleanup()
  useStore.getState().reset()
  vi.clearAllMocks()
})

const state = {
  world_metadata: {
    schema_version: 1,
    calendar_schema_version: 'yuanming-calendar-v1',
    game_id: 'g1',
    branch_id: 'b1',
    version_id: 'v1',
    source_kind: 'initial',
  },
  activities: [],
} as unknown as GameState

describe('ContinuityPage', () => {
  it('renders branch, version, bookmark, and retention sections from typed adapters', async () => {
    useStore.getState().setState(state)
    render(<BrowserRouter><ContinuityPage /></BrowserRouter>)

    expect(screen.getByRole('heading', { name: '世界连续性' })).toBeTruthy()
    await waitFor(() => expect(screen.getAllByText('b1').length).toBeGreaterThan(0))
    expect(screen.getByText('世界分支')).toBeTruthy()
    expect(screen.getByText('版本链')).toBeTruthy()
    expect(screen.getByText('保留计划')).toBeTruthy()
    expect(screen.getByText('保护版本')).toBeTruthy()
  })

  it('submits a bookmark for the selected immutable version', async () => {
    useStore.getState().setState(state)
    render(<BrowserRouter><ContinuityPage /></BrowserRouter>)

    await waitFor(() => expect(screen.getByText('v1')).toBeTruthy())
    fireEvent.change(screen.getByRole('textbox', { name: '书签名称' }), { target: { value: '权力真空' } })
    fireEvent.click(screen.getByRole('button', { name: '保护当前版本' }))

    const { worldsApi } = await import('../api/worlds')
    await waitFor(() => expect(worldsApi.createBookmark).toHaveBeenCalledWith('g1', expect.objectContaining({ version_id: 'v1', name: '权力真空' })))
  })
})
