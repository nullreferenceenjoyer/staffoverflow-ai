import { useEffect, useRef, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import {
  DashboardGroup,
  StaffBasis,
  StaffCategory,
  StaffingDashboard,
  StaffingMeta,
  StaffingStatus,
} from '../../api'
import { AXIS, Legend, SERIES } from '../../components/charts'
import { StatusBadge } from '../../components/staffing/parts'
import { MoneyDelta } from '../../components/staffing/Schedule'
import { Async, Card, Empty, Kpi, Segmented } from '../../components/ui'
import {
  fmt,
  fmtDate,
  fmtDeviation,
  fmtFte,
  fmtInt,
  fmtRub,
  fmtRubShort,
  STAFFING_STATUS,
  useApi,
} from '../../lib'

const ORDER: StaffingStatus[] = ['deficit', 'surplus', 'warning', 'no_data', 'normal']
const CATEGORY_TITLE: Record<StaffCategory, string> = { aup: 'АУП', support: 'Вспомогательный' }
const DEFICIT = 'var(--critical)'
const SURPLUS = 'var(--serious)'

/** Из скольких учреждений складывается каждый статус — одна полоса на категорию. */
function StatusBars({ data }: { data: StaffingDashboard }) {
  return (
    <>
      {(['aup', 'support'] as StaffCategory[]).map((category) => {
        const counts = data.status[category]
        const total = ORDER.reduce((sum, s) => sum + counts[s], 0) || 1
        return (
          <div key={category} className="status-stack">
            <div className="status-stack-head">
              <strong>{CATEGORY_TITLE[category]}</strong>
              <span className="muted">
                в норме {counts.normal} из {total}
              </span>
            </div>
            <div
              className="status-stack-bar"
              role="img"
              aria-label={`Статусы: ${CATEGORY_TITLE[category]}`}
            >
              {ORDER.filter((s) => counts[s]).map((s) => (
                <i
                  key={s}
                  style={{
                    width: `${(counts[s] / total) * 100}%`,
                    background: STAFFING_STATUS[s].color,
                  }}
                  title={`${STAFFING_STATUS[s].label}: ${counts[s]}`}
                >
                  {counts[s] / total > 0.08 && <span>{counts[s]}</span>}
                </i>
              ))}
            </div>
          </div>
        )
      })}
      <Legend items={ORDER.map((s) => [STAFFING_STATUS[s].label, STAFFING_STATUS[s].color])} />
    </>
  )
}

interface GroupTipProps {
  active?: boolean
  payload?: { payload: DashboardGroup }[]
}

function GroupTip({ active, payload }: GroupTipProps) {
  const g = payload?.[0]?.payload
  if (!active || !g) return null
  return (
    <div className="chart-tip">
      <b>{g.group}</b>
      <div>
        <span className="swatch" style={{ background: DEFICIT }} />
        <span>Не хватает</span>
        <span>
          {fmtFte(g.deficit)} ст. · {fmtRubShort(g.deficit_cost)}/год
        </span>
      </div>
      <div>
        <span className="swatch" style={{ background: SURPLUS }} />
        <span>Сверх норматива</span>
        <span>
          {fmtFte(g.surplus)} ст. · {fmtRubShort(g.surplus_cost)}/год
        </span>
      </div>
      <div>
        <span />
        <span>Норматив / факт</span>
        <span>
          {fmtFte(g.required)} / {fmtFte(g.fact)}
        </span>
      </div>
    </div>
  )
}

/** Дефицит влево от нуля, излишек вправо — сразу видно, каких групп не хватает. */
function DeviationChart({ groups }: { groups: DashboardGroup[] }) {
  const [unit, setUnit] = useState<'fte' | 'rub'>('fte')
  const rows = groups
    .filter((g) => g.deficit || g.surplus)
    .map((g) => ({
      ...g,
      minus: -(unit === 'fte' ? g.deficit : g.deficit_cost),
      plus: unit === 'fte' ? g.surplus : g.surplus_cost,
    }))
  if (!rows.length) return <Empty>Отклонений от норматива нет.</Empty>
  const format = (v: number) => (unit === 'fte' ? fmt(Math.abs(v)) : fmtRubShort(Math.abs(v)))
  return (
    <>
      <div className="toolbar">
        <Segmented
          label="Единицы"
          options={[
            ['fte', 'Ставки'],
            ['rub', 'Рубли в год'],
          ]}
          value={unit}
          onChange={setUnit}
        />
      </div>
      <div className="hbars">
        <ResponsiveContainer width="100%" height={Math.max(rows.length * 34 + 40, 160)}>
          <BarChart data={rows} layout="vertical" stackOffset="sign" barCategoryGap={8}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" {...AXIS} tickFormatter={format} />
            <YAxis type="category" dataKey="group" {...AXIS} width={190} interval={0} />
            <ReferenceLine x={0} stroke="var(--border-strong)" />
            <Tooltip content={<GroupTip />} cursor={{ fill: 'var(--surface-3)' }} />
            <Bar
              dataKey="minus"
              name="Не хватает"
              stackId="dev"
              fill={DEFICIT}
              radius={[4, 0, 0, 4]}
              isAnimationActive={false}
            />
            <Bar
              dataKey="plus"
              name="Сверх норматива"
              stackId="dev"
              fill={SURPLUS}
              radius={[0, 4, 4, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Legend
        items={[
          ['Не хватает ставок', DEFICIT],
          ['Сверх норматива', SURPLUS],
        ]}
      />
    </>
  )
}

function PayrollChart({ groups }: { groups: DashboardGroup[] }) {
  const rows = [...groups].filter((g) => g.payroll).sort((a, b) => b.payroll - a.payroll)
  if (!rows.length) return <Empty>Окладов в штатках пока нет.</Empty>
  const total = rows.reduce((sum, g) => sum + g.payroll, 0)
  return (
    <div className="hbars">
      <ResponsiveContainer width="100%" height={rows.length * 30 + 30}>
        <BarChart data={rows} layout="vertical" barCategoryGap={6} margin={{ right: 80 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="group" {...AXIS} width={190} interval={0} />
          <Tooltip
            cursor={{ fill: 'var(--surface-3)' }}
            content={({ active, payload }) => {
              const g = payload?.[0]?.payload as DashboardGroup | undefined
              if (!active || !g) return null
              return (
                <div className="chart-tip">
                  <b>{g.group}</b>
                  <div>
                    <span className="swatch" style={{ background: SERIES[0] }} />
                    <span>ФОТ в год</span>
                    <span>{fmtRub(g.payroll)}</span>
                  </div>
                  <div>
                    <span />
                    <span>Доля</span>
                    <span>{Math.round((g.payroll / total) * 100)} %</span>
                  </div>
                </div>
              )
            }}
          />
          <Bar dataKey="payroll" fill={SERIES[0]} radius={[0, 4, 4, 0]} isAnimationActive={false}>
            <LabelList
              dataKey="payroll"
              content={({ x, y, width, height, value }) => (
                <text
                  x={Number(x) + Number(width) + 6}
                  y={Number(y) + Number(height) / 2}
                  dominantBaseline="central"
                  className="bar-label"
                >
                  {fmtRubShort(Number(value))}
                </text>
              )}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Dashboard({
  meta,
  year,
  basis,
  version,
  onOpenAnalysis,
  onOpenSchedule,
}: {
  meta: StaffingMeta
  year: string
  basis: StaffBasis
  version: number
  onOpenAnalysis: (id: number) => void
  onOpenSchedule: (id: number) => void
}) {
  const [municipality, setMunicipality] = useState('')
  const state = useApi<StaffingDashboard>('/staffing/dashboard', {
    year,
    basis,
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
  const details = meta.permissions.details
  const single = meta.organization !== null

  return (
    <>
      {meta.municipalities.length > 1 && (
        <div className="toolbar">
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
        </div>
      )}
      <Async state={state}>
        {(d) => {
          const k = d.kpi
          return (
            <>
              <div className="kpis">
                <Kpi
                  icon="alert"
                  tone={k.deficit_fte ? 'critical' : 'good'}
                  label="Не хватает ставок"
                  value={fmtFte(k.deficit_fte)}
                  note={
                    k.deficit_fte
                      ? `закрыть дефицит — ${k.cost_estimated ? '≈ ' : ''}${fmtRubShort(k.deficit_cost)}/год`
                      : 'дефицита нет'
                  }
                />
                <Kpi
                  icon="scale"
                  tone={k.surplus_fte ? 'warn' : 'good'}
                  label="Сверх норматива"
                  value={fmtFte(k.surplus_fte)}
                  note={
                    k.surplus_fte ? `в ФОТ — ${fmtRubShort(k.surplus_cost)}/год` : 'излишков нет'
                  }
                />
                <Kpi
                  icon="doc"
                  label="ФОТ по штатке"
                  value={fmtRubShort(k.payroll_approved)}
                  note={`в год · занятые ${fmtRubShort(k.payroll_occupied)}, вакансии ${fmtRubShort(k.vacant_payroll)}`}
                />
                {single ? (
                  <Kpi
                    icon="users"
                    label="Занято ставок"
                    value={fmtFte(k.occupied)}
                    note={`из ${fmtFte(k.approved)} по штатке, вакантно ${fmtFte(k.vacant)}`}
                  />
                ) : (
                  <Kpi
                    icon="building"
                    tone={k.problems ? 'warn' : 'good'}
                    label="Учреждений с отклонениями"
                    value={`${fmtInt(k.problems)} из ${fmtInt(d.organizations)}`}
                    note={`нет данных — ${k.no_data}, в норме — ${k.normal}`}
                  />
                )}
              </div>

              <div className="grid-2">
                <Card title="Где не хватает и где сверх норматива">
                  <p className="card-sub">
                    Сумма по группам должностей{single ? '' : ' по всем учреждениям'},{' '}
                    {basis === 'occupied' ? 'по занятым ставкам' : 'по утверждённой штатке'}.
                  </p>
                  <DeviationChart groups={d.by_group} />
                </Card>
                <div className="stack-cards">
                  <Card title={single ? 'Итог по категориям' : 'Статусы учреждений'}>
                    {single ? (
                      <div className="chips">
                        {(['aup', 'support'] as StaffCategory[]).map((c) => {
                          const status = ORDER.find((s) => d.status[c][s]) ?? 'no_data'
                          return (
                            <span key={c} className="chips">
                              <strong>{CATEGORY_TITLE[c]}</strong> <StatusBadge status={status} />
                            </span>
                          )
                        })}
                      </div>
                    ) : (
                      <StatusBars data={d} />
                    )}
                  </Card>
                  <Card title="ФОТ по группам">
                    <p className="card-sub">Оклад × ставки по штатке × 12, в год.</p>
                    <PayrollChart groups={d.by_group} />
                  </Card>
                </div>
              </div>

              {d.by_municipality.length > 1 && (
                <Card title="По муниципалитетам">
                  <table className="stack staffing-table">
                    <thead>
                      <tr>
                        <th>Муниципалитет</th>
                        <th className="num">Учреждений</th>
                        <th className="num">С отклонениями</th>
                        <th className="num">Нет данных</th>
                        <th className="num">Не хватает</th>
                        <th className="num">Сверх нормы</th>
                        <th className="num">Закрыть дефицит</th>
                        <th className="num">ФОТ в год</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.by_municipality.map((m) => (
                        <tr
                          key={m.municipality_id}
                          className="clickable"
                          onClick={() => setMunicipality(String(m.municipality_id))}
                        >
                          <td data-label="Муниципалитет">
                            <strong>{m.municipality}</strong>
                          </td>
                          <td data-label="Учреждений" className="num">
                            {m.organizations}
                          </td>
                          <td data-label="С отклонениями" className="num">
                            {m.problems}
                          </td>
                          <td data-label="Нет данных" className="num">
                            {m.no_data}
                          </td>
                          <td data-label="Не хватает" className="num dev-deficit">
                            {fmtFte(m.deficit)}
                          </td>
                          <td data-label="Сверх нормы" className="num dev-surplus">
                            {fmtFte(m.surplus)}
                          </td>
                          <td data-label="Закрыть дефицит" className="num">
                            {fmtRubShort(m.deficit_cost)}
                          </td>
                          <td data-label="ФОТ в год" className="num">
                            {fmtRubShort(m.payroll)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}

              <div className="grid-2">
                {!single && (
                  <Card title="Самые большие отклонения">
                    <p className="card-sub">По цене отклонения в год.</p>
                    {d.top.length === 0 ? (
                      <Empty>Отклонений нет.</Empty>
                    ) : (
                      <ul className="rank-list">
                        {d.top.map((t) => (
                          <li key={t.organization_id}>
                            <button
                              className="rank-item"
                              disabled={!details}
                              onClick={() => onOpenAnalysis(t.organization_id)}
                            >
                              <span>
                                <strong>{t.organization}</strong>
                                <span className="muted">{t.municipality}</span>
                              </span>
                              <span className="num">
                                {t.deficit > 0 && (
                                  <span className="dev-deficit">−{fmtFte(t.deficit)} ст. </span>
                                )}
                                {t.surplus > 0 && (
                                  <span className="dev-surplus">+{fmtFte(t.surplus)} ст.</span>
                                )}
                                <span className="muted">
                                  {fmtRubShort(t.deficit_cost + t.surplus_cost)}/год
                                </span>
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Card>
                )}
                <Card title="Изменения штаток">
                  <p className="card-sub">Что меняли в этом году и как это сдвинуло ФОТ.</p>
                  {d.changes.length === 0 ? (
                    <Empty>Штатки в этом году не менялись.</Empty>
                  ) : (
                    <ul className="rank-list">
                      {d.changes.map((c) => (
                        <li key={c.id}>
                          <button
                            className="rank-item"
                            disabled={!details}
                            onClick={() => onOpenSchedule(c.organization_id)}
                          >
                            <span>
                              <strong>{single ? fmtDate(c.created_at) : c.organization}</strong>
                              <span className="muted">
                                {single ? '' : `${fmtDate(c.created_at)} · `}
                                {c.changes
                                  .map((x) => `${x.group} ${fmtDeviation(x.approved_delta)}`)
                                  .join(', ')}
                              </span>
                              {c.comment && <span className="muted small-text">{c.comment}</span>}
                            </span>
                            <span className="num">
                              <MoneyDelta value={c.payroll_delta} />
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            </>
          )
        }}
      </Async>
    </>
  )
}
