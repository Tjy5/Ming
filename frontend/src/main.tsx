import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import GameRoot from './pages/GameRoot.tsx'

const AdminPage = lazy(() => import('./pages/AdminPage.tsx'))
const ChatPage = lazy(() => import('./pages/ChatPage.tsx'))
const ModeSelectPage = lazy(() => import('./pages/ModeSelectPage.tsx'))
const ContinuityPage = lazy(() => import('./pages/ContinuityPage.tsx'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<GameRoot forceMap />} />
        <Route path="/trpg" element={<GameRoot forceTrpg />} />
        <Route
          path="/admin"
          element={(
            <Suspense fallback={<div style={{ padding: 24 }}>Loading admin…</div>}>
              <AdminPage />
            </Suspense>
          )}
        />
        <Route
          path="/chat"
          element={(
            <Suspense fallback={<div style={{ padding: 24 }}>Loading chat…</div>}>
              <ChatPage />
            </Suspense>
          )}
        />
        <Route
          path="/mode-select"
          element={(
            <Suspense fallback={<div style={{ padding: 24 }}>Loading mode select…</div>}>
              <ModeSelectPage />
            </Suspense>
          )}
        />
        <Route
          path="/continuity"
          element={(
            <Suspense fallback={<div style={{ padding: 24 }}>Loading continuity…</div>}>
              <ContinuityPage />
            </Suspense>
          )}
        />
        <Route path="*" element={<GameRoot forceMap />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
