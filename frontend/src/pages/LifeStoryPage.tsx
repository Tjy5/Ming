/**
 * 跑团叙事页（phase=life_story）：角色卡面板 + AI 叙事流 + D100 检定展示
 * + 分支选项/自由行动。每次 act 响应后同步 phase/chapter；检测到 phase
 * 切换（→ governance）时同步全局状态并跳转治理界面（切换触发归阶段D，
 * 此处仅按后端 state.phase 响应）。
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
  RollResult,
  TrpgOption,
} from '../types/trpg'
import CharacterPanel from '../components/trpg/CharacterPanel'
import NarrativeFeed from '../components/trpg/NarrativeFeed'
import DiceRollView from '../components/trpg/DiceRollView'
import OptionList from '../components/trpg/OptionList'
import {
  appendActResult,
  buildActFromFreeText,
  buildActFromOption,
  detectPhaseSwitch,
  feedFromHistory,
  type FeedItem,
} from '../components/trpg/trpgLogic'
import './LifeStoryPage.css'

interface TransitionInfo {
  narrative: string
  latest: GameState
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
  const [error, setError] = useState<string | null>(null)
  const [freeText, setFreeText] = useState('')
  const [transition, setTransition] = useState<TransitionInfo | null>(null)
  const transitioned = useRef(false)

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

  const handleFreeSubmit = (e: FormEvent) => {
    e.preventDefault()
    const payload = buildActFromFreeText(freeText)
    if (!payload) return
    setFreeText('')
    void performAct(payload)
  }

  const busy = acting || !!transition

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
          <OptionList
            options={options}
            disabled={busy}
            onSelect={(option) => void performAct(buildActFromOption(option))}
          />
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
    </div>
  )
}
