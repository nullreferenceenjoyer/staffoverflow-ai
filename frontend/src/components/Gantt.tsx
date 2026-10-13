import { Fragment, ReactNode, useMemo, useState } from 'react'

import { fmtDate } from '../lib'

export interface GanttItem {
  id: string | number
  label: string
  note?: string
  group?: string
  start: string | Date
  end: string | Date
  // Доля выполнения 0…1 — светлая заливка внутри полосы
  progress?: number
  tone?: 'blue' | 'green' | 'red' | 'amber' | 'gray'
  tip?: ReactNode
  onClick?: () => void
}

const DAY = 86_400_000
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

const day = (value: string | Date) => {
  const date = new Date(value)
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** Подписи шкалы: по неделям, если период короткий, иначе по месяцам. */
function ticks(from: number, to: number) {
  const result: { at: number; label: string }[] = []
  const weekly = to - from <= 75 * DAY
  const cursor = new Date(from)
  if (weekly) {
    cursor.setDate(cursor.getDate() - ((cursor.getDay() + 6) % 7))
  } else {
    cursor.setDate(1)
  }
  while (cursor.getTime() <= to) {
    if (cursor.getTime() >= from) {
      const label = weekly
        ? `${cursor.getDate()} ${MONTHS[cursor.getMonth()]}`
        : `${MONTHS[cursor.getMonth()]} ${String(cursor.getFullYear()).slice(2)}`
      result.push({ at: cursor.getTime(), label })
    }
    if (weekly) cursor.setDate(cursor.getDate() + 7)
    else cursor.setMonth(cursor.getMonth() + 1)
  }
  return result
}

/**
 * Диаграмма Ганта без сторонних библиотек: строки — работы, шкала — календарь.
 * Положение полос считается в процентах, поэтому диаграмма тянется по ширине карточки.
 */
export function Gantt({
  items,
  empty = 'Нет работ со сроками',
}: {
  items: GanttItem[]
  empty?: string
}) {
  const [tip, setTip] = useState<{ item: GanttItem; x: number; y: number } | null>(null)

  const range = useMemo(() => {
    if (!items.length) return null
    const today = day(new Date())
    let from = Math.min(today, ...items.map((i) => day(i.start)))
    let to = Math.max(today, ...items.map((i) => day(i.end)))
    // Небольшой запас по краям, чтобы полосы не упирались в рамку
    const pad = Math.max(Math.round((to - from) / DAY / 30), 1) * DAY
    from -= pad
    to += pad + DAY
    return { from, to, today }
  }, [items])

  if (!range) return <div className="empty">{empty}</div>

  const span = range.to - range.from
  const pos = (value: number) => ((value - range.from) / span) * 100
  const scale = ticks(range.from, range.to)

  let lastGroup: string | undefined

  return (
    <div className="gantt">
      <div className="gantt-grid">
        <div className="gantt-lines">
          {scale.map((t) => (
            <i key={t.at} style={{ left: `${pos(t.at)}%` }} />
          ))}
          <div className="gantt-today" style={{ left: `${pos(range.today)}%` }} />
        </div>
        <div className="gantt-head" />
        <div className="gantt-head">
          {scale.map((t) => (
            <span key={t.at} style={{ left: `${pos(t.at)}%` }}>
              {t.label}
            </span>
          ))}
        </div>
        {items.map((item, index) => {
          const start = day(item.start)
          const end = Math.max(day(item.end), start) + DAY
          const header = item.group !== lastGroup ? item.group : undefined
          lastGroup = item.group
          return (
            <Fragment key={item.id}>
              {header && <div className="gantt-group">{header}</div>}
              <div className="gantt-row">
                <div className="gantt-label">
                  <b>{item.label}</b>
                  {item.note && <small>{item.note}</small>}
                </div>
                <div className="gantt-track">
                  <div
                    className={`gantt-bar tone-${item.tone ?? 'blue'} ${item.onClick ? 'clickable' : ''}`}
                    style={{
                      left: `${pos(start)}%`,
                      width: `${pos(end) - pos(start)}%`,
                      animationDelay: `${Math.min(index * 0.03, 0.5)}s`,
                    }}
                    onClick={item.onClick}
                    onMouseMove={(e) => setTip({ item, x: e.clientX, y: e.clientY })}
                    onMouseLeave={() => setTip(null)}
                  >
                    {item.progress !== undefined && (
                      <i style={{ width: `${Math.min(item.progress, 1) * 100}%` }} />
                    )}
                  </div>
                </div>
              </div>
            </Fragment>
          )
        })}
      </div>
      {tip && (
        <div
          className="gantt-tip"
          style={{
            left: Math.min(tip.x + 14, window.innerWidth - 340),
            top: tip.y + 16,
          }}
        >
          <b>{tip.item.label}</b>
          {fmtDate(new Date(tip.item.start).toISOString())} —{' '}
          {fmtDate(new Date(tip.item.end).toISOString())}
          {tip.item.tip && <div>{tip.item.tip}</div>}
        </div>
      )}
    </div>
  )
}
