import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Minister, GameState, DialogueMessage } from '../types/game'
import { api } from '../api/client'
import { getPortraitUrl } from '../utils/portraits'

interface Props {
  minister: Minister | null
  onClose: () => void
  onStateUpdate: (state: GameState) => void
}

export default function MinisterDialogue({ minister, onClose, onStateUpdate }: Props) {
  const [messages, setMessages] = useState<DialogueMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [loyaltyChange, setLoyaltyChange] = useState<number | null>(null)
  const [portraitError, setPortraitError] = useState(false)
  const [isComposing, setIsComposing] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const loyaltyTimerRef = useRef<number>(0)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEsc)
    return () => {
      window.removeEventListener('keydown', handleEsc)
      window.clearTimeout(loyaltyTimerRef.current)
    }
  }, [onClose])

  if (!minister) return null

  async function handleSend() {
    if (!input.trim() || loading || !minister || isComposing) return

    const userMsg: DialogueMessage = { role: 'user', content: input.trim(), timestamp: Date.now() }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.ministerDialogue(minister.name, userMsg.content, conversationId)
      const reply: DialogueMessage = { role: 'minister', content: res.reply, timestamp: Date.now() }
      setMessages(prev => [...prev, reply])
      setConversationId(res.conversation_id)
      onStateUpdate(res.state)

      if (res.loyalty_change !== 0) {
        window.clearTimeout(loyaltyTimerRef.current)
        setLoyaltyChange(res.loyalty_change)
        loyaltyTimerRef.current = window.setTimeout(() => setLoyaltyChange(null), 3000)
      }
    } catch (e) {
      console.error(e)
      setMessages(prev => [...prev, { role: 'minister', content: '（大臣似乎不愿多言……）' }])
    } finally {
      setLoading(false)
    }
  }

  const loyaltyColor = minister.loyalty > 60 ? 'var(--green)' : minister.loyalty > 30 ? 'var(--yellow)' : 'var(--red)'

  return (
    <div className="modal-overlay" onClick={onClose}>
      <motion.div
        className="minister-dialogue-modal"
        onClick={e => e.stopPropagation()}
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialogue-minister-name"
      >
        <div className="md-content">
          <div className="md-left">
            {portraitError ? (
              <div className="md-portrait md-portrait-fallback" style={{ backgroundColor: '#555' }}>
                {minister.name.charAt(0)}
              </div>
            ) : (
              <img
                className="md-portrait"
                src={getPortraitUrl(minister.name)}
                alt={minister.name}
                onError={() => setPortraitError(true)}
              />
            )}
            <div className="md-minister-name" id="dialogue-minister-name">{minister.name}</div>
            <div className="md-minister-pos">{minister.positions?.join('、') || '大臣'}</div>
            <div className="md-minister-faction">{minister.faction}</div>
            {minister.historical_note && <div className="md-historical-note">{minister.historical_note}</div>}

            <div className="md-loyalty-section">
              <div className="md-loyalty-label">
                <span>忠诚度</span>
                <span>{minister.loyalty}</span>
              </div>
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{
                    width: `${minister.loyalty}%`,
                    backgroundColor: loyaltyColor
                  }}
                />
              </div>
            </div>

            <AnimatePresence>
              {loyaltyChange !== null && (
                <motion.div
                  className={`md-loyalty-notification ${loyaltyChange > 0 ? 'pos' : 'neg'}`}
                  initial={{ y: 20, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  exit={{ y: -20, opacity: 0 }}
                >
                  忠诚 {loyaltyChange > 0 ? `+${loyaltyChange}` : loyaltyChange}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="md-right">
            <div className="md-messages" ref={scrollRef}>
              {messages.length === 0 && (
                <div className="md-empty-hint">与 {minister.name} 开启对话...</div>
              )}
              {messages.map((m, i) => (
                <div key={m.timestamp ?? i} className={m.role === 'user' ? 'md-message-user' : 'md-message-minister'}>
                  <div className="md-bubble">{m.content}</div>
                </div>
              ))}
              {loading && (
                <div className="md-message-minister">
                  <div className="md-bubble">...</div>
                </div>
              )}
            </div>
            <div className="md-input-area">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !isComposing) handleSend()
                }}
                onCompositionStart={() => setIsComposing(true)}
                onCompositionEnd={() => setIsComposing(false)}
                placeholder="输入奏对内容..."
                maxLength={500}
                autoFocus
              />
              <button onClick={handleSend} disabled={loading || !input.trim()}>发送</button>
            </div>
          </div>
        </div>
        <button className="md-close-btn" onClick={onClose} aria-label="关闭对话">×</button>
      </motion.div>
    </div>
  )
}

