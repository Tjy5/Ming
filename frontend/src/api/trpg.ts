/**
 * TRPG API 封装：GET /api/trpg/character（角色卡/成长记录/篇章节奏）、
 * POST /api/trpg/act（行动 → D100 检定 → AI 主持人叙事+分支）、
 * POST /api/trpg/milestones/{id}/complete（关键事件完成 → 时间对齐/phase 切换）、
 * POST /api/trpg/converge（1360 收束抉择）。
 * 复用 client.ts 的 request 基础设施（BASE/错误归一化）。
 */
import { request } from './client'
import type {
  ActPayload,
  ActResponse,
  CharacterResponse,
  ConvergeChoice,
  ConvergeResponse,
  MilestoneCompleteResponse,
} from '../types/trpg'

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
        // 未指定难度时不传 → 后端按当前章默认难度（篇章 DC 曲线，阶段D 4.1）
        ...(payload.difficulty ? { difficulty: payload.difficulty } : {}),
      }),
    }),

  completeMilestone: (milestoneId: string, signal?: AbortSignal) =>
    request<MilestoneCompleteResponse>(
      `/trpg/milestones/${encodeURIComponent(milestoneId)}/complete`,
      { method: 'POST', signal },
    ),

  converge: (choice: ConvergeChoice, signal?: AbortSignal) =>
    request<ConvergeResponse>('/trpg/converge', {
      method: 'POST',
      signal,
      body: JSON.stringify({ choice }),
    }),
}
