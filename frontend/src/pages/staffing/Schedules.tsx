import { useEffect, useMemo, useRef, useState } from 'react'

import { ScheduleList, StaffingMeta } from '../../api'
import { Meter } from '../../components/charts'
import { HowItWorks } from '../../components/staffing/HowItWorks'
import { ScheduleActions, ScheduleDetail, useSchedule } from '../../components/staffing/Schedule'
import { Async, Card, Empty, Kpi } from '../../components/ui'
import { fmtDate, fmtFte, fmtRubShort, ORG_TYPE_LABELS, useApi } from '../../lib'

const PAGE = 100

/** Директору — сразу его штатка с должностями, без списка учреждений. */
function OwnSchedule({
  organizationId,
  year,
  version,
}: {
  organizationId: number
  year: string
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
          <ScheduleDetail data={data} onChanged={() => void reload({ silent: true })} />
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
  version,
  onOpen,
}: {
  meta: StaffingMeta
  year: string
  version: number
  onOpen: (id: number) => void
}) {
  if (meta.organization)
    return <OwnSchedule organizationId={meta.organization.id} year={year} version={version} />
  return <ScheduleTable meta={meta} year={year} version={version} onOpen={onOpen} />
}

type Sort = 'cut' | 'staffed' | 'payroll' | 'name'

function ScheduleTable({
  meta,
  year,
  version,
  onOpen,
}: {
  meta: StaffingMeta
  year: string
  version: number
  onOpen: (id: number) => void
}) {
  const [municipality, setMunicipality] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<Sort>('cut')
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
    const by: Record<Sort, (a: (typeof items)[0], b: (typeof items)[0]) => number> = {
      cut: (a, b) =>
        b.cut_cost - a.cut_cost ||
        b.cut + b.cut_vacant + b.reduce_load - (a.cut + a.cut_vacant + a.reduce_load),
      staffed: (a, b) => (a.staffed_pct ?? 101) - (b.staffed_pct ?? 101),
      payroll: (a, b) => (b.payroll_approved ?? 0) - (a.payroll_approved ?? 0),
      name: (a, b) => a.organization.localeCompare(b.organization),
    }
    return [...items].sort(by[sort])
  }, [state.data, search, sort])

  const details = meta.permissions.details

  return (
    <Async state={state}>
      {(data) => {
        const t = data.totals
        const noSchedule = data.items.filter((i) => !i.status).length
        const cut = data.items.reduce((s, i) => s + i.cut + i.cut_vacant + i.reduce_load, 0)
        const cutCost = data.items.reduce((s, i) => s + i.cut_cost, 0)
        return (
          <>
            <div className="kpis">
              <Kpi
                icon="doc"
                label="Ставок по штаткам"
                value={fmtFte(t.approved)}
                note={`${data.items.length - noSchedule} из ${data.items.length} учреждений со штаткой`}
              />
              <Kpi
                icon="users"
                label="Занято"
                value={fmtFte(t.occupied)}
                note={`вакантно ${fmtFte(t.vacant)} · на вакансии ${fmtRubShort(t.vacant_payroll)}/год`}
              />
              <Kpi
                icon="scale"
                label="ФОТ по штаткам"
                value={fmtRubShort(t.payroll_approved)}
                note="в год: оклад × ставки × 12"
              />
              <Kpi
                icon="cut"
                tone={cut ? 'warn' : 'good'}
                label="Высвободить"
                value={`${fmtFte(cut)} ст.`}
                note={cut ? `≈ ${fmtRubShort(cutCost)} в год` : 'лишних ставок нет'}
              />
            </div>

            <div className="toolbar">
              {meta.municipalities.length > 1 && (
                <select
                  value={municipality}
                  onChange={(e) => setMunicipality(e.target.value)}
                  aria-label="Территория"
                >
                  <option value="">Все муниципалитеты</option>
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
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as Sort)}
                aria-label="Сортировка"
              >
                <option value="cut">Сначала где больше высвободить</option>
                <option value="staffed">Сначала с вакансиями</option>
                <option value="payroll">По ФОТ</option>
                <option value="name">По названию</option>
              </select>
            </div>

            {shown.length === 0 ? (
              <Empty>Учреждений нет.</Empty>
            ) : (
              <Card>
                <table className="stack staffing-table">
                  <thead>
                    <tr>
                      <th>Учреждение</th>
                      <th className="num">По штатке</th>
                      <th className="num">Занято</th>
                      <th>Укомплектованность</th>
                      <th className="num">ФОТ в год</th>
                      <th className="num">Высвободить</th>
                    </tr>
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
                            {ORG_TYPE_LABELS[i.org_type]} · {i.positions} должн. · {i.status_title}
                            {i.last_change && ` · изменена ${fmtDate(i.last_change.created_at)}`}
                          </div>
                        </td>
                        <td data-label="По штатке" className="num">
                          {i.status ? fmtFte(i.approved) : '—'}
                        </td>
                        <td data-label="Занято" className="num">
                          {fmtFte(i.occupied)}
                          {i.vacant ? (
                            <div className="muted small-text">вакантно {fmtFte(i.vacant)}</div>
                          ) : null}
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
                        <td data-label="ФОТ в год" className="num">
                          {fmtRubShort(i.payroll_approved)}
                        </td>
                        <td data-label="Высвободить" className="num">
                          {i.cut + i.cut_vacant + i.reduce_load > 0 ? (
                            <>
                              <span className="dev-surplus">
                                {fmtFte(i.cut + i.cut_vacant + i.reduce_load)} ст.
                              </span>
                              <div className="muted small-text">{fmtRubShort(i.cut_cost)}/год</div>
                            </>
                          ) : i.hire > 0 ? (
                            <span className="dev-deficit">не хватает {fmtFte(i.hire)}</span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
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
            <HowItWorks>
              <p>
                Нажмите на учреждение — откроется его штатка по должностям: сколько ставок по
                штатке, сколько занято, вакансии, оклады и что можно высвободить с пояснением по
                каждой группе. Укомплектованность = занято ÷ по штатке. «Высвободить» — лишние
                вакансии, совмещение и занятые ставки по правилам из «Итога».
              </p>
            </HowItWorks>
          </>
        )
      }}
    </Async>
  )
}
