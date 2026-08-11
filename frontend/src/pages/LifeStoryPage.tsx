/**
 * 跑团叙事页（phase=life_story）：角色卡面板 + AI 叙事流 + D100 检定展示
 * + 分支选项/自由行动。每次 act 响应后同步 phase/chapter；检测到 phase
 * 切换（→ governance）时同步全局状态并跳转治理界面（切换触发归阶段D，
 * 此处仅按后端 state.phase 响应）。
 * 阶段D 扩展：选项路由——收束抉择（convergence 标记 → /converge）、
 * 里程碑联动（milestone_id → milestones/{id}/complete）；convergence_hook
 * 非空时渲染收束横幅；拒绝归附会进入仍可继续行动的流亡困局。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import { trpgApi } from '../api/trpg'
import { useStore } from '../hooks/store'
import type { GameState, GameTime } from '../types/game'
import type {
  ActPayload,
  ApiCharacterSheet,
  ApiGrowthEntry,
  ConvergeChoice,
  ConvergenceHook,
  NarrativeRegenerationRequest,
  RollResult,
  TrpgOption,
} from '../types/trpg'
import CharacterPanel from '../components/trpg/CharacterPanel'
import NarrativeFeed from '../components/trpg/NarrativeFeed'
import DiceRollView from '../components/trpg/DiceRollView'
import OptionList from '../components/trpg/OptionList'
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
  type FeedItem,
} from '../components/trpg/trpgLogic'
import './LifeStoryPage.css'

interface TransitionInfo {
  narrative: string
  latest: GameState
}

interface NarrativeFallbackInfo {
  settlementId: string
  pathId: NarrativeRegenerationRequest['path_id']
}

function formatTime(time: GameTime | null): string {
  if (!time) return ''
  const era = time.era_year === 1 ? `${time.era_name}元年` : `${time.era_name}${time.era_year}年`
  return `${era}${time.month}月`
}

export default function LifeStoryPage() {
  const state = useStore((s) => s.state)
  const setState = useStore((s) => s.setState)

  const [sheet, setSheet] = useState<ApiCharacterSheet | null>(null)
  const [chapterTitle, setChapterTitle] = useState('')
  const [chapterTurns, setChapterTurns] = useState(state?.chapter_turns ?? 0)
  const [time, setTime] = useState<GameTime | null>(state?.time ?? null)
  const [feed, setFeed] = useState<FeedItem[]>([])
  const feedSeeded = useRef(false)
  const [options, setOptions] = useState<TrpgOption[]>([])
  const [lastRoll, setLastRoll] = useState<RollResult | null>(null)
  const [latestGrowth, setLatestGrowth] = useState<ApiGrowthEntry | null>(null)
  const [acting, setActing] = useState(false)
  const [regeneratingNarrative, setRegeneratingNarrative] = useState(false)
  const [narrativeFallback, setNarrativeFallback] = useState<NarrativeFallbackInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [freeText, setFreeText] = useState('')
  const [transition, setTransition] = useState<TransitionInfo | null>(null)
  const transitioned = useRef(false)
  const [convergenceHook, setConvergenceHook] = useState<ConvergenceHook | null>(null)
  const [ending, setEnding] = useState<{ message: string } | null>(null)

  // 播种：从存档历史回放此前的跑团叙事
  useEffect(() => {
    if (feedSeeded.current || !state) return
    feedSeeded.current = true
    setFeed(feedFromHistory(state.history_log))
  }, [state])

  // 拉取角色卡与篇章信息
  useEffect(() => {
    let cancelled = false
    trpgApi.getCharacter()
      .then((res) => {
        if (cancelled) return
        setSheet(res.player)
        setChapterTitle(res.chapter_title)
        const lastGrowth = res.growth_log.length
          ? res.growth_log[res.growth_log.length - 1]
          : null
        setLatestGrowth(lastGrowth)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.body.message : '角色卡读取失败')
      })
    return () => { cancelled = true }
  }, [])

  // phase 切换过渡：短暂展示收束叙事，随后进入治理界面
  useEffect(() => {
    if (!transition || transitioned.current) return
    const timer = window.setTimeout(() => {
      transitioned.current = true
      setState(transition.latest)
    }, 6000)
    return () => window.clearTimeout(timer)
  }, [transition, setState])

  const performAct = useCallback(async (payload: ActPayload) => {
    if (acting || transitioned.current) return
    setActing(true)
    setError(null)
    try {
      const res = await trpgApi.act(payload)
      setFeed((f) => appendActResult(f, payload.action_text, res))
      setLastRoll(res.roll)
      setOptions(res.options)
      setNarrativeFallback(
        res.narrative_status === 'fallback_facts' && res.settlement_id
          ? { settlementId: res.settlement_id, pathId: res.narrative_path_id }
          : null,
      )
      setConvergenceHook(res.convergence_hook)
      setChapterTitle(res.chapter_title)
      setChapterTurns(res.chapter_turns)
      setTime(res.time)
      if (res.growth) setLatestGrowth(res.growth)
      // 同步角色卡数值变化（成长点/属性），失败不阻断主流程
      trpgApi.getCharacter()
        .then((c) => setSheet(c.player))
        .catch((e) => console.warn('角色卡刷新失败，保留本地数据', e))

      // phase 切换检测：拉取全量状态，展示过渡剧情后跳转治理界面
      if (detectPhaseSwitch('life_story', res)) {
        const latest = await api.getState()
        setTransition({ narrative: res.narrative, latest })
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : '行动失败，请稍后重试')
    } finally {
      setActing(false)
    }
  }, [acting])

  const regenerateNarrative = useCallback(async () => {
    if (!narrativeFallback || regeneratingNarrative) return
    setRegeneratingNarrative(true)
    setError(null)
    try {
      const result = await trpgApi.regenerateNarrative(
        narrativeFallback.settlementId,
        { path_id: narrativeFallback.pathId, topic_id: 'trpg' },
      )
      setFeed((current) => {
        const next = [...current]
        for (let index = next.length - 1; index >= 0; index -= 1) {
          const item = next[index]
          if (item.kind !== 'narrative') continue
          next[index] = { ...item, text: result.text, source: 'regenerated' }
          break
        }
        return next
      })
      setNarrativeFallback(
        result.narrative_status === 'fallback_facts'
          ? narrativeFallback
          : null,
      )
    } catch (e) {
      setError(e instanceof ApiError
        ? e.body.message
        : '叙事重生成失败；已提交的结算保持不变')
    } finally {
      setRegeneratingNarrative(false)
    }
  }, [narrativeFallback, regeneratingNarrative])

  // 1360 收束抉择：接受招揽切换 governance；拒绝归附则继续当前世界线
  const performConverge = useCallback(async (choice: ConvergeChoice) => {
    if (acting || transitioned.current || ending) return
    setActing(true)
    setError(null)
    try {
      const res = await trpgApi.converge(choice)
      setFeed((f) => appendConvergeResult(f, res))
      setOptions([])
      setConvergenceHook(null)
      setChapterTitle(res.chapter_title)
      setChapterTurns(res.chapter_turns)
      setTime(res.time)
      if (res.game_over) {
        setEnding({ message: res.game_over.message })
        return
      }
      // 接受招揽 → phase 切换：拉取全量状态，展示过渡剧情后跳转治理界面
      if (detectPhaseSwitch('life_story', res)) {
        const latest = await api.getState()
        setTransition({ narrative: res.narrative, latest })
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.body.message : '收束抉择失败，请稍后重试')
    } finally {
      setActing(false)
    }
  }, [acting, ending])

  // 里程碑联动：带 milestone_id 的选项 → 完成关键事件端点（成长奖励/章推进/phase 切换）
  const performCompleteMilestone = useCallback(async (milestoneId: string, optionLabel: string) => {
    if (acting || transitioned.current || ending) return
    setActing(true)
    setError(null)
    try {
      const res = await trpgApi.completeMilestone(milestoneId)
      setFeed((f) => appendMilestoneResult(f, optionLabel, res))
      setOptions([])
      setChapterTitle(res.chapter_title)
      setChapterTurns(res.chapter_turns)
      setTime(res.time)
      if (res.growth) setLatestGrowth(res.growth)
      // 同步角色卡数值变化（成长点/属性），失败不阻断主流程
      trpgApi.getCharacter()
        .then((c) => setSheet(c.player))
        .catch((e) => console.warn('角色卡刷新失败，保留本地数据', e))
      // phase 切换检测（yingtian-founding → governance）
      if (detectPhaseSwitch('life_story', res)) {
        const latest = await api.getState()
        setTransition({ narrative: res.narrative, latest })
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // 里程碑已达成（milestone_already_resolved）：提示后静默回退，不崩溃
        setError('该事件已达成，无需重复完成')
      } else {
        setError(e instanceof ApiError ? e.body.message : '关键事件提交失败，请稍后重试')
      }
    } finally {
      setActing(false)
    }
  }, [acting, ending])

  // 选项路由：收束抉择 → /converge；里程碑联动 → complete 端点；其余 → /act
  const handleOption = useCallback((option: TrpgOption) => {
    const convergence = optionConvergence(option)
    if (convergence) {
      void performConverge(convergence)
      return
    }
    const milestoneId = optionMilestoneId(option)
    if (milestoneId) {
      void performCompleteMilestone(milestoneId, option.label)
      return
    }
    void performAct(buildActFromOption(option))
  }, [performAct, performConverge, performCompleteMilestone])

  const handleFreeSubmit = (e: FormEvent) => {
    e.preventDefault()
    const payload = buildActFromFreeText(freeText)
    if (!payload) return
    setFreeText('')
    void performAct(payload)
  }

  const busy = acting || regeneratingNarrative || !!transition || !!ending

  return (
    <div className="life-story-page">
      <header className="ls-topbar">
        <div className="ls-title">元末纪事 · 朱元璋</div>
        <div className="ls-chapter-info">
          <strong>{chapterTitle || '篇章待启'}</strong>
          {time && <span>{formatTime(time)}</span>}
          <span>本篇章回合 {chapterTurns}</span>
        </div>
      </header>

      <div className="ls-main">
        <CharacterPanel sheet={sheet} latestGrowth={latestGrowth} />
        <div className="ls-center">
          <NarrativeFeed items={feed} loading={acting} />
        </div>
      </div>

      <footer className="ls-bottom">
        <DiceRollView roll={lastRoll} />
        <div className="ls-action-area">
          {convergenceHook && (
            <div className="ls-convergence-banner">
              <h3>大势已定 · 收束抉择</h3>
              <p>{convergenceHook.message}</p>
            </div>
          )}
          <OptionList
            options={options}
            disabled={busy}
            onSelect={handleOption}
          />
          {narrativeFallback && (
            <div className="ls-narrative-fallback" role="status">
              <div>
                <strong>结算已提交，当前显示事实摘要。</strong>
                <span>重生成只更新叙事，不会重复行动或改判结果。</span>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void regenerateNarrative()}
              >
                {regeneratingNarrative ? '正在重生成…' : '仅重生成叙事'}
              </button>
            </div>
          )}
          <form className="ls-freetext" onSubmit={handleFreeSubmit}>
            <input
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && handleFreeSubmit(e)}
              placeholder="自由行动：写下你想做的事（如：趁夜色翻墙，去镇上讨口饭吃）"
              maxLength={500}
              disabled={busy}
            />
            <button type="submit" disabled={busy || !freeText.trim()}>行动</button>
          </form>
          {error && <div className="ls-error">{error}</div>}
        </div>
      </footer>

      {transition && (
        <div className="ls-transition-overlay">
          <div className="ls-transition-card">
            <h2>时局已变 · 新的篇章</h2>
            <p className="ls-transition-narrative">{transition.narrative}</p>
            <button
              type="button"
              className="ls-transition-btn"
              onClick={() => {
                if (transitioned.current) return
                transitioned.current = true
                setState(transition.latest)
              }}
            >
              进入治理模拟
            </button>
          </div>
        </div>
      )}

      {ending && (
        <div className="ls-ending-overlay">
          <div className="ls-ending-card">
            <h2>此局已终</h2>
            <p className="ls-ending-narrative">{ending.message}</p>
            <p className="ls-ending-note">刷新页面可重作抉择。</p>
          </div>
        </div>
      )}
    </div>
  )
}
