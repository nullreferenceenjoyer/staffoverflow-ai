import { StaffingProblem, StaffingResult } from '../../api'
import { fmtDeviation, fmtFte, STAFFING_STATUS } from '../../lib'
import { Badge } from '../ui'

export function StatusBadge({ status }: { status: string }) {
  const info = STAFFING_STATUS[status] ?? STAFFING_STATUS.no_data
  return <Badge tone={info.tone}>{info.label}</Badge>
}

/** Отклонение в ставках: дефицит красным, излишек оранжевым, норма — спокойным цветом. */
export function Deviation({ value, status }: { value: number | null; status: string }) {
  const tone =
    status === 'deficit' ? 'dev-deficit' : status === 'surplus' ? 'dev-surplus' : 'dev-calm'
  return <span className={`num ${tone}`}>{fmtDeviation(value)}</span>
}

/** «Что не так»: две-три группы с наибольшим отклонением или чего не хватает. */
export function ProblemList({
  row,
  problems,
}: {
  row: StaffingResult
  problems: StaffingProblem[]
}) {
  const off = problems.filter((p) => p.status === 'deficit' || p.status === 'surplus')
  if (row.status === 'no_data' || (off.length === 0 && row.reasons.length > 0)) {
    return <span className="muted">{row.reasons.join('; ')}</span>
  }
  if (off.length === 0) return <span className="muted">—</span>
  return (
    <span className="problem-list">
      {off.slice(0, 3).map((p) => (
        <span key={p.group}>
          {p.group} <Deviation value={p.deviation} status={p.status} />
        </span>
      ))}
      {off.length > 3 && <span className="muted">и ещё {off.length - 3}</span>}
    </span>
  )
}

/** Подпись факта: «Занято» или «По штатке». */
export const factLabel = (basis: string) => (basis === 'occupied' ? 'Занято' : 'По штатке')

export function Totals({ row }: { row: StaffingResult }) {
  return (
    <dl className="facts">
      <dt>Норматив</dt>
      <dd className="strong-num">{fmtFte(row.required)} ставки</dd>
      <dt>{factLabel(row.basis)}</dt>
      <dd className="strong-num">{fmtFte(row.fact)} ставки</dd>
      <dt>Отклонение</dt>
      <dd className="strong-num">
        <Deviation value={row.deviation} status={row.status} />
        {row.deviation_pct !== null && row.status !== 'normal' && (
          <span className="muted"> · {Math.abs(row.deviation_pct).toLocaleString('ru-RU')} %</span>
        )}
      </dd>
      <dt>Статус</dt>
      <dd>
        <StatusBadge status={row.status} />
        {row.reasons.length > 0 && <div className="muted">{row.reasons.join('; ')}</div>}
      </dd>
    </dl>
  )
}
