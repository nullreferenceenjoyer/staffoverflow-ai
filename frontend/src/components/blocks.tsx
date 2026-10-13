import { Finding, RequestStats } from '../api'
import { fmtMoney } from '../lib'
import { Legend } from './charts'
import { Badge } from './ui'

export const VERDICT: Record<string, { label: string; tone: string }> = {
  duplicate: { label: 'Дублирование по соседству', tone: 'orange' },
  idle: { label: 'Недозагрузка', tone: 'amber' },
  overload: { label: 'Перегрузка', tone: 'red' },
  underused: { label: 'Здание недозаполнено', tone: 'gray' },
  ok: { label: 'В норме', tone: 'green' },
}

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

export function FindingRow({ finding }: { finding: Finding }) {
  return (
    <div className="finding">
      <span className={`finding-mark ${finding.verdict}`} />
      <div className="finding-body">
        <div className="chips">
          <strong>{finding.title}</strong>
          <Badge tone={VERDICT[finding.verdict].tone}>{VERDICT[finding.verdict].label}</Badge>
        </div>
        <div className="muted">{finding.site}</div>
        <p>{finding.recommendation}</p>
      </div>
      {finding.saving_year > 0 && (
        <div className="finding-side">
          <strong>{fmtMoney(finding.saving_year)}</strong>
          <span className="muted">в год</span>
        </div>
      )}
    </div>
  )
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
