/**
 * 路由层 phase 分流（RC4）：全局读取后端 state.phase——
 *   life_story → LifeStoryPage（跑团叙事）
 *   governance → App（治理主页，元末化）
 * 首次进入负责拉取/创建全局状态；此后 App 与各页面共享 zustand store。
 */
import { useEffect } from 'react'
import { api, ApiError } from '../api/client'
import { useStore } from '../hooks/store'
import { resolvePhaseRoute } from '../components/trpg/trpgLogic'
import App from '../App'
import LifeStoryPage from './LifeStoryPage'

export default function GameRoot() {
  const state = useStore((s) => s.state)
  const setState = useStore((s) => s.setState)
  const setError = useStore((s) => s.setError)
  const error = useStore((s) => s.error)

  useEffect(() => {
    if (useStore.getState().state) return
    api.getState()
      .then((s) => setState(s))
      .catch(() => {
        api.newGame()
          .then((s) => setState(s))
          .catch((e) => setError(e instanceof ApiError ? e.message : '连接后端失败'))
      })
  }, [setState, setError])

  const route = resolvePhaseRoute(state)

  if (route === 'loading') {
    return (
      <div className="loading-overlay">
        <div className="spinner" />
        {error && <div className="toast">{error}</div>}
      </div>
    )
  }

  if (route === 'life_story') return <LifeStoryPage />
  return <App />
}
