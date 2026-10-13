import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api, getToken, Notification, RequestStats, setToken, User } from './api'
import { Icon, IconName } from './components/icons'
import { Avatar } from './components/ui'
import { fmtDateTime, isServiceRole, ROLE_LABELS, useApi } from './lib'
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
import { Workload } from './pages/Workload'

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
  adminOnly?: boolean
}

const NAV: [group: string, items: NavItem[]][] = [
  [
    'Анализ',
    [
      { to: '/', label: 'Обзор', icon: 'grid' },
      { to: '/workload', label: 'Загрузка персонала', icon: 'gauge' },
      { to: '/analytics', label: 'Отклонения', icon: 'bars' },
      { to: '/centralization', label: 'Централизация', icon: 'layers' },
      { to: '/organizations', label: 'Учреждения', icon: 'building' },
    ],
  ],
  [
    'Работа',
    [
      { to: '/requests', label: 'Заявки', icon: 'inbox' },
      { to: '/projects', label: 'Проекты', icon: 'folder' },
      { to: '/workflow', label: 'Задачи', icon: 'tasks' },
      { to: '/program', label: 'Паспорт проекта', icon: 'target' },
    ],
  ],
  [
    'Справочники',
    [
      { to: '/norms', label: 'Нормативы', icon: 'sliders' },
      { to: '/knowledge', label: 'База знаний', icon: 'book' },
      { to: '/assistant', label: 'Помощник', icon: 'sparkles' },
      { to: '/admin', label: 'Администрирование', icon: 'shield', adminOnly: true },
    ],
  ],
]
// Сотруднику и хозяйственной службе доступны только заявки
const SERVICE_NAV: typeof NAV = [['Работа', [{ to: '/requests', label: 'Заявки', icon: 'inbox' }]]]

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
    else if (note.task_id) navigate('/workflow')
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
                className={`note ${n.read_at ? '' : 'unread'} ${n.request_id || n.task_id ? 'clickable' : ''}`}
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
  const service = isServiceRole(user)
  // Счётчик просроченных заявок в меню — чтобы о них не нужно было вспоминать
  const requests = useApi<RequestStats>('/requests/stats')
  const groups = service ? SERVICE_NAV : NAV
  const home = service ? '/requests' : '/'

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="users" />
          </span>
          <div>
            Кадровый потенциал
            <small>образовательных учреждений</small>
          </div>
        </div>
        <nav>
          {groups.map(([group, items]) => (
            <div key={group}>
              <div className="nav-group">{group}</div>
              {items
                .filter((item) => !item.adminOnly || user.role === 'admin')
                .map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === '/'}>
                    <Icon name={item.icon} />
                    {item.label}
                    {item.to === '/requests' && requests.data?.overdue ? (
                      <span className="nav-count" title="Просрочено">
                        {requests.data.overdue}
                      </span>
                    ) : null}
                  </NavLink>
                ))}
            </div>
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
            {!service && (
              <>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/workload" element={<Workload />} />
                <Route path="/organizations" element={<Organizations />} />
                <Route path="/organizations/:id" element={<OrganizationPage />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/centralization" element={<Centralization />} />
                <Route path="/program" element={<ProgramPage />} />
                <Route path="/projects" element={<Projects />} />
                <Route path="/projects/:id" element={<ProjectPage />} />
                <Route path="/workflow" element={<Workflow />} />
                <Route path="/norms" element={<Norms />} />
                <Route path="/knowledge" element={<Knowledge />} />
                <Route path="/assistant" element={<Assistant />} />
              </>
            )}
            {user.role === 'admin' && <Route path="/admin" element={<Admin />} />}
            <Route path="*" element={<Navigate to={home} replace />} />
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
