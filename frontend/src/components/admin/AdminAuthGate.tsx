import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'

import { useAdminStore } from '../../stores/adminStore'

const STORAGE_KEY = 'admin_auth_password'

interface Props {
  children: ReactNode
}

export default function AdminAuthGate({ children }: Props) {
  const { isAuthenticated, login, error, clearError } = useAdminStore()
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [bootstrapped, setBootstrapped] = useState(false)

  useEffect(() => {
    let cancelled = false
    const restore = async () => {
      const cached = sessionStorage.getItem(STORAGE_KEY)
      if (!cached) {
        if (!cancelled) setBootstrapped(true)
        return
      }
      setSubmitting(true)
      const ok = await login(cached)
      if (ok) {
        if (!cancelled) {
          setPassword(cached)
          clearError()
        }
      } else {
        sessionStorage.removeItem(STORAGE_KEY)
      }
      if (!cancelled) {
        setSubmitting(false)
        setBootstrapped(true)
      }
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [login, clearError])

  if (!bootstrapped) {
    return <div className="admin-auth-loading">正在验证管理员会话…</div>
  }

  if (isAuthenticated) return <>{children}</>

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    const ok = await login(password)
    if (ok) {
      sessionStorage.setItem(STORAGE_KEY, password)
      clearError()
    }
    setSubmitting(false)
  }

  return (
    <div className="admin-auth-shell">
      <form className="admin-auth-card" onSubmit={onSubmit}>
        <h1>管理入口</h1>
        <p>请输入管理员密码以访问 `/admin` 页面。</p>
        <label htmlFor="admin-password">管理员密码</label>
        <input
          id="admin-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoFocus
          autoComplete="current-password"
          required
        />
        <button type="submit" disabled={submitting}>
          {submitting ? '验证中…' : '进入管理页'}
        </button>
        {error && <div className="admin-error">{error}</div>}
      </form>
    </div>
  )
}
