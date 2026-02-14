import type { GameTime } from '../types/game'

const STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
const BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
const MONTH_CN = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
const SEASONS = ['春', '春', '春', '夏', '夏', '夏', '秋', '秋', '秋', '冬', '冬', '冬']

function ganZhi(year: number): string {
  return `${STEMS[(year - 4) % 10]}${BRANCHES[(year - 4) % 12]}年`
}

export default function HistoricalCalendar({ year, month, era_name, era_year }: GameTime) {
  const eraDisplay = era_year === 1 ? '元年' : `${era_year}年`
  const m = month >= 1 && month <= 12 ? month : 1
  return (
    <div className="historical-calendar">
      <div className="hc-main">{era_name}{eraDisplay}</div>
      <div className="hc-sub">
        <span>{ganZhi(year)}</span>
        <span>{SEASONS[m - 1]} · {MONTH_CN[m - 1]}月</span>
      </div>
    </div>
  )
}
