import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api, getToken, Notification, RequestStats, setToken, User } from './api'
import { Icon, IconName } from './components/icons'
import { Avatar } from './components/ui'
import { fmtDateTime, ROLE_LABELS, useApi } from './lib'
import { Admin } from './pages/Admin'
import { Login } from './pages/Login'
import { Requests } from './pages/Requests'

const UserContext = createContext<User | null>(null)

export function useUser(): User {
  const user = useContext(UserContext)
  if (!user) throw new Error('useUser вызван вне авторизованной части приложения')
  return user
}

interface NavItem {
  to: string
  label: string
  icon: IconName
  // Кому пункт показывать; без списка — всем
  roles?: User['role'][]
}

const NAV: NavItem[] = [
  { to: '/requests', label: 'Заявки', icon: 'inbox' },
  { to: '/admin', label: 'Администрирование', icon: 'shield', roles: ['admin'] },
]

const THEME_KEY = 'hr-edu-theme'

function useTheme() {
  const [theme, setTheme] = useState(
    () =>
      localStorage.getItem(THEME_KEY) ??
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
  )
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])
  return [theme, () => setTheme(theme === 'dark' ? 'light' : 'dark')] as const
}

function Notifications() {
  const state = useApi<Notification[]>('/notifications')
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const unread = state.data?.filter((n) => !n.read_at).length ?? 0

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) {
        setOpen(false)
        void state.reload()
      }
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open, state])

  async function toggle() {
    setOpen(!open)
    if (!open && unread) {
      await api('/notifications/read', { method: 'POST' })
      // Список не перезагружаем сразу, чтобы непрочитанные остались выделены, пока панель открыта
    } else if (open) {
      void state.reload()
    }
  }

  function follow(note: Notification) {
    setOpen(false)
    if (note.request_id) navigate(`/requests?open=${note.request_id}`)
  }

  return (
    <div className="notifications" ref={box}>
      <button className="ghost icon" onClick={toggle} aria-label="Уведомления" title="Уведомления">
        <Icon name="bell" />
        {unread > 0 && <span className="counter">{unread}</span>}
      </button>
      {open && (
        <div className="popover">
          {state.data?.length ? (
            state.data.map((n) => (
              <div
                key={n.id}
                className={`note ${n.read_at ? '' : 'unread'} ${n.request_id ? 'clickable' : ''}`}
                onClick={() => follow(n)}
              >
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
  const [theme, toggleTheme] = useTheme()
  const location = useLocation()
  // На узком экране меню выезжает поверх страницы и закрывается после перехода
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => setMenuOpen(false), [location.pathname])
  // Счётчики заявок в меню — чтобы о них не нужно было вспоминать
  const requests = useApi<RequestStats>('/requests/stats')
  const reloadRequests = requests.reload
  useEffect(() => {
    const reload = () => void reloadRequests()
    const timer = setInterval(reload, 60_000)
    window.addEventListener('requests-changed', reload)
    return () => {
      clearInterval(timer)
      window.removeEventListener('requests-changed', reload)
    }
  }, [reloadRequests])
  const items = NAV.filter((item) => !item.roles || item.roles.includes(user.role))
  const waiting = (requests.data?.my_turn ?? 0) + (requests.data?.overdue ?? 0)

  return (
    <div className={`layout ${menuOpen ? 'menu-open' : ''}`}>
      <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />
      <aside className="sidebar" aria-label="Меню">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="inbox" />
          </span>
          <div>
            Заявки
            <small>образовательных учреждений</small>
          </div>
          <button
            className="ghost icon menu-close"
            onClick={() => setMenuOpen(false)}
            aria-label="Закрыть меню"
          >
            <Icon name="x" />
          </button>
        </div>
        <nav>
          {items.map((item) => (
            <NavLink key={item.to} to={item.to}>
              <Icon name={item.icon} />
              {item.label}
              {item.to === '/requests' && requests.data && (
                <span className="nav-counts">
                  {requests.data.my_turn > 0 && (
                    <span className="nav-count mine" title="Ждут ваших действий">
                      {requests.data.my_turn}
                    </span>
                  )}
                  {requests.data.overdue > 0 && (
                    <span className="nav-count" title="Просрочено">
                      {requests.data.overdue}
                    </span>
                  )}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Avatar name={user.full_name} />
          <div className="whoami">
            <strong>{user.full_name}</strong>
            <span className="muted">{ROLE_LABELS[user.role]}</span>
          </div>
          <button className="ghost icon" onClick={onLogout} aria-label="Выйти" title="Выйти">
            <Icon name="logout" />
          </button>
        </div>
      </aside>
      <div className="content">
        <div className="topbar">
          <button
            className="ghost icon menu-toggle"
            onClick={() => setMenuOpen(true)}
            aria-label="Открыть меню"
            aria-expanded={menuOpen}
          >
            <Icon name="menu" />
            {waiting > 0 && <span className="menu-dot" />}
          </button>
          <span className="topbar-title">
            {items.find((item) => location.pathname.startsWith(item.to))?.label ?? 'Заявки'}
          </span>
          <span className="spacer" />
          <button
            className="ghost icon"
            onClick={toggleTheme}
            aria-label="Сменить тему"
            title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
          </button>
          <Notifications />
        </div>
        {/* key перезапускает анимацию появления при переходе между разделами */}
        <main key={location.pathname.split('/')[1]}>
          <Routes>
            <Route path="/requests" element={<Requests />} />
            {user.role === 'admin' && <Route path="/admin" element={<Admin />} />}
            <Route path="*" element={<Navigate to="/requests" replace />} />
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
