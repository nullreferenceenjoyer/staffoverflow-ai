import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Dashboard } from '../api'
import { Async, Card, Delta, Kpi, MunicipalitySelect, Page } from '../components/ui'
import { CATEGORY_SHORT, fmt, fmtInt, fmtMoney, PROJECT_STATUS, useApi } from '../lib'

const INTRO_KEY = 'hr-edu-intro-hidden'

const STEPS = [
  ['1. Данные', 'Загрузите контингент, здания и штатные расписания учреждений.', '/organizations'],
  ['2. Норматив', 'Система посчитает, сколько ставок положено по нормативам.', '/norms'],
  ['3. Отклонения', 'Посмотрите, где ставок больше или меньше нормы и почему.', '/analytics'],
  ['4. Решение', 'Сформируйте проект изменений, документы и задачи.', '/projects'],
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
      <p>
        Система сравнивает фактические штатные расписания с расчётными нормативами и помогает
        подготовить решение: что сократить, что добавить и какие функции выгоднее объединить.
      </p>
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
      hint="Сводные показатели по доступным вам учреждениям"
      actions={<MunicipalitySelect value={municipality} onChange={setMunicipality} />}
    >
      <Intro />
      <Async state={state}>
        {(d) => (
          <>
            <div className="kpis">
              <Kpi
                label="Численность персонала"
                value={`${fmt(d.actual_total)} ст.`}
                note={`${d.organizations} учреждений, ${fmtInt(d.students)} обучающихся`}
              />
              <Kpi
                label="Соответствие нормативам"
                value={`${fmt(d.compliance)} %`}
                note={`норматив ${fmt(d.norm_total)} ст.`}
              />
              <Kpi
                label="Избыток / нехватка"
                value={`${fmt(d.surplus)} / ${fmt(d.shortage)} ст.`}
                note="сумма отклонений по функциям"
              />
              <Kpi
                label="Потенциал экономии ФОТ"
                value={fmtMoney(d.saving_potential_year)}
                note={`в год, при ФОТ ${fmtMoney(d.fot_actual_year)}`}
              />
            </div>

            <div className="grid-2">
              <Card title="Факт и норматив по категориям, ставок">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={d.categories.map((c) => ({ ...c, name: CATEGORY_SHORT[c.key] }))}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(v: number) => fmt(v)} />
                    <Legend />
                    <Bar
                      isAnimationActive={false}
                      dataKey="actual"
                      name="Факт"
                      fill="#3b6fd4"
                      radius={[3, 3, 0, 0]}
                    />
                    <Bar
                      isAnimationActive={false}
                      dataKey="norm"
                      name="Норматив"
                      fill="#a9b8d6"
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              <Card
                title="Эффект централизации АУП и ВП"
                aside={<Link to="/centralization">Подробнее</Link>}
              >
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={d.centralization.stages.map((s) => ({
                      ...s,
                      name: CATEGORY_SHORT[s.category],
                    }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} />
                    <Tooltip formatter={(v: number) => fmt(v)} />
                    <Legend />
                    <Bar
                      isAnimationActive={false}
                      dataKey="actual"
                      name="Сейчас"
                      fill="#3b6fd4"
                      radius={[3, 3, 0, 0]}
                    />
                    <Bar
                      isAnimationActive={false}
                      dataKey="norm"
                      name="По нормативу"
                      fill="#a9b8d6"
                      radius={[3, 3, 0, 0]}
                    />
                    <Bar
                      isAnimationActive={false}
                      dataKey="centralized"
                      name="После централизации"
                      fill="#2f9e83"
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
                <p className="muted">
                  Высвобождается {fmt(d.centralization.released_total)} ст., экономия до{' '}
                  {fmtMoney(d.centralization.saving_year)} в год.
                </p>
              </Card>
            </div>

            <div className="grid-2">
              <Card title="Учреждения с наибольшим потенциалом экономии">
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
                <Card title="Проекты оптимизации" aside={<Link to="/projects">Все проекты</Link>}>
                  {Object.keys(d.projects_by_status).length ? (
                    <div className="chips">
                      {Object.entries(d.projects_by_status).map(([status, count]) => (
                        <span key={status} className="chip">
                          {PROJECT_STATUS[status]?.label ?? status}: <strong>{count}</strong>
                        </span>
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
