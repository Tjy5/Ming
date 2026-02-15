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
        <h2>{result === 'victory' ? '大明中兴' : '社稷倾覆'}</h2>
        <p>{message}</p>
        <p>历时：{state.time.era_name}{eraYear}{state.time.month}月</p>
        <p>最终威望：{state.court_prestige} | 钱粮：{state.treasury}</p>
        <p>执行政令：{state.decree_count} 道</p>
        <button onClick={onNewGame}>再续国祚</button>
      </div>
    </div>
  )
}
