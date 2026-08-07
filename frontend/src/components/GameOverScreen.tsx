import type { GameState } from '../types/game'

interface Props {
  result: 'victory' | 'defeat'
  message: string
  state: GameState
  onNewGame: () => void
}

export default function GameOverScreen({ result, message, state, onNewGame }: Props) {
  const eraYear = state.time.era_year === 1 ? '元年' : `${state.time.era_year}年`
  return (
    <div className="game-over-overlay">
      <div className={`game-over-box ${result}`}>
        <h2>{result === 'victory' ? '王业垂成' : '基业倾覆'}</h2>
        <p>{message}</p>
        <p>历时：{state.time.era_name}{eraYear}{state.time.month}月</p>
        <p>最终威望：{state.court_prestige} | 钱粮：{state.national_treasury}</p>
        <p>推进回合：{state.decree_count} 月</p>
        <button onClick={onNewGame}>重整旗鼓</button>
      </div>
    </div>
  )
}
