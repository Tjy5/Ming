/**
 * AI 叙事流卡片：玩家行动卡 + 主持人叙事卡（沿用项目 react-markdown 渲染方式）。
 */
import { useEffect, useRef } from 'react'
import Markdown from 'react-markdown'
import type { FeedItem } from './trpgLogic'
import { rollSummary, tierClass, tierLabel } from './trpgLogic'

interface Props {
  items: FeedItem[]
  loading: boolean
}

export default function NarrativeFeed({ items, loading }: Props) {
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [items.length])

  return (
    <div className="ls-feed" aria-live="polite">
      {items.length === 0 && !loading && (
        <div className="ls-feed-opening">
          <p>命运尚未落笔。写下你的第一个行动，主持人将为你展开故事。</p>
        </div>
      )}
      {items.map((item) => {
        if (item.kind === 'action') {
          return (
            <div className="ls-feed-item is-action" key={item.id}>
              <span className="ls-feed-role">你</span>
              <div className="ls-feed-text">{item.text}</div>
            </div>
          )
        }
        return (
          <div className="ls-feed-item is-narrative" key={item.id}>
            <div className="ls-feed-head">
              <span className="ls-feed-role">主持人</span>
              {item.chapterTitle && <span className="ls-feed-chapter">{item.chapterTitle}</span>}
              {item.roll && (
                <span className={`ls-feed-roll ${tierClass(item.roll.tier)}`}>
                  {tierLabel(item.roll.tier)} · {rollSummary(item.roll)}
                </span>
              )}
            </div>
            <div className="ls-feed-text ls-md-body">
              <Markdown>{item.text}</Markdown>
            </div>
          </div>
        )
      })}
      {loading && (
        <div className="ls-feed-item is-loading">
          <div className="spinner" aria-label="主持人推演中" role="status" />
          <span>主持人正在推演局势…</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  )
}
