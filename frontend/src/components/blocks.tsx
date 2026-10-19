import { RequestStats } from '../api'
import { Legend } from './charts'

// Цвета статусов заявок — те же, что у бейджей
export const STATUS_COLOR: Record<string, string> = {
  new: 'var(--warn)',
  assigned: 'var(--series-1)',
  in_progress: 'var(--series-1)',
  on_hold: 'var(--serious)',
  done: 'var(--good)',
  closed: 'var(--series-muted)',
  rejected: 'var(--critical)',
}

export function StatusBar({ items }: { items: RequestStats['by_status'] }) {
  const shown = items.filter((item) => item.count > 0)
  return (
    <>
      <div className="statusbar">
        {shown.map((item) => (
          <i
            key={item.status}
            style={{ flex: item.count, background: STATUS_COLOR[item.status] }}
            title={`${item.title}: ${item.count}`}
          />
        ))}
      </div>
      <Legend
        items={shown.map((item) => [`${item.title} · ${item.count}`, STATUS_COLOR[item.status]])}
      />
    </>
  )
}
