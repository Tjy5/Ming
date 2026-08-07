import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type ChatStreamEvent } from '../api/client'
import { DECREE_LABELS, PRECONDITION_MESSAGES } from '../types/game'
import { DECREE_CATEGORY_MAP } from '../constants/decreeCategories'
import { checkPrecondition } from '../hooks/store'
import type {
  ChatGameOver,
  ChatMessage,
  DecreeType,
  GameState,
  MinisterReaction,
} from '../types/game'
import './ChatPage.css'

type ResourceDef = { key: keyof GameState; label: string; max: number; unit: string }

const RESOURCES: ResourceDef[] = [
  { key: 'national_treasury', label: '国库', unit: '万两', max: 1000 },
  { key: 'imperial_treasury', label: '内帑', unit: '万两', max: 500 },
  { key: 'grain', label: '粮草', unit: '万石', max: 5000 },
  { key: 'population', label: '人口', unit: '万人', max: 20000 },
  { key: 'military_strength', label: '兵力', unit: '万人', max: 500 },
  { key: 'civil_morale', label: '民心', unit: '%', max: 100 },
  { key: 'military_morale', label: '军心', unit: '%', max: 100 },
  { key: 'court_prestige', label: '威望', unit: '%', max: 100 },
]

const RESOURCE_LABELS: Record<string, string> = RESOURCES.reduce(
  (acc, item) => ({ ...acc, [item.key]: item.label }),
  {},
)

const QUICK_DECREE_TYPES: DecreeType[] = [
  'tax_increase',
  'tax_decrease',
  'recruit_troops',
  'disband_troops',
  'disaster_relief',
  'harsh_punishment',
  'personnel',
  'diplomacy',
]
const EXPLORE_PREFIX = '详细介绍当前局势：'
const OPENING_BRIEFING_MESSAGE = '请为我简述当前军政局势'

function buildId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function formatDelta(value: number): string {
  return value > 0 ? `+${value}` : `${value}`
}

function barColor(val: number, max: number): string {
  const pct = max > 0 ? val / max : 0
  if (pct > 0.6) return 'var(--green)'
  if (pct > 0.3) return 'var(--yellow)'
  return 'var(--red)'
}

function percent(value: number, max: number): number {
  if (max <= 0) return 0
  return Math.max(0, Math.min(100, (value / max) * 100))
}

function normalizeEffectLabel(rawKey: string): string {
  const key = rawKey.startsWith('global.') ? rawKey.slice(7) : rawKey
  return RESOURCE_LABELS[key] ?? rawKey
}

function normalizeReactionType(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (normalized.includes('support') || value.includes('支持')) return '支持'
  if (normalized.includes('oppose') || value.includes('反对')) return '反对'
  if (normalized.includes('neutral') || value.includes('中立')) return '中立'
  return value || '回应'
}

export default function ChatPage() {
  const navigate = useNavigate()
  const [gameState, setGameState] = useState<GameState | null>(null)
  const [prevState, setPrevState] = useState<GameState | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [gameOver, setGameOver] = useState<ChatGameOver | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const activeAssistantIdRef = useRef<string | null>(null)
  const gameStateRef = useRef<GameState | null>(null)
  const briefingSent = useRef(false)

  useEffect(() => {
    gameStateRef.current = gameState
  }, [gameState])

  useEffect(() => {
    let cancelled = false
    api.getState()
      .then((state) => {
        if (cancelled) return
        setGameState(state)
        setGameOver(null)
      })
      .catch((err) => {
        if (cancelled) return
        const message = err instanceof ApiError ? err.body.message : '读取状态失败'
        setError(message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!listRef.current) return
    listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages])

  const stateSummary = useMemo(() => {
    if (!gameState) return null
    return {
      time: `${gameState.time.era_name}${gameState.time.era_year}年 ${gameState.time.month}月`,
      activeEvents: gameState.active_events.length,
    }
  }, [gameState])

  const pendingMemorials = useMemo(() => {
    if (!gameState?.memorials) return 0
    return gameState.memorials.filter((item) => item.status === 'pending').length
  }, [gameState])

  const missionMinisters = useMemo(() => {
    if (!gameState) return []
    return gameState.ministers.filter(
      (minister) => minister.status === 'on_mission' && !!minister.current_mission,
    )
  }, [gameState])

  const suggestions = useMemo(() => {
    if (!gameState) return []
    const out: { id: string; text: string }[] = []
    const seen = new Set<string>()
    const push = (text: string) => {
      if (seen.has(text)) return
      seen.add(text)
      out.push({ id: text, text })
    }

    for (const event of gameState.active_events) {
      if (event.urgency === '高') push(`处理${event.name}`)
    }
    if (gameState.civil_morale < 30) push('减税安民')
    if (gameState.military_strength < 50) push('增兵备战')
    if (gameState.national_treasury < 20) push('加征赋税')
    if (pendingMemorials > 0) push('批阅奏折')

    return out.slice(0, 5)
  }, [gameState, pendingMemorials])

  const applyEventToAssistant = (event: ChatStreamEvent): void => {
    const assistantId = activeAssistantIdRef.current
    if (!assistantId) return

    setMessages((prev) => prev.map((msg) => {
      if (msg.id !== assistantId) return msg
      if (event.event === 'intent') {
        return { ...msg, intent: event.data.intent }
      }
      if (event.event === 'narrative_chunk') {
        return { ...msg, content: `${msg.content}${event.data.chunk}` }
      }
      if (event.event === 'effects') {
        return {
          ...msg,
          effectsApplied: true,
          effectsSummary: event.data.summary,
          effectsDelta: event.data.delta,
        }
      }
      if (event.event === 'reactions') {
        return {
          ...msg,
          ministerReactions: event.data.minister_reactions,
        }
      }
      if (event.event === 'done') {
        const fallbackSummary = msg.effectsSummary ?? (() => {
          const entries = Object.entries(msg.effectsDelta ?? {})
          if (!entries.length) return undefined
          return entries
            .map(([key, value]) => `${key} ${formatDelta(value)}`)
            .join(' | ')
        })()
        return {
          ...msg,
          content: msg.content || event.data.reply,
          intent: msg.intent ?? event.data.intent,
          effectsApplied: event.data.effects_applied || msg.effectsApplied,
          effectsSummary: fallbackSummary,
          ministerReactions:
            (event.data.minister_reactions && event.data.minister_reactions.length > 0)
              ? event.data.minister_reactions
              : (msg.ministerReactions ?? []),
          triggeredEvents: event.data.triggered_events ?? msg.triggeredEvents,
          newMinisters: event.data.new_ministers ?? msg.newMinisters,
          gameOver: event.data.game_over ?? msg.gameOver,
        }
      }
      return msg
    }))
  }

  const handleSend = useCallback(async (raw?: string) => {
    const messageText = (raw ?? input).trim()
    if (!messageText || sending || gameOver) return

    setError(null)
    setInput('')
    setSending(true)

    const userMsg: ChatMessage = {
      id: buildId('user'),
      role: 'user',
      content: messageText,
      timestamp: Date.now(),
    }
    const assistantMsg: ChatMessage = {
      id: buildId('assistant'),
      role: 'assistant',
      content: '',
      timestamp: Date.now() + 1,
    }
    activeAssistantIdRef.current = assistantMsg.id
    setMessages((prev) => [...prev, userMsg, assistantMsg])

    if (messageText === '存档') {
      try {
        await api.save()
        const assistantId = activeAssistantIdRef.current
        if (assistantId) {
          setMessages((prev) => prev.map((msg) => (
            msg.id === assistantId
              ? { ...msg, content: '臣已奉命完成存档。' }
              : msg
          )))
        }
      } catch (err) {
        const message = err instanceof ApiError ? err.body.message : '存档失败，请稍后重试'
        setError(message)
        const assistantId = activeAssistantIdRef.current
        if (assistantId) {
          setMessages((prev) => prev.map((msg) => (
            msg.id === assistantId
              ? { ...msg, content: `启禀主公：${message}` }
              : msg
          )))
        }
      } finally {
        activeAssistantIdRef.current = null
        setSending(false)
      }
      return
    }

    try {
      await api.chatStream(messageText, (event) => {
        if (event.event === 'state') {
          setPrevState(gameStateRef.current)
          setGameState(event.data.state)
          return
        }
        if (event.event === 'done' && event.data.game_over) {
          setGameOver(event.data.game_over)
        }
        applyEventToAssistant(event)
      })
    } catch (err) {
      const message = err instanceof ApiError ? err.body.message : '对话失败，请稍后重试'
      setError(message)
      const assistantId = activeAssistantIdRef.current
      if (assistantId) {
        setMessages((prev) => prev.map((msg) => {
          if (msg.id !== assistantId) return msg
          if (msg.content.trim()) return msg
          return {
            ...msg,
            content: `启禀主公：${message}`,
          }
        }))
      }
    } finally {
      activeAssistantIdRef.current = null
      setSending(false)
    }
  }, [gameOver, input, sending])

  useEffect(() => {
    if (briefingSent.current) return
    if (!gameState || messages.length > 0 || sending || gameOver) return
    briefingSent.current = true
    void handleSend(OPENING_BRIEFING_MESSAGE)
  }, [gameOver, gameState, handleSend, messages.length, sending])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    await handleSend()
  }

  const handleInputKeyDown = async (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    await handleSend()
  }

  const hasOnlyOpeningBriefingConversation = useMemo(() => {
    if (!messages.length) return false
    const hasOpeningPrompt = messages.some(
      (msg) => msg.role === 'user' && msg.content === OPENING_BRIEFING_MESSAGE,
    )
    if (!hasOpeningPrompt) return false
    return messages.every((msg) => (
      msg.role === 'assistant' || msg.content === OPENING_BRIEFING_MESSAGE
    ))
  }, [messages])
  const hasMessages = messages.length > 0 && !(sending && hasOnlyOpeningBriefingConversation)
  const quickActionLocked = sending || !gameState || !!gameOver

  return (
    <div className="chat-page">
      <header className="chat-topbar">
        <button className="chat-back-btn" onClick={() => navigate('/')}>返回朝堂</button>
        <div className="chat-topbar-main">
          <div className="chat-calendar">
            <strong>{stateSummary?.time ?? '加载中...'}</strong>
            <span>{stateSummary ? `${stateSummary.activeEvents}件在案` : ''}</span>
          </div>
          <div className="chat-resource-grid">
            {RESOURCES.map(({ key, label, max, unit }) => {
              const value = gameState ? Number(gameState[key]) : 0
              const prev = prevState ? Number(prevState[key]) : value
              const diff = value - prev
              return (
                <div className="chat-resource-item" key={key}>
                  <div className="chat-resource-head">
                    <span>{label}</span>
                    <strong>
                      {value}
                      <small>{unit}</small>
                    </strong>
                    {diff > 0 && <em className="trend-up">▲</em>}
                    {diff < 0 && <em className="trend-down">▼</em>}
                  </div>
                  <div className="chat-resource-track">
                    <div
                      className="chat-resource-fill"
                      style={{
                        width: `${percent(value, max)}%`,
                        backgroundColor: barColor(value, max),
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </header>

      <main className="chat-message-list" ref={listRef}>
        {!hasMessages && (
          <div className="chat-situation">
            <h2>幕府局势总览</h2>
            <div className="chat-situation-grid">
              <section className="chat-situation-card">
                <h3>活跃事件</h3>
                {gameState?.active_events.length ? (
                  <ul className="chat-event-list">
                    {gameState.active_events.map((event) => (
                      <li key={`${event.name}_${event.triggered_year}_${event.triggered_month}`}>
                        <span
                          className={`urgency-dot ${
                            event.urgency === '高' ? 'is-high' : event.urgency === '中' ? 'is-mid' : 'is-low'
                          }`}
                        />
                        <span>{event.name}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="chat-empty-note">暂无活跃事件</p>
                )}
              </section>
              <section className="chat-situation-card">
                <h3>待批奏折</h3>
                <p className="chat-big-number">{pendingMemorials}</p>
                <p className="chat-empty-note">份待批奏折</p>
              </section>
              <section className="chat-situation-card">
                <h3>在任任务</h3>
                {missionMinisters.length ? (
                  <ul className="chat-mission-list">
                    {missionMinisters.map((minister) => {
                      const mission = minister.current_mission
                      if (!mission) return null
                      return (
                        <li key={`${minister.name}_${mission.name}`}>
                          <span>{minister.name}</span>
                          <em>
                            {mission.name} {mission.progress_months}/{mission.total_months}月
                          </em>
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className="chat-empty-note">暂无在执行任务的大臣</p>
                )}
              </section>
              <section className="chat-situation-card">
                <h3>本月指标</h3>
                <div className="chat-kpi">
                  <span>国库：{gameState?.national_treasury ?? '-'}万两</span>
                  <span>民心：{gameState?.civil_morale ?? '-'}</span>
                  <span>兵力：{gameState?.military_strength ?? '-'}万人</span>
                </div>
              </section>
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`chat-row ${msg.role === 'user' ? 'is-user' : 'is-ai'}`}
          >
            <div className="chat-bubble">
              <div className="chat-text">{msg.content || (msg.role === 'assistant' ? '…' : '')}</div>
              {msg.role === 'assistant' && (() => {
                const entries = Object.entries(msg.effectsDelta ?? {}).filter(([, value]) => value !== 0)
                if (!entries.length) return null
                return (
                  <div className="chat-effects-grid">
                    {entries.map(([key, value]) => {
                      const up = value > 0
                      return (
                        <div className="chat-effect-card" key={`${msg.id}_${key}`}>
                          <span>{normalizeEffectLabel(key)}</span>
                          <strong className={up ? 'is-pos' : 'is-neg'}>
                            {formatDelta(value)} {up ? '▲' : '▼'}
                          </strong>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
              {msg.role === 'assistant' && !!msg.ministerReactions?.length && (
                <div className="chat-reaction-list">
                  {msg.ministerReactions.map((reaction: MinisterReaction) => (
                    <div
                      className="chat-reaction-item"
                      key={`${msg.id}_${reaction.faction}_${reaction.minister_name}_${reaction.reaction_type}`}
                    >
                      <span>
                        {reaction.faction}·{reaction.minister_name}：
                        {normalizeReactionType(reaction.reaction_type)}
                        （忠诚 {formatDelta(reaction.loyalty_change)}）
                      </span>
                      {reaction.reaction_text && <em>{reaction.reaction_text}</em>}
                    </div>
                  ))}
                </div>
              )}
              {msg.role === 'assistant' && ((msg.triggeredEvents?.length ?? 0) > 0 || (msg.newMinisters?.length ?? 0) > 0) && (
                <div className="chat-advance-info">
                  {!!msg.triggeredEvents?.length && (
                    <p>新事件：{msg.triggeredEvents.join('、')}</p>
                  )}
                  {!!msg.newMinisters?.length && (
                    <p>新入朝：{msg.newMinisters.join('、')}</p>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </main>

      <footer className="chat-input-area">
        {hasMessages && (
          <div className="chat-compact-hint">
            {gameState ? `${gameState.active_events.length}件事件 | ${pendingMemorials}份奏折待批` : '读取局势中…'}
          </div>
        )}
        <div className="chat-quick-actions">
          <div className="chat-fixed-actions">
            <button
              type="button"
              className="chat-action-btn is-fixed"
              disabled={quickActionLocked}
              onClick={() => { void handleSend('进入下月') }}
            >
              进入下月
            </button>
            <button
              type="button"
              className="chat-action-btn is-fixed"
              disabled={quickActionLocked}
              onClick={() => { void handleSend('存档') }}
            >
              存档
            </button>
          </div>
          <div className="chat-decree-actions">
            {QUICK_DECREE_TYPES.map((type) => {
              const preconditionOk = !!gameState && checkPrecondition(gameState, type)
              const usedThisMonth = !!gameState && !!gameState.decrees_this_month[DECREE_CATEGORY_MAP[type]]
              const disabled = quickActionLocked || !preconditionOk || usedThisMonth
              let title = DECREE_LABELS[type]
              if (usedThisMonth) title = '本月已用'
              else if (!preconditionOk) title = PRECONDITION_MESSAGES[type]
              return (
                <button
                  type="button"
                  key={type}
                  className={`chat-action-btn ${usedThisMonth ? 'is-used' : ''}`}
                  disabled={disabled}
                  title={title}
                  onClick={() => { void handleSend(DECREE_LABELS[type]) }}
                >
                  <span>{DECREE_LABELS[type]}</span>
                  {usedThisMonth && <small>本月已用</small>}
                </button>
              )
            })}
          </div>
        </div>
        {!!suggestions.length && (
          <div className="chat-suggestions">
            {suggestions.map((item) => (
              <button
                type="button"
                key={item.id}
                className="chat-suggestion-card"
                onClick={() => { void handleSend(`${EXPLORE_PREFIX}${item.text}`) }}
                disabled={quickActionLocked}
              >
                {item.text}
              </button>
            ))}
          </div>
        )}
        <form className="chat-input-form" onSubmit={handleSubmit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="请输入指令…（如：整顿军备 / 国库还有多少 / 进入下月）"
            disabled={sending || !!gameOver}
          />
          <button type="submit" disabled={sending || !input.trim() || !!gameOver}>
            {sending ? '处理中…' : '发送'}
          </button>
        </form>
        {error && <div className="chat-error">{error}</div>}
      </footer>
      {gameOver && (
        <div className="chat-gameover-overlay">
          <div className="chat-gameover-card">
            <h2>{gameOver.result === 'defeat' ? '基业倾覆' : '王业可期'}</h2>
            <p>{gameOver.message}</p>
            <div className="chat-gameover-actions">
              <button type="button" onClick={() => navigate('/')}>返回朝堂</button>
              <button type="button" onClick={() => setGameOver(null)}>继续查看记录</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
