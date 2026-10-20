import { useEffect, useMemo, useRef, useState } from 'react'

import { ScheduleList, StaffingMeta } from '../../api'
import { Meter } from '../../components/charts'
import {
  MoneyDelta,
  ScheduleActions,
  ScheduleDetail,
  ScheduleMode,
  useSchedule,
} from '../../components/staffing/Schedule'
import { Async, Card, Empty, Kpi } from '../../components/ui'
import { fmtDate, fmtDeviation, fmtFte, fmtRubShort, ORG_TYPE_LABELS, useApi } from '../../lib'

const PAGE = 100

/** Директору — сразу его штатка, без списка учреждений. */
function OwnSchedule({
  organizationId,
  year,
  mode,
  version,
}: {
  organizationId: number
  year: string
  mode: ScheduleMode
  version: number
}) {
  const state = useSchedule(organizationId, year, 'occupied')
  const { reload } = state
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    void reload({ silent: true })
  }, [version, reload])
  return (
    <Async state={state}>
      {(data) => (
        <Card>
          <ScheduleDetail data={data} mode={mode} />
          <ScheduleActions
            data={data}
            year={year}
            onChanged={() => void reload({ silent: true })}
          />
        </Card>
      )}
    </Async>
  )
}

export function Schedules({
  meta,
  year,
  mode,
  version,
  onOpen,
}: {
  meta: StaffingMeta
  year: string
  mode: ScheduleMode
  version: number
  onOpen: (id: number) => void
}) {
  if (meta.organization)
    return (
      <OwnSchedule
        organizationId={meta.organization.id}
        year={year}
        mode={mode}
        version={version}
      />
    )
  return <ScheduleTable meta={meta} year={year} mode={mode} version={version} onOpen={onOpen} />
}

function ScheduleTable({
  meta,
  year,
  mode,
  version,
  onOpen,
}: {
  meta: StaffingMeta
  year: string
  mode: ScheduleMode
  version: number
  onOpen: (id: number) => void
}) {
  const [municipality, setMunicipality] = useState('')
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(PAGE)
  const state = useApi<ScheduleList>('/staffing/schedules', {
    year,
    municipality_id: municipality || null,
  })
  const { reload } = state
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    void reload({ silent: true })
  }, [version, reload])

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const items = (state.data?.items ?? []).filter(
      (i) => !needle || `${i.organization} ${i.municipality}`.toLowerCase().includes(needle),
    )
    if (mode === 'fact')
      // Сначала самые недоукомплектованные; без данных о занятости — в конце
      return [...items].sort((a, b) => (a.staffed_pct ?? 101) - (b.staffed_pct ?? 101))
    return [...items].sort((a, b) => (b.payroll_approved ?? 0) - (a.payroll_approved ?? 0))
  }, [state.data, search, mode])

  const details = meta.permissions.details

  return (
    <Async state={state}>
      {(data) => {
        const t = data.totals
        const changed = data.items.filter((i) => i.last_change).length
        const noSchedule = data.items.filter((i) => !i.status).length
        return (
          <>
            <div className="kpis">
              {mode === 'schedule' ? (
                <>
                  <Kpi
                    icon="doc"
                    label="Ставок по штаткам"
                    value={fmtFte(t.approved)}
                    note={`${data.items.length - noSchedule} из ${data.items.length} учреждений со штаткой`}
                  />
                  <Kpi
                    icon="scale"
                    label="ФОТ по штаткам"
                    value={fmtRubShort(t.payroll_approved)}
                    note="в год: оклад × ставки × 12"
                  />
                  <Kpi
                    icon="refresh"
                    label="Штатки меняли"
                    value={changed}
                    note="учреждений с изменениями в этом году"
                  />
                  <Kpi
                    icon="alert"
                    tone={t.missing_salary ? 'warn' : 'good'}
                    label="Без оклада"
                    value={t.missing_salary}
                    note={
                      t.missing_salary ? 'групп: ФОТ по ним не посчитан' : 'оклады указаны везде'
                    }
                  />
                </>
              ) : (
                <>
                  <Kpi
                    icon="users"
                    label="Занято ставок"
                    value={fmtFte(t.occupied)}
                    note={`из ${fmtFte(t.approved)} утверждённых`}
                  />
                  <Kpi
                    icon="alert"
                    tone={t.vacant ? 'warn' : 'good'}
                    label="Вакантно"
                    value={fmtFte(t.vacant)}
                    note="ставок свободно"
                  />
                  <Kpi
                    icon="scale"
                    label="ФОТ занятых"
                    value={fmtRubShort(t.payroll_occupied)}
                    note="в год"
                  />
                  <Kpi
                    icon="scale"
                    label="На вакансии"
                    value={fmtRubShort(t.vacant_payroll)}
                    note="в год: заложено в штатке, но не выплачивается"
                  />
                </>
              )}
            </div>

            <div className="toolbar">
              {meta.municipalities.length > 1 && (
                <select
                  value={municipality}
                  onChange={(e) => setMunicipality(e.target.value)}
                  aria-label="Территория"
                >
                  <option value="">Весь регион</option>
                  {meta.municipalities.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              )}
              <input
                type="search"
                placeholder="Поиск учреждения"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {shown.length === 0 ? (
              <Empty>Учреждений нет.</Empty>
            ) : (
              <Card>
                <table className="stack staffing-table">
                  <thead>
                    {mode === 'schedule' ? (
                      <tr>
                        <th>Учреждение</th>
                        <th>Штатка</th>
                        <th className="num">Ставок</th>
                        <th className="num">ФОТ в год</th>
                        <th>Последнее изменение</th>
                      </tr>
                    ) : (
                      <tr>
                        <th>Учреждение</th>
                        <th className="num">Утверждено</th>
                        <th className="num">Занято</th>
                        <th className="num">Вакантно</th>
                        <th>Укомплектованность</th>
                        <th className="num">На вакансии</th>
                      </tr>
                    )}
                  </thead>
                  <tbody>
                    {shown.slice(0, limit).map((i) => (
                      <tr
                        key={i.organization_id}
                        className={details ? 'clickable' : ''}
                        onClick={() => details && onOpen(i.organization_id)}
                      >
                        <td data-label="Учреждение">
                          <strong>{i.organization}</strong>
                          <div className="muted">
                            {i.municipality} · {ORG_TYPE_LABELS[i.org_type]}
                          </div>
                        </td>
                        {mode === 'schedule' ? (
                          <>
                            <td data-label="Штатка">
                              {i.status_title}
                              {i.missing_salary > 0 && (
                                <div className="muted small-text">
                                  без оклада: {i.missing_salary}
                                </div>
                              )}
                            </td>
                            <td data-label="Ставок" className="num">
                              {i.status ? fmtFte(i.approved) : '—'}
                            </td>
                            <td data-label="ФОТ в год" className="num">
                              {fmtRubShort(i.payroll_approved)}
                            </td>
                            <td data-label="Последнее изменение">
                              {i.last_change ? (
                                <>
                                  {fmtDate(i.last_change.created_at)}:{' '}
                                  {fmtDeviation(i.last_change.approved_delta)} ст.,{' '}
                                  <MoneyDelta value={i.last_change.payroll_delta} />
                                  <div className="muted small-text">
                                    {i.last_change.changes
                                      .map((c) => `${c.group} ${fmtDeviation(c.approved_delta)}`)
                                      .join(', ')}
                                  </div>
                                </>
                              ) : (
                                <span className="muted">не менялась</span>
                              )}
                            </td>
                          </>
                        ) : (
                          <>
                            <td data-label="Утверждено" className="num">
                              {i.status ? fmtFte(i.approved) : '—'}
                            </td>
                            <td data-label="Занято" className="num">
                              {fmtFte(i.occupied)}
                            </td>
                            <td data-label="Вакантно" className="num">
                              {i.vacant ? fmtFte(i.vacant) : '—'}
                            </td>
                            <td data-label="Укомплектованность" className="meter-cell">
                              {i.staffed_pct === null ? (
                                <span className="muted">
                                  {i.status ? 'занятость не ведётся' : 'нет штатки'}
                                </span>
                              ) : (
                                <Meter label="" value={i.staffed_pct} low={i.staffed_pct < 95} />
                              )}
                            </td>
                            <td data-label="На вакансии" className="num">
                              {i.vacant_payroll ? fmtRubShort(i.vacant_payroll) : '—'}
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {shown.length > limit && (
                  <button className="ghost" onClick={() => setLimit(limit + PAGE)}>
                    Показать ещё {Math.min(PAGE, shown.length - limit)}
                  </button>
                )}
              </Card>
            )}
          </>
        )
      }}
    </Async>
  )
}
