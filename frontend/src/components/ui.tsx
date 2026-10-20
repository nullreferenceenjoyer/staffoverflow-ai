import { FormEvent, ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { Icon, IconName } from './icons'

export function Page({
  title,
  hint,
  actions,
  children,
}: {
  title: string
  hint?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{title}</h1>
          {hint && <p className="hint">{hint}</p>}
        </div>
        {actions && <div className="actions wrap">{actions}</div>}
      </header>
      {children}
    </div>
  )
}

export function Card({
  title,
  aside,
  children,
}: {
  title?: string
  aside?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card">
      {(title || aside) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  )
}

/** Число, которое «докручивается» до значения при появлении и при каждом изменении. */
export function Counter({
  value,
  format = String,
}: {
  value: number
  format?: (value: number) => string
}) {
  const [shown, setShown] = useState(0)
  const from = useRef(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(value)
      return
    }
    const start = performance.now()
    const origin = from.current
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min((now - start) / 700, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      const current = origin + (value - origin) * eased
      from.current = current
      setShown(t === 1 ? value : current)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])

  return <>{format(shown)}</>
}

export function Kpi({
  label,
  value,
  note,
  icon,
  tone,
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  icon?: IconName
  tone?: 'good' | 'warn' | 'critical'
}) {
  return (
    <div className={`kpi ${tone ? `tone-${tone}` : ''}`}>
      <span className="kpi-label">
        {icon && (
          <span className="kpi-icon">
            <Icon name={icon} size={16} />
          </span>
        )}
        {label}
      </span>
      <strong>{value}</strong>
      {note && <span className="kpi-note">{note}</span>}
    </div>
  )
}

export function Avatar({ name, small }: { name: string; small?: boolean }) {
  const initials = name
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
  return (
    <span className={`avatar ${small ? 'small' : ''}`} title={name}>
      {initials.toUpperCase()}
    </span>
  )
}

export function Badge({ tone = 'gray', children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

/** Обёртка для состояний загрузки: показывает спиннер, ошибку или содержимое. */
export function Async<T>({
  state,
  children,
}: {
  state: { data: T | null; error: string | null; loading: boolean }
  children: (data: T) => ReactNode
}) {
  if (state.error) return <div className="notice notice-error">{state.error}</div>
  if (state.data === null) {
    return (
      <div className="skeletons" aria-busy="true" aria-label="Загрузка">
        <div className="row">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 92 }} />
          ))}
        </div>
        <div className="skeleton" style={{ height: 260 }} />
      </div>
    )
  }
  return <div className={state.loading ? 'stale' : undefined}>{children(state.data)}</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: [T, string][]
  value: T
  onChange: (tab: T) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([key, label]) => (
        <button
          key={key}
          role="tab"
          aria-selected={key === value}
          className={key === value ? 'active' : ''}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/** Переключатель из двух-трёх значений: «АУП | Вспомогательный». */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: [T, string][]
  value: T
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([key, title]) => (
        <button
          key={key}
          type="button"
          aria-pressed={key === value}
          className={key === value ? 'active' : ''}
          onClick={() => onChange(key)}
        >
          {title}
        </button>
      ))}
    </div>
  )
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // В корень документа: внутри анимированной карточки fixed отсчитывался бы от неё
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-label={title}>
        <div className="card-head">
          <h2>{title}</h2>
          <button className="ghost icon" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** Боковая панель: карточка объекта поверх списка, список остаётся на месте. */
export function Drawer({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** Для широких таблиц: штатка с окладами и ФОТ */
  wide?: boolean
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className={`drawer ${wide ? 'drawer-wide' : ''}`} role="dialog">
        <div className="drawer-head">
          <div>{title}</div>
          <button className="ghost icon" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </div>,
    document.body,
  )
}

/** Форма с единообразной обработкой отправки и ошибок сервера. */
export function Form({
  onSubmit,
  submitLabel = 'Сохранить',
  children,
}: {
  onSubmit: () => Promise<void>
  submitLabel?: string
  children: ReactNode
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handle(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={handle}>
      {children}
      {error && <div className="notice notice-error">{error}</div>}
      <div className="form-actions">
        <button type="submit" className="primary" disabled={busy}>
          {busy ? 'Подождите…' : submitLabel}
        </button>
      </div>
    </form>
  )
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  )
}
