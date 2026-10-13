import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Dashboard } from '../api'
import { FindingRow, StatusBar } from '../components/blocks'
import { AXIS, BAR, ChartTip, Legend, Meter, MUTED, SERIES } from '../components/charts'
import { Icon } from '../components/icons'
import { Async, Badge, Card, Counter, Delta, Kpi, MunicipalitySelect, Page } from '../components/ui'
import {
  CATEGORY_SHORT,
  fmt,
  fmtDay,
  fmtHours,
  fmtInt,
  fmtMoney,
  PROJECT_STATUS,
  useApi,
} from '../lib'

const INTRO_KEY = 'hr-edu-intro-hidden'

const STEPS = [
  ['1. Данные', 'Штатные расписания, контингент и здания из РГИС.', '/organizations'],
  ['2. Загрузка', 'Где персонала больше, чем работы, и почему.', '/workload'],
  ['3. Решение', 'Проект изменений, документы и задачи со сроками.', '/projects'],
  ['4. Заявки', 'Текущая работа хозяйственных служб и её сроки.', '/requests'],
] as const

/** Короткое объяснение для тех, кто открыл систему впервые. Скрывается одним кликом. */
function Intro() {
  const [hidden, setHidden] = useState(localStorage.getItem(INTRO_KEY) === '1')
  if (hidden) return null
  return (
    <section className="intro">
      <div className="card-head">
        <h2>Как работать с системой</h2>
        <button
          className="ghost"
          onClick={() => {
            localStorage.setItem(INTRO_KEY, '1')
            setHidden(true)
          }}
        >
          Скрыть
        </button>
      </div>
      <div className="steps">
        {STEPS.map(([title, text, to]) => (
          <Link key={to} to={to} className="step">
            <strong>{title}</strong>
            <span>{text}</span>
          </Link>
        ))}
      </div>
    </section>
  )
}

export function DashboardPage() {
  const [municipality, setMunicipality] = useState<number | null>(null)
  const state = useApi<Dashboard>('/dashboard', { municipality_id: municipality })

  return (
    <Page
      title="Обзор"
      hint="Загрузка АУП и вспомогательного персонала, заявки и ход проектов по доступным вам учреждениям"
      actions={<MunicipalitySelect value={municipality} onChange={setMunicipality} />}
    >
      <Intro />
      <Async state={state}>
        {(d) => (
          <>
            <div className="kpis">
              <Kpi
                icon="gauge"
                tone={(d.workload.load_pct ?? 100) < 85 ? 'warn' : 'good'}
                label="Загрузка АУП и ВП"
                value={
                  <Counter value={d.workload.load_pct ?? 0} format={(v) => `${fmtInt(v)} %`} />
                }
                note={`${fmt(d.workload.volume)} ст. работы на ${fmt(d.workload.actual)} занятых`}
              />
              <Kpi
                icon="users"
                label="Можно сократить"
                value={
                  <Counter
                    value={d.workload.excess}
                    format={(v) => `${fmt(Math.round(v * 4) / 4)} ст.`}
                  />
                }
                note={`из них вакансии — ${fmt(d.workload.vacant_in_excess)} ст., площадок: ${d.workload.flagged_sites}`}
              />
              <Kpi
                icon="wallet"
                tone="good"
                label="Экономия ФОТ в год"
                value={<Counter value={d.workload.saving_year} format={fmtMoney} />}
                note={`при ФОТ ${fmtMoney(d.fot_actual_year)}`}
              />
              <Kpi
                icon="inbox"
                tone={d.requests.overdue ? 'critical' : undefined}
                label="Заявки в работе"
                value={<Counter value={d.requests.active} format={fmtInt} />}
                note={
                  d.requests.overdue ? (
                    <Link to="/requests">просрочено: {d.requests.overdue}</Link>
                  ) : (
                    'просроченных нет'
                  )
                }
              />
            </div>

            <div className="grid-wide">
              <Card
                title="Что предлагает система"
                aside={
                  <Link to="/workload">
                    Все площадки <Icon name="arrow" size={14} />
                  </Link>
                }
              >
                {d.workload.findings.length ? (
                  d.workload.findings.map((f) => (
                    <FindingRow
                      key={`${f.site_id}-${f.function_code}-${f.organization}`}
                      finding={f}
                    />
                  ))
                ) : (
                  <p className="muted">Недозагруженного персонала не найдено.</p>
                )}
              </Card>

              <Card title="Загрузка по функциям">
                <p className="card-sub">Объём работы к занятым ставкам. Черта — 100 %.</p>
                {d.workload.by_function.map((f) => (
                  <Meter
                    key={f.function_code}
                    label={f.title}
                    value={f.load_pct}
                    max={125}
                    mark={100}
                    low={(f.load_pct ?? 100) < 85}
                    title={`${f.title}: занято ${fmt(f.actual)} ст., работы на ${fmt(f.volume)} ст.`}
                  />
                ))}
              </Card>
            </div>

            <div className="grid-2">
              <Card title="Заявки за 30 дней" aside={<Link to="/requests">К заявкам</Link>}>
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={d.requests.flow.map((p) => ({ ...p, name: fmtDay(p.date) }))}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="name" {...AXIS} minTickGap={28} />
                    <YAxis {...AXIS} allowDecimals={false} width={28} />
                    <Tooltip content={<ChartTip format={fmtInt} />} />
                    <Area
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="created"
                      name="Создано"
                      stroke={SERIES[0]}
                      strokeWidth={2}
                      fill={SERIES[0]}
                      fillOpacity={0.12}
                    />
                    <Area
                      isAnimationActive={false}
                      type="monotone"
                      dataKey="closed"
                      name="Выполнено"
                      stroke={SERIES[2]}
                      strokeWidth={2}
                      fill={SERIES[2]}
                      fillOpacity={0.12}
                    />
                  </AreaChart>
                </ResponsiveContainer>
                <Legend
                  items={[
                    ['Создано', SERIES[0]],
                    ['Выполнено', SERIES[2]],
                  ]}
                />
                <p className="muted">
                  Среднее время выполнения — {fmtHours(d.requests.avg_hours)}, в срок —{' '}
                  {d.requests.in_time_pct ?? '—'} %. Ждут подтверждения заявителя:{' '}
                  {d.requests.waiting_confirmation}, без исполнителя: {d.requests.unassigned}.
                </p>
                <StatusBar items={d.requests.by_status} />
              </Card>

              <Card title="Факт и норматив по категориям, ставок">
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart
                    data={d.categories.map((c) => ({ ...c, name: CATEGORY_SHORT[c.key] }))}
                    barGap={2}
                  >
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="name" {...AXIS} />
                    <YAxis {...AXIS} width={44} />
                    <Tooltip content={<ChartTip />} />
                    <Bar
                      isAnimationActive={false}
                      dataKey="actual"
                      name="Факт"
                      fill={SERIES[0]}
                      {...BAR}
                    />
                    <Bar
                      isAnimationActive={false}
                      dataKey="norm"
                      name="Норматив"
                      fill={MUTED}
                      {...BAR}
                    />
                  </BarChart>
                </ResponsiveContainer>
                <Legend
                  items={[
                    ['Факт', SERIES[0]],
                    ['Норматив', MUTED],
                  ]}
                />
                <p className="muted">
                  Всего {fmt(d.actual_total)} ст. при нормативе {fmt(d.norm_total)} ст.,
                  соответствие {fmt(d.compliance)} %. {d.organizations} учреждений,{' '}
                  {fmtInt(d.students)} обучающихся.
                </p>
              </Card>
            </div>

            <div className="grid-2">
              <Card
                title="Учреждения с наибольшим потенциалом экономии"
                aside={<Link to="/organizations">Все учреждения</Link>}
              >
                <table>
                  <thead>
                    <tr>
                      <th>Учреждение</th>
                      <th className="num">Факт</th>
                      <th className="num">Норматив</th>
                      <th className="num">Экономия в год</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.top_organizations.map((o) => (
                      <tr key={o.id}>
                        <td>
                          <Link to={`/organizations/${o.id}`}>{o.name}</Link>
                        </td>
                        <td className="num">{fmt(o.actual)}</td>
                        <td className="num">{fmt(o.norm)}</td>
                        <td className="num">{fmtMoney(o.saving_potential_year)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>

              <div>
                <Card
                  title="Проекты и централизация"
                  aside={<Link to="/projects">Все проекты</Link>}
                >
                  {Object.keys(d.projects_by_status).length ? (
                    <div className="chips">
                      {Object.entries(d.projects_by_status).map(([status, count]) => (
                        <Badge key={status} tone={PROJECT_STATUS[status]?.tone}>
                          {PROJECT_STATUS[status]?.label ?? status}: {count}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Проектов пока нет.</p>
                  )}
                  {d.overdue_tasks ? (
                    <p className="delta-minus">
                      Просроченных задач: {d.overdue_tasks}. <Link to="/workflow">Открыть</Link>
                    </p>
                  ) : null}
                  <p className="muted">
                    Сценарий <Link to="/centralization">централизации</Link> высвобождает{' '}
                    {fmt(d.centralization.released_total)} ст. — до{' '}
                    {fmtMoney(d.centralization.saving_year)} в год.
                  </p>
                </Card>

                {d.municipalities.length > 1 && (
                  <Card title="По муниципалитетам">
                    <table>
                      <thead>
                        <tr>
                          <th>Муниципалитет</th>
                          <th className="num">ОУ</th>
                          <th className="num">Факт</th>
                          <th className="num">Отклонение</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.municipalities.map((m) => (
                          <tr key={m.id}>
                            <td>{m.name}</td>
                            <td className="num">{m.organizations}</td>
                            <td className="num">{fmt(m.actual)}</td>
                            <td className="num">
                              <Delta value={m.actual - m.norm} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                )}
              </div>
            </div>
          </>
        )}
      </Async>
    </Page>
  )
}
