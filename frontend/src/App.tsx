import { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { api, getToken, Notification, setToken, User } from './api'
import { fmtDateTime, ROLE_LABELS, useApi } from './lib'
import { Analytics } from './pages/Analytics'
import { Admin } from './pages/Admin'
import { Assistant } from './pages/Assistant'
import { Centralization } from './pages/Centralization'
import { DashboardPage } from './pages/Dashboard'
import { Knowledge } from './pages/Knowledge'
import { Login } from './pages/Login'
import { Norms } from './pages/Norms'
import { OrganizationPage } from './pages/Organization'
import { Organizations } from './pages/Organizations'
import { ProgramPage } from './pages/Program'
import { ProjectPage, Projects } from './pages/Projects'
import { Requests } from './pages/Requests'
import { Workflow } from './pages/Workflow'

const UserContext = createContext<User | null>(null)

export function useUser(): User {
  const user = useContext(UserContext)
  if (!user) throw new Error('useUser вызван вне авторизованной части приложения')
  return user
}

const NAV: { to: string; label: string; adminOnly?: boolean }[] = [
  { to: '/', label: 'Обзор' },
  { to: '/program', label: 'Паспорт проекта' },
  { to: '/organizations', label: 'Учреждения' },
  { to: '/analytics', label: 'Отклонения' },
  { to: '/centralization', label: 'Централизация' },
  { to: '/projects', label: 'Проекты' },
  { to: '/workflow', label: 'Задачи' },
  { to: '/requests', label: 'Обращения' },
  { to: '/norms', label: 'Нормативы' },
  { to: '/knowledge', label: 'База знаний' },
  { to: '/assistant', label: 'Помощник' },
  { to: '/admin', label: 'Администрирование', adminOnly: true },
]

function Notifications() {
  const state = useApi<Notification[]>('/notifications')
  const [open, setOpen] = useState(false)
  const unread = state.data?.filter((n) => !n.read_at).length ?? 0

  async function toggle() {
    setOpen(!open)
    if (!open && unread) {
      await api('/notifications/read', { method: 'POST' })
      // Список не перезагружаем сразу, чтобы непрочитанные остались выделены, пока панель открыта
    } else if (open) {
      void state.reload()
    }
  }

  return (
    <div className="notifications">
      <button className="ghost" onClick={toggle} aria-label="Уведомления">
        Уведомления{unread > 0 && <span className="counter">{unread}</span>}
      </button>
      {open && (
        <div className="popover">
          {state.data?.length ? (
            state.data.map((n) => (
              <div key={n.id} className={n.read_at ? 'note' : 'note unread'}>
                <div>{n.text}</div>
                <span className="muted">{fmtDateTime(n.created_at)}</span>
              </div>
            ))
          ) : (
            <div className="muted pad">Уведомлений нет</div>
          )}
        </div>
      )}
    </div>
  )
}

function Layout({ user, onLogout }: { user: User; onLogout: () => void }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          Кадровый потенциал ОУ
          <small>Штатные расписания</small>
        </div>
        <nav>
          {NAV.filter((item) => !item.adminOnly || user.role === 'admin').map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="content">
        <div className="topbar">
          <Notifications />
          <div className="whoami">
            <strong>{user.full_name}</strong>
            <span className="muted">{ROLE_LABELS[user.role]}</span>
          </div>
          <button className="ghost" onClick={onLogout}>
            Выйти
          </button>
        </div>
        <main>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/organizations" element={<Organizations />} />
            <Route path="/organizations/:id" element={<OrganizationPage />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/centralization" element={<Centralization />} />
            <Route path="/program" element={<ProgramPage />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:id" element={<ProjectPage />} />
            <Route path="/workflow" element={<Workflow />} />
            <Route path="/requests" element={<Requests />} />
            <Route path="/norms" element={<Norms />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/assistant" element={<Assistant />} />
            {user.role === 'admin' && <Route path="/admin" element={<Admin />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(Boolean(getToken()))

  useEffect(() => {
    if (!getToken()) return
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setChecking(false))
  }, [])

  if (checking) return null
  if (!user) return <Login onLogin={setUser} />

  function logout() {
    setToken(null)
    setUser(null)
  }

  return (
    <UserContext.Provider value={user}>
      <Layout user={user} onLogout={logout} />
    </UserContext.Provider>
  )
}
