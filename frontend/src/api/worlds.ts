// OpenAPI-backed adapters. Keep payload shapes sourced from generated.ts; regenerate after backend schema changes.
import type { components as OpenApiComponents } from '../types/generated'
import { request } from './client'

type Schemas = OpenApiComponents['schemas']

export type WorldBranchRef = Schemas['WorldBranchRef']
export type WorldVersionRef = Schemas['WorldVersionRef']
export type WorldBookmarkRef = Schemas['WorldBookmarkRef']
export type WorldBookmarkRequest = Schemas['WorldBookmarkRequest']
export type WorldBranchListResponse = Schemas['WorldBranchListResponse']
export type WorldVersionListResponse = Schemas['WorldVersionListResponse']
export type WorldBookmarkListResponse = Schemas['WorldBookmarkListResponse']
export type WorldRetentionResponse = Schemas['WorldRetentionResponse']
export type WorldRetentionCollectRequest = Schemas['WorldRetentionCollectRequest']
export type WorldRetentionCollectResponse = Schemas['WorldRetentionCollectResponse']
export type WorldLifecycleResponse = Schemas['WorldLifecycleResponse']
export type SettlementFacts = Schemas['SettlementFacts']
export type Activity = Schemas['Activity']
export type ActivityContinueRequest = Schemas['ActivityContinueRequest']
export type ActivityBatchExecutionResponse = Schemas['ActivityBatchExecutionResponse']
export type WorldStateProjection = Schemas['WorldStateProjection']

const encode = (value: string) => encodeURIComponent(value)

export const worldsApi = {
  listBranches: (gameId: string) =>
    request<WorldBranchListResponse>(`/worlds/${encode(gameId)}/branches`),

  listVersions: (gameId: string, branchId: string) =>
    request<WorldVersionListResponse>(`/worlds/${encode(gameId)}/branches/${encode(branchId)}/versions`),

  forkVersion: (gameId: string, versionId: string) =>
    request<WorldLifecycleResponse>(`/worlds/${encode(gameId)}/versions/${encode(versionId)}/branch`, {
      method: 'POST',
    }),

  switchBranch: (gameId: string, branchId: string) =>
    request<WorldLifecycleResponse>('/worlds/switch', {
      method: 'POST',
      body: JSON.stringify({ game_id: gameId, branch_id: branchId }),
    }),

  listBookmarks: (gameId: string, branchId?: string) => {
    const query = branchId ? `?branch_id=${encode(branchId)}` : ''
    return request<WorldBookmarkListResponse>(`/worlds/${encode(gameId)}/bookmarks${query}`)
  },

  createBookmark: (gameId: string, payload: WorldBookmarkRequest) =>
    request<{ bookmark: WorldBookmarkRef }>(`/worlds/${encode(gameId)}/bookmarks`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteBookmark: (gameId: string, bookmarkId: string) =>
    request<null>(`/worlds/${encode(gameId)}/bookmarks/${encode(bookmarkId)}`, { method: 'DELETE' }),

  retentionReport: (gameId: string, branchId?: string, recentLimit?: number) => {
    const params = new URLSearchParams()
    if (branchId) params.set('branch_id', branchId)
    if (recentLimit !== undefined) params.set('recent_limit', String(recentLimit))
    const query = params.toString() ? `?${params.toString()}` : ''
    return request<WorldRetentionResponse>(`/worlds/${encode(gameId)}/retention${query}`)
  },

  collectRetention: (gameId: string, payload: WorldRetentionCollectRequest) =>
    request<WorldRetentionCollectResponse>(`/worlds/${encode(gameId)}/retention/collect`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getSettlement: (settlementId: string) =>
    request<SettlementFacts>(`/settlements/${encode(settlementId)}`),

  getActivity: (gameId: string, branchId: string, activityId: string) =>
    request<Activity>(`/activities/${encode(gameId)}/${encode(branchId)}/${encode(activityId)}`),

  continueActivity: (activityId: string, payload: ActivityContinueRequest) =>
    request<ActivityBatchExecutionResponse>(`/activities/${encode(activityId)}/continue`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getProjection: (gameId: string, branchId: string, versionId: string) =>
    request<WorldStateProjection>(`/world-state/${encode(gameId)}/${encode(branchId)}/${encode(versionId)}`),
}

// Domain alias used by continuity-oriented consumers; both names share one adapter owner.
export const continuityApi = worldsApi
