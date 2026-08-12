import { useEffect, useRef, useState } from 'react'
import { markGuideSeen, setGuidePreference } from './guideModalLogic'

// 08-07-frontend-ui-polish：界面指引手册（新手引导）
const GUIDE_SECTIONS: { title: string; body: string }[] = [
  {
    title: '顶部数据栏',
    body: '国库、内帑、粮草、人口、兵力、民心、军心、威望。点击任一项，或聚焦后按 Enter/Space，可查看其含义与构成。',
  },
  {
    title: '天下地图',
    body: '点击或聚焦任一省份，可查看驻军、控制与税率详情，并将该省带入自由行动。右侧可切换显示维度（标准/灾害/民心/动乱/税率/赋税）。',
  },
  {
    title: '大臣面板',
    body: '查阅朝臣生平、事功与忠诚。可与之对话，或下旨调动、赏罚。被处决或罢免者不再出现于朝堂与叙事。',
  },
  {
    title: '下诏施政',
    body: '于下诏面板选择政令类别并下达。政令经官僚传达会有执行损耗（腐败越高到手越少）；在办任务会持续推进，无需反复催办。',
  },
  {
    title: 'AI 设置',
    body: '配置模型与密钥后，可用“测试连接”一键验证端到端可用；报错会给出可读原因（密钥/额度/网络/模型名等）。',
  },
]

interface Props {
  open: boolean
  onClose: () => void
}

function GuideModalContent({ onClose }: Pick<Props, 'onClose'>) {
  const [page, setPage] = useState(0)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const section = GUIDE_SECTIONS[page]
  const isLast = page === GUIDE_SECTIONS.length - 1

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const panel = panelRef.current
    const focusable = () => panel ? Array.from(panel.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')) : []
    focusable()[0]?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      returnFocusRef.current?.focus()
    }
  }, [onClose])

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="guide-modal">
      <div ref={panelRef} className="modal-panel guide-panel" role="dialog" aria-modal="true" aria-labelledby="guide-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="guide-title" className="modal-title">界面指引</h2>
        <div className="guide-section">
          <h3>{section.title}</h3>
          <p>{section.body}</p>
        </div>
        <div className="guide-nav">
          <button className="modal-btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            上一步
          </button>
          <span className="guide-progress">{page + 1} / {GUIDE_SECTIONS.length}</span>
          {isLast ? (
            <button className="modal-btn primary" onClick={() => { setGuidePreference('completed'); onClose() }}>完成并开始</button>
          ) : (
            <button className="modal-btn primary" onClick={() => { markGuideSeen(); setPage((p) => p + 1) }}>下一步</button>
          )}
        </div>
        <div className="guide-preferences">
          <button className="guide-skip" onClick={() => { setGuidePreference('skipped'); onClose() }}>跳过本次</button>
          <button className="guide-never" onClick={() => { setGuidePreference('never'); onClose() }}>以后不再显示</button>
        </div>
      </div>
    </div>
  )
}

export default function GuideModal({ open, onClose }: Props) {
  if (!open) return null
  return <GuideModalContent onClose={onClose} />
}
