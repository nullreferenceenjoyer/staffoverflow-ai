import { FormEvent, ReactNode, useEffect, useState } from 'react'

import { Municipality } from '../api'
import { fmtDelta, useApi } from '../lib'

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
    <>
      <header className="page-header">
        <div>
          <h1>{title}</h1>
          {hint && <p className="hint">{hint}</p>}
        </div>
        {actions && <div className="actions">{actions}</div>}
      </header>
      {children}
    </>
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

export function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <strong>{value}</strong>
      {note && <span className="kpi-note">{note}</span>}
    </div>
  )
}

export function Badge({ tone = 'gray', children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

/** Отклонение в ставках: избыток подсвечивается жёлтым, нехватка — красным. */
export function Delta({ value }: { value: number }) {
  if (Math.abs(value) < 0.005) return <span className="muted">0</span>
  return <span className={value > 0 ? 'delta-plus' : 'delta-minus'}>{fmtDelta(value)}</span>
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
  if (state.data === null) return <div className="muted pad">Загрузка…</div>
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

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-label={title}>
        <div className="card-head">
          <h2>{title}</h2>
          <button className="ghost" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
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

export function MunicipalitySelect({
  value,
  onChange,
  allLabel = 'Все муниципалитеты',
}: {
  value: number | null
  onChange: (id: number | null) => void
  allLabel?: string | null
}) {
  const { data } = useApi<Municipality[]>('/municipalities')
  // Директору и специалисту доступен один муниципалитет — выбирать не из чего
  if (!data || data.length < 2) return null
  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      aria-label="Муниципалитет"
    >
      {allLabel && <option value="">{allLabel}</option>}
      {data.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name}
        </option>
      ))}
    </select>
  )
}

/** Кнопка для действий с запросом к серверу: блокируется на время выполнения. */
export function ActionButton({
  onClick,
  children,
  className = '',
  confirm,
}: {
  onClick: () => Promise<unknown>
  children: ReactNode
  className?: string
  confirm?: string
}) {
  const [busy, setBusy] = useState(false)
  return (
    <button
      className={className}
      disabled={busy}
      onClick={async () => {
        if (confirm && !window.confirm(confirm)) return
        setBusy(true)
        try {
          await onClick()
        } catch (e) {
          window.alert(e instanceof Error ? e.message : 'Не удалось выполнить действие')
        } finally {
          setBusy(false)
        }
      }}
    >
      {busy ? 'Подождите…' : children}
    </button>
  )
}
