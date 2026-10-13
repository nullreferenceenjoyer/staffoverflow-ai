import { ReactNode } from 'react'

import { fmt } from '../lib'

// Цвета серий заданы в styles.css и идут в фиксированном порядке: серия не меняет цвет
// от того, сколько их на графике. Палитра проверена на различимость при дальтонизме.
export const SERIES = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
] as const
export const MUTED = 'var(--series-muted)'

// Встроенная анимация recharts выключена: появление графиков анимируется в styles.css,
// теми же кривыми, что и остальные блоки страницы.
export const AXIS = { tickLine: false, axisLine: false, tickMargin: 8 } as const
export const BAR = { radius: [4, 4, 0, 0] as [number, number, number, number], maxBarSize: 34 }

interface TipEntry {
  name?: string
  value?: number | string
  color?: string
  fill?: string
}

/** Всплывающая подсказка для графиков recharts в стиле интерфейса. */
export function ChartTip({
  active,
  label,
  payload,
  format = fmt,
}: {
  active?: boolean
  label?: string
  payload?: TipEntry[]
  format?: (value: number) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tip">
      {label && <b>{label}</b>}
      {payload.map((entry) => (
        <div key={entry.name}>
          <span className="swatch" style={{ background: entry.color ?? entry.fill }} />
          <span>{entry.name}</span>
          <span>{format(Number(entry.value))}</span>
        </div>
      ))}
    </div>
  )
}

export function Legend({ items }: { items: [label: string, color: string][] }) {
  return (
    <div className="legend">
      {items.map(([label, color]) => (
        <span key={label}>
          <i className="swatch" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  )
}

/** Полоса «сколько из целого»: одна метрика на строку, все строки в одной шкале. */
export function Meter({
  label,
  value,
  max = 100,
  mark,
  low,
  suffix = ' %',
  title,
}: {
  label: ReactNode
  value: number | null
  max?: number
  mark?: number
  low?: boolean
  suffix?: string
  title?: string
}) {
  const share = value === null ? 0 : Math.max(0, Math.min(value / max, 1))
  return (
    <div className="meter-row" title={title}>
      <span>{label}</span>
      <div className="meter">
        <i className={low ? 'low' : ''} style={{ width: `${share * 100}%` }} />
        {mark !== undefined && <u style={{ left: `${Math.min(mark / max, 1) * 100}%` }} />}
      </div>
      <span className="num">{value === null ? '—' : `${fmt(value)}${suffix}`}</span>
    </div>
  )
}
