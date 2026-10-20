import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { InstitutionSchedule, ScheduleLine, ScheduleVersion, StaffBasis } from '../../api'
import {
  fmtDate,
  fmtDateTime,
  fmtDeviation,
  fmtFte,
  fmtRub,
  fmtRubDelta,
  fmtRubShort,
  useApi,
} from '../../lib'
import { Icon } from '../icons'
import { Drawer, Segmented } from '../ui'
import { DataEditor } from './DataEditor'
import { StatusBadge } from './parts'

export type ScheduleMode = 'schedule' | 'fact'

const CATEGORY_TITLE = { aup: 'АУП', support: 'Вспомогательный персонал' }

/** «−270 000 ₽» зелёным, если ФОТ уменьшился, оранжевым — если вырос. */
export function MoneyDelta({ value }: { value: number | null }) {
  if (value === null || value === 0) return <span className="muted">без изменений ФОТ</span>
  return <span className={value < 0 ? 'dev-calm' : 'dev-surplus'}>{fmtRubDelta(value)}/год</span>
}

function changeLine(c: ScheduleVersion['changes'][number]) {
  const parts = []
  if (c.approved_delta) parts.push(`${fmtFte(c.approved_before)} → ${fmtFte(c.approved_after)} ст.`)
  if (c.salary_before !== c.salary_after)
    parts.push(`оклад ${fmtRub(c.salary_before)} → ${fmtRub(c.salary_after)}`)
  return parts.join(', ')
}

/** История штатки: что поменялось и как это сдвинуло ФОТ. */
export function History({ versions }: { versions: ScheduleVersion[] }) {
  if (!versions.length) return <p className="muted">Изменений пока не было.</p>
  return (
    <ol className="timeline">
      {versions.map((v) => (
        <li key={v.id}>
          <div className="timeline-head">
            <strong>{fmtDate(v.created_at)}</strong>
            <span className="muted">
              {v.author ?? v.source_title} · {v.status_title}
            </span>
          </div>
          {v.comment && <div>{v.comment}</div>}
          {v.first ? (
            <div className="muted">
              Исходная штатка: {fmtFte(v.approved)} ставок, ФОТ {fmtRub(v.payroll_approved)}/год
            </div>
          ) : (
            <>
              <ul className="why">
                {v.changes.map((c) => (
                  <li key={c.group_id}>
                    <strong>{c.group}:</strong> {changeLine(c)}{' '}
                    {c.payroll_delta !== null && <MoneyDelta value={c.payroll_delta} />}
                  </li>
                ))}
                {v.changes.length === 0 && <li className="muted">изменился статус штатки</li>}
              </ul>
              <div className="timeline-total">
                Итого: {fmtDeviation(v.approved_delta)} ст., ФОТ{' '}
                <MoneyDelta value={v.payroll_delta} /> → {fmtRub(v.payroll_approved)}/год
              </div>
            </>
          )}
        </li>
      ))}
    </ol>
  )
}

function Row({ line, mode }: { line: ScheduleLine; mode: ScheduleMode }) {
  return (
    <tr>
      <td data-label="Группа">
        {line.group}
        {line.status && line.status !== 'normal' && (
          <div>
            <StatusBadge status={line.status} />
          </div>
        )}
      </td>
      {mode === 'schedule' ? (
        <>
          <td data-label="Ставок" className="num">
            {fmtFte(line.approved)}
          </td>
          <td data-label="Оклад, ₽/мес" className="num">
            {line.salary === null ? <span className="muted">не указан</span> : fmtRub(line.salary)}
          </td>
          <td data-label="ФОТ, ₽/год" className="num">
            {fmtRub(line.payroll_approved)}
          </td>
        </>
      ) : (
        <>
          <td data-label="Утверждено" className="num">
            {fmtFte(line.approved)}
          </td>
          <td data-label="Занято" className="num">
            {line.occupied === null ? (
              <span className="muted">не ведётся</span>
            ) : (
              fmtFte(line.occupied)
            )}
          </td>
          <td data-label="Вакантно" className="num">
            {line.vacant ? fmtFte(line.vacant) : '—'}
          </td>
          <td data-label="ФОТ занятых" className="num">
            {fmtRub(line.payroll_occupied)}
          </td>
        </>
      )}
      <td data-label="Норматив" className="num">
        {fmtFte(line.required)}
      </td>
      <td data-label="Отклонение" className="num">
        <span
          className={
            line.status === 'deficit'
              ? 'dev-deficit'
              : line.status === 'surplus'
                ? 'dev-surplus'
                : 'dev-calm'
          }
        >
          {fmtDeviation(line.deviation)}
        </span>
        {line.deviation_cost !== null && line.deviation !== 0 && (
          <div
            className="muted small-text"
            title={line.salary_estimated ? 'По среднему окладу муниципалитета' : undefined}
          >
            {line.salary_estimated ? '≈ ' : ''}
            {fmtRubShort(Math.abs(line.deviation_cost))}/год
          </div>
        )}
      </td>
    </tr>
  )
}

/** Штатка учреждения по группам: ставки, оклады, ФОТ, норматив и история. */
export function ScheduleDetail({ data, mode }: { data: InstitutionSchedule; mode: ScheduleMode }) {
  const t = data.totals
  if (!data.schedule && data.lines.every((l) => l.approved === null))
    return <p className="muted">Штатного расписания на {data.year} нет.</p>
  return (
    <>
      <dl className="facts facts-row">
        {mode === 'schedule' ? (
          <>
            <dt>Ставок по штатке</dt>
            <dd className="strong-num">{fmtFte(t.approved)}</dd>
            <dt>ФОТ по штатке</dt>
            <dd className="strong-num">{fmtRub(t.payroll_approved)}/год</dd>
            <dt>Статус</dt>
            <dd>{data.schedule?.status_title ?? 'нет штатки'}</dd>
          </>
        ) : (
          <>
            <dt>Занято</dt>
            <dd className="strong-num">
              {fmtFte(t.occupied)} из {fmtFte(t.approved)}
            </dd>
            <dt>Вакантно</dt>
            <dd className="strong-num">{fmtFte(t.vacant)} ст.</dd>
            <dt>ФОТ занятых</dt>
            <dd className="strong-num">{fmtRub(t.payroll_occupied)}/год</dd>
            <dt>На вакансии</dt>
            <dd>{fmtRub(t.vacant_payroll)}/год</dd>
          </>
        )}
      </dl>
      {t.missing_salary > 0 && (
        <div className="notice">
          У {t.missing_salary} групп не указан оклад — их ФОТ не посчитан. Внесите оклады в
          «Изменить штатку».
        </div>
      )}
      {(['aup', 'support'] as const).map((category) => {
        const lines = data.lines.filter((l) => l.category === category)
        if (!lines.length) return null
        const part = data.by_category[category]
        return (
          <section key={category}>
            <h3>
              {CATEGORY_TITLE[category]}{' '}
              <span className="muted">
                · {fmtFte(mode === 'schedule' ? part.approved : part.occupied)} ст. ·{' '}
                {fmtRubShort(mode === 'schedule' ? part.payroll_approved : part.payroll_occupied)}
                /год
              </span>
            </h3>
            <table className="stack compact schedule-table">
              <thead>
                <tr>
                  <th>Группа</th>
                  {mode === 'schedule' ? (
                    <>
                      <th className="num">Ставок</th>
                      <th className="num">Оклад, ₽/мес</th>
                      <th className="num">ФОТ, ₽/год</th>
                    </>
                  ) : (
                    <>
                      <th className="num">Утверждено</th>
                      <th className="num">Занято</th>
                      <th className="num">Вакантно</th>
                      <th className="num">ФОТ занятых</th>
                    </>
                  )}
                  <th className="num">Норматив</th>
                  <th className="num">Отклонение</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <Row key={l.group_id} line={l} mode={mode} />
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
      <p className="muted small-text">
        ФОТ = средний оклад за ставку × ставки × 12, без надбавок. Цена отклонения — сколько в год
        стоят недостающие или лишние ставки; «≈» — оклада в штатке нет, взят средний по
        муниципалитету.
      </p>
      <h3>История изменений</h3>
      <History versions={data.history} />
    </>
  )
}

/** Загрузка штатки учреждения с кнопками «Изменить» и «Спросить помощника». */
export function useSchedule(organizationId: number | null, year: string, basis: StaffBasis) {
  return useApi<InstitutionSchedule>(
    organizationId ? `/staffing/institutions/${organizationId}/schedule` : null,
    { year, basis },
  )
}

export function ScheduleActions({
  data,
  year,
  onChanged,
}: {
  data: InstitutionSchedule
  year: string
  onChanged: () => void
}) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  return (
    <>
      <div className="actions wrap">
        {data.can_edit && (
          <button className="primary" onClick={() => setEditing(true)}>
            <Icon name="edit" size={16} /> Изменить штатку
          </button>
        )}
        <button
          className="ghost"
          onClick={() =>
            navigate(`/staffing?tab=assistant&about=${data.organization_id}&year=${year}`)
          }
        >
          <Icon name="message" size={16} /> Спросить помощника
        </button>
      </div>
      {editing && (
        <DataEditor
          organizationId={data.organization_id}
          year={year}
          onClose={() => setEditing(false)}
          onSaved={onChanged}
        />
      )}
    </>
  )
}

export function ScheduleDrawer({
  organizationId,
  year,
  initialMode,
  onClose,
  onChanged,
}: {
  organizationId: number
  year: string
  initialMode: ScheduleMode
  onClose: () => void
  onChanged: () => void
}) {
  const [mode, setMode] = useState(initialMode)
  const state = useSchedule(organizationId, year, 'occupied')
  const data = state.data
  return (
    <Drawer
      title={
        <>
          <h2>{data?.organization ?? 'Штатка'}</h2>
          <span className="muted">
            Штатка {year}
            {data?.schedule?.updated_at && ` · изменена ${fmtDateTime(data.schedule.updated_at)}`}
          </span>
        </>
      }
      wide
      onClose={onClose}
      footer={
        data && (
          <ScheduleActions
            data={data}
            year={year}
            onChanged={() => {
              void state.reload({ silent: true })
              onChanged()
            }}
          />
        )
      }
    >
      {state.error ? (
        <div className="notice notice-error">{state.error}</div>
      ) : !data ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : (
        <>
          <div className="toolbar">
            <Segmented
              label="Что показать"
              options={[
                ['schedule', 'Штатка и ФОТ'],
                ['fact', 'Факт и вакансии'],
              ]}
              value={mode}
              onChange={setMode}
            />
          </div>
          <ScheduleDetail data={data} mode={mode} />
        </>
      )}
    </Drawer>
  )
}
