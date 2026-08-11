import { useEffect, useState } from 'react'
import { markGuideSeen } from './guideModalLogic'

// 08-07-frontend-ui-polish：界面指引手册（新手引导）
const GUIDE_SECTIONS: { title: string; body: string }[] = [
  {
    title: '顶部数据栏',
    body: '国库、内帑、粮草、人口、兵力、民心、军心、威望。将鼠标悬停于任一项可查看其含义与构成。',
  },
  {
    title: '天下地图',
    body: '点击任一省份，可查看驻军、控制与税率详情，并快捷对该省下诏或调阅军队状态。右上角可切换显示维度（稳定/灾害/民心/动乱/税率）。',
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
  const section = GUIDE_SECTIONS[page]
  const isLast = page === GUIDE_SECTIONS.length - 1

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="guide-modal">
      <div className="modal-panel guide-panel" onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">界面指引</h2>
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
            <button className="modal-btn primary" onClick={onClose}>开始游戏</button>
          ) : (
            <button className="modal-btn primary" onClick={() => setPage((p) => p + 1)}>下一步</button>
          )}
        </div>
        <button className="guide-skip" onClick={onClose}>跳过</button>
      </div>
    </div>
  )
}

export default function GuideModal({ open, onClose }: Props) {
  useEffect(() => {
    if (open) markGuideSeen()
  }, [open])

  if (!open) return null
  return <GuideModalContent onClose={onClose} />
}
