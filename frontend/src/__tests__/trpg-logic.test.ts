import { describe, expect, it } from 'vitest'
import type { HistoryEntry } from '../types/game'
import type { ActResponse, RollResult, TrpgOption } from '../types/trpg'
import {
  appendActResult,
  appendConvergeResult,
  appendMilestoneResult,
  buildActFromFreeText,
  buildActFromOption,
  detectPhaseSwitch,
  feedFromHistory,
  optionConvergence,
  optionMilestoneId,
  resolvePhaseRoute,
  rollSummary,
  tierClass,
  tierLabel,
  tierMessage,
  TRPG_HISTORY_TYPE,
} from '../components/trpg/trpgLogic'

function roll(overrides: Partial<RollResult> = {}): RollResult {
  return {
    roll: 37,
    target: 55,
    tier: 'success',
    dc: 0,
    attr_name: '胆略',
    skill_name: null,
    ...overrides,
  }
}

function historyEntry(overrides: Partial<HistoryEntry> = {}): HistoryEntry {
  return {
    year: 1356,
    month: 3,
    decree_type: TRPG_HISTORY_TYPE,
    decree_desc: '趁夜色翻墙出营',
    delta: {},
    narrative: '',
    ...overrides,
  }
}

function option(overrides: Partial<TrpgOption> = {}): TrpgOption {
  return {
    option_id: 'opt-1',
    label: '整肃军纪',
    description: '立即着手整饬军纪，安抚民心',
    ...overrides,
  }
}

describe('tierClass（检定分级 → CSS 类）', () => {
  it('maps all four tiers to their modifier classes', () => {
    expect(tierClass('critical_success')).toBe('is-critical-success')
    expect(tierClass('success')).toBe('is-success')
    expect(tierClass('failure')).toBe('is-failure')
    expect(tierClass('critical_failure')).toBe('is-critical-failure')
  })
})

describe('rollSummary（检定摘要行）', () => {
  it('joins attribute and skill with a middle dot when both present', () => {
    expect(rollSummary(roll({ attr_name: '胆略', skill_name: '骑术' })))
      .toBe('胆略·骑术 · 骰面 37 / 目标 55')
  })

  it('falls back to attribute only when skill is absent', () => {
    expect(rollSummary(roll({ attr_name: '胆略', skill_name: null })))
      .toBe('胆略 · 骰面 37 / 目标 55')
  })

  it('falls back to generic label when neither attribute nor skill is present', () => {
    expect(rollSummary(roll({ attr_name: null, skill_name: null })))
      .toBe('检定 · 骰面 37 / 目标 55')
  })
})

describe('buildActFromOption / buildActFromFreeText（选项 → act 请求）', () => {
  it('combines label and description into action text', () => {
    expect(buildActFromOption(option())).toEqual({
      action_text: '整肃军纪——立即着手整饬军纪，安抚民心',
    })
  })

  it('uses label alone when description is empty', () => {
    expect(buildActFromOption(option({ description: '' }))).toEqual({
      action_text: '整肃军纪',
    })
  })

  it('returns null for blank free text and trims valid input', () => {
    expect(buildActFromFreeText('   ')).toBeNull()
    expect(buildActFromFreeText('')).toBeNull()
    expect(buildActFromFreeText('  趁夜色翻墙  ')).toEqual({
      action_text: '趁夜色翻墙',
    })
  })
})

describe('feedFromHistory（治理存档历史 → 叙事流条目）', () => {
  it('only replays trpg_act entries, preserving order', () => {
    const entries = [
      historyEntry({ decree_type: 'decree', decree_desc: '政令一条', narrative: '不应出现' }),
      historyEntry({ decree_desc: '第一行动', narrative: '第一段叙事' }),
      historyEntry({ decree_desc: '', narrative: '仅有叙事的行动' }),
    ]
    const feed = feedFromHistory(entries)

    expect(feed).toHaveLength(3)
    expect(feed[0]).toEqual({ kind: 'action', id: expect.any(String), text: '第一行动' })
    expect(feed[1]).toMatchObject({
      kind: 'narrative',
      text: '第一段叙事',
      roll: null,
      chapterTitle: '',
      source: 'history',
    })
    expect(feed[2]).toMatchObject({ kind: 'narrative', id: expect.any(String), text: '仅有叙事的行动' })
    expect(feed.filter((f) => f.kind === 'narrative')).toHaveLength(2)
  })

  it('returns an empty feed when there is no trpg history', () => {
    expect(feedFromHistory([historyEntry({ decree_type: 'decree' })])).toEqual([])
    expect(feedFromHistory([])).toEqual([])
  })
})

describe('resolvePhaseRoute（phase 路由判定）', () => {
  it('routes null state to loading', () => {
    expect(resolvePhaseRoute(null)).toBe('loading')
  })

  it('routes life_story to the TRPG page', () => {
    expect(resolvePhaseRoute({ phase: 'life_story' })).toBe('life_story')
  })

  it('routes governance (and any non-life_story phase) to governance', () => {
    expect(resolvePhaseRoute({ phase: 'governance' })).toBe('governance')
  })
})

describe('detectPhaseSwitch（act 响应是否触发 phase 切换）', () => {
  it('returns false when the response stays in life_story', () => {
    expect(detectPhaseSwitch('life_story', { phase: 'life_story' })).toBe(false)
  })

  it('returns true when the response moves to governance', () => {
    expect(detectPhaseSwitch('life_story', { phase: 'governance' })).toBe(true)
  })
})

describe('optionConvergence / optionMilestoneId（选项路由判定）', () => {
  it('recognizes convergence accept/refuse markers', () => {
    expect(optionConvergence(option({ convergence: 'accept' }))).toBe('accept')
    expect(optionConvergence(option({ convergence: 'refuse' }))).toBe('refuse')
    expect(optionConvergence(option())).toBeNull()
    expect(optionConvergence(option({ convergence: undefined }))).toBeNull()
  })

  it('extracts non-empty milestone_id only', () => {
    expect(optionMilestoneId(option({ milestone_id: 'famine-1344' }))).toBe('famine-1344')
    expect(optionMilestoneId(option({ milestone_id: '  ' }))).toBeNull()
    expect(optionMilestoneId(option())).toBeNull()
    expect(optionMilestoneId(option({ milestone_id: null }))).toBeNull()
  })
})

describe('appendMilestoneResult / appendConvergeResult（关键事件/收束 → 叙事流）', () => {
  it('appends action card + narrative card without roll for milestone completion', () => {
    const feed = appendMilestoneResult([], '完成关键事件：灾疫丧亲', {
      narrative: '岁月流转，新篇开启。',
      chapter_title: '僧旅飘零',
    })
    expect(feed).toHaveLength(2)
    expect(feed[0]).toEqual({ kind: 'action', id: expect.any(String), text: '完成关键事件：灾疫丧亲' })
    expect(feed[1]).toMatchObject({
      kind: 'narrative',
      text: '岁月流转，新篇开启。',
      roll: null,
      chapterTitle: '僧旅飘零',
      source: 'milestone',
    })
  })

  it('appends narrative-only card for convergence choice', () => {
    const feed = appendConvergeResult([], {
      narrative: '【收束·身死】霸业未成。',
      chapter_title: '割据江东',
    })
    expect(feed).toHaveLength(1)
    expect(feed[0]).toMatchObject({
      kind: 'narrative',
      text: '【收束·身死】霸业未成。',
      roll: null,
      source: 'converge',
    })
  })
})

describe('appendActResult（act 响应 → 追加行动卡与叙事卡）', () => {
  it('appends an action card then a narrative card with roll details', () => {
    const res: ActResponse = {
      roll: roll(),
      narrative: '**夜袭得手**，粮仓火光映红了半边天。',
      options: [],
      state_changes: {},
      source: 'ai',
      phase: 'life_story',
      chapter: 'yingtian',
      chapter_title: '集庆之变',
      chapter_turns: 1,
      pacing: { turns_taken: 1, min_turns: 1, max_turns: 3, may_advance: true, must_advance: false },
      frozen: false,
      growth: null,
      convergence_hook: null,
      time: { year: 1356, month: 3, era_name: '至正', era_year: 16 },
    }

    const feed = appendActResult([], '整肃军纪', res)

    expect(feed).toHaveLength(2)
    expect(feed[0]).toEqual({ kind: 'action', id: expect.any(String), text: '整肃军纪' })
    expect(feed[1]).toMatchObject({
      kind: 'narrative',
      text: res.narrative,
      roll: roll(),
      chapterTitle: '集庆之变',
      source: 'ai',
    })
  })
})

describe('tier 文案与分级标签', () => {
  it('provides a dramatic message and label per tier', () => {
    expect(tierLabel('critical_success')).toBe('大成功')
    expect(tierLabel('critical_failure')).toBe('大失败')
    expect(tierMessage('critical_success')).toContain('天命')
    expect(tierMessage('critical_failure')).toContain('祸从天降')
  })
})
