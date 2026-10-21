import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api, getToken, LlmStatus, Notification, RequestStats, setToken, User } from './api'
import { Icon, IconName } from './components/icons'
import { Avatar } from './components/ui'
import { debounce, fmtDateTime, ROLE_LABELS, useApi } from './lib'
import { startLive, stopLive, useLive, useLiveConnected, useLlmStatus } from './live'
import { Admin } from './pages/Admin'
import { Login } from './pages/Login'
import { Requests } from './pages/Requests'
import { Staffing } from './pages/Staffing'

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

// Нормативную численность видят те, кто принимает кадровые решения: сотруднику,
// хозслужбе и бригадам раздел ни к чему
const STAFFING_ROLES: User['role'][] = [
  'admin',
  'regional_analyst',
  'municipal_specialist',
  'director',
  'observer',
]

const NAV: NavItem[] = [
  { to: '/requests', label: 'Заявки', icon: 'inbox' },
  { to: '/staffing', label: 'Оптимизация штата', icon: 'scale', roles: STAFFING_ROLES },
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
  const reload = state.reload
  const openRef = useRef(open)
  openRef.current = open

  // Новое уведомление появляется под колокольчиком сразу, без перезагрузки страницы
  useLive((event) => {
    if (event.type !== 'notifications') return
    void (async () => {
      await reload({ silent: true })
      // Панель открыта — пользователь их уже видит
      if (openRef.current) await api('/notifications/read', { method: 'POST' }).catch(() => {})
    })()
  })

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) {
        setOpen(false)
        void reload({ silent: true })
      }
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open, reload])

  async function toggle() {
    setOpen(!open)
    if (!open) {
      // Сначала свежий список, потом отметка о прочтении: непрочитанные остаются
      // выделены, пока панель открыта
      await reload({ silent: true })
      await api('/notifications/read', { method: 'POST' }).catch(() => {})
    } else {
      void reload({ silent: true })
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

/** Значок связи: зелёный — изменения приходят сразу, серый — переподключаемся. */
function LiveDot() {
  const connected = useLiveConnected()
  const [grace, setGrace] = useState(true)
  // Первые секунды соединение ещё устанавливается — не пугаем серым значком
  useEffect(() => {
    const timer = setTimeout(() => setGrace(false), 5000)
    return () => clearTimeout(timer)
  }, [])
  const off = !connected && !grace
  return (
    <span
      className={`live-dot ${connected ? 'on' : off ? 'off' : ''}`}
      role="status"
      title={
        connected
          ? 'Изменения заявок появляются сразу'
          : 'Нет связи с сервером, переподключаемся. Данные могут быть устаревшими.'
      }
    >
      <i />
      {off && <span>нет связи</span>}
    </span>
  )
}

function llmMessage(state: LlmStatus) {
  if (!state.configured) {
    return 'Языковая модель не подключена: тема новых заявок определяется по ключевым словам. Чтобы включить модель, задайте LLM_BASE_URL в .env (см. README).'
  }
  const since = state.since ? ` с ${fmtDateTime(state.since)}` : ''
  return `Языковая модель не отвечает${since}: тема новых заявок определяется по ключевым словам.${state.error ? ` Причина: ${state.error}` : ''}`
}

/** Администратор сразу видит, что модель выключена или не работает. */
function LlmBanner() {
  const state = useLlmStatus()
  const [checking, setChecking] = useState(false)
  const [hidden, setHidden] = useState(false)
  const data = state.data
  if (!data || data.available !== false || hidden) return null

  async function check() {
    setChecking(true)
    try {
      state.setData(await api<LlmStatus>('/llm/check', { method: 'POST' }))
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className={`notice llm-banner ${data.configured ? 'notice-error' : ''}`} role="alert">
      <Icon name="alert" />
      <span>{llmMessage(data)}</span>
      <span className="actions">
        {data.configured && (
          <button className="small" disabled={checking} onClick={check}>
            {checking ? 'Проверяем…' : 'Проверить сейчас'}
          </button>
        )}
        <button className="ghost icon" aria-label="Скрыть" onClick={() => setHidden(true)}>
          <Icon name="x" size={16} />
        </button>
      </span>
    </div>
  )
}

function Layout({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [theme, toggleTheme] = useTheme()
  const location = useLocation()
  // На узком экране меню выезжает поверх страницы и закрывается после перехода
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => setMenuOpen(false), [location.pathname])
  // Поток событий живёт, пока пользователь в системе
  useEffect(() => {
    startLive()
    return stopLive
  }, [])
  // Счётчики заявок в меню — чтобы о них не нужно было вспоминать
  const requests = useApi<RequestStats>('/requests/stats')
  const reloadRequests = requests.reload
  const refreshCounts = useMemo(
    () => debounce(() => void reloadRequests({ silent: true }), 1000),
    [reloadRequests],
  )
  useLive((event) => {
    if (event.type === 'requests') refreshCounts()
  })
  useEffect(() => {
    // Просрочка наступает со временем, без событий, поэтому изредка перечитываем и так
    const timer = setInterval(refreshCounts, 120_000)
    window.addEventListener('requests-changed', refreshCounts)
    return () => {
      clearInterval(timer)
      refreshCounts.cancel()
      window.removeEventListener('requests-changed', refreshCounts)
    }
  }, [refreshCounts])
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
          <LiveDot />
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
          {user.role === 'admin' && <LlmBanner />}
          <Routes>
            <Route path="/requests" element={<Requests />} />
            {STAFFING_ROLES.includes(user.role) && (
              <Route path="/staffing" element={<Staffing />} />
            )}
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
