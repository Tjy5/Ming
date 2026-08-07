/**
 * TRPG API 封装：GET /api/trpg/character（角色卡/成长记录/篇章节奏）
 * 与 POST /api/trpg/act（行动 → D100 检定 → AI 主持人叙事+分支）。
 * 复用 client.ts 的 request 基础设施（BASE/错误归一化）。
 */
import { request } from './client'
import type { ActPayload, ActResponse, CharacterResponse } from '../types/trpg'

export const trpgApi = {
  getCharacter: (signal?: AbortSignal) =>
    request<CharacterResponse>('/trpg/character', { signal }),

  act: (payload: ActPayload, signal?: AbortSignal) =>
    request<ActResponse>('/trpg/act', {
      method: 'POST',
      signal,
      body: JSON.stringify({
        action_text: payload.action_text,
        skill: payload.skill ?? null,
        attr: payload.attr ?? null,
        difficulty: payload.difficulty ?? '常规',
      }),
    }),
}
