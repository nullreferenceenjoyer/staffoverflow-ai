import { Fragment, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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

import { api, Municipality, Project, Scenario } from '../api'
import { useUser } from '../App'
import { ActionButton, Async, Card, Kpi, MunicipalitySelect, Page } from '../components/ui'
import { canPlan, CATEGORY_LABELS, fmt, fmtMoney, useApi } from '../lib'

export function Centralization() {
  const user = useUser()
  const navigate = useNavigate()
  const municipalities = useApi<Municipality[]>('/municipalities')
  const [municipality, setMunicipality] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  // Централизация имеет смысл в границах одного муниципалитета, поэтому «все» не предлагаем
  useEffect(() => {
    if (municipality === null && municipalities.data?.length) {
      setMunicipality(municipalities.data[0].id)
    }
  }, [municipalities.data, municipality])

  const state = useApi<Scenario>(municipality ? '/analytics/centralization' : null, {
    municipality_id: municipality,
  })

  async function createProject() {
    const project = await api<Project>('/projects/generate', {
      body: { kind: 'centralization', municipality_id: municipality },
    })
    navigate(`/projects/${project.id}`)
  }

  return (
    <Page
      title="Централизация АУП и вспомогательного персонала"
      hint="Что будет, если бухгалтерию, кадры, уборку и охрану вести не в каждом учреждении, а общими центрами и бригадами"
      actions={
        <>
          <MunicipalitySelect value={municipality} onChange={setMunicipality} allLabel={null} />
          {canPlan(user) && (
            <ActionButton className="primary" onClick={createProject}>
              Сформировать проект
            </ActionButton>
          )}
        </>
      }
    >
      <Async state={state}>
        {(s) => (
          <>
            <div className="kpis">
              <Kpi label="Учреждений в периметре" value={String(s.organizations)} />
              <Kpi
                label="Высвобождается"
                value={`${fmt(s.released_total)} ст.`}
                note="относительно факта"
              />
              <Kpi
                label="Экономия ФОТ"
                value={fmtMoney(s.saving_year)}
                note="в год, с начислениями"
              />
            </div>

            <Card title="Численность АУП и ВП при переходе на новую модель, ставок">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={[
                    { name: 'Сейчас', ...stageValues(s, 'actual') },
                    { name: 'По нормативу в каждом ОУ', ...stageValues(s, 'norm') },
                    { name: 'Общие центры и бригады', ...stageValues(s, 'centralized') },
                  ]}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip formatter={(v: number) => fmt(v)} />
                  <Legend />
                  <Bar
                    isAnimationActive={false}
                    dataKey="admin"
                    name={CATEGORY_LABELS.admin}
                    stackId="a"
                    fill="#8a5cd0"
                  />
                  <Bar
                    isAnimationActive={false}
                    dataKey="support"
                    name={CATEGORY_LABELS.support}
                    stackId="a"
                    fill="#d9892b"
                    radius={[3, 3, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card title="Функции, которые можно объединить">
              <table>
                <thead>
                  <tr>
                    <th>Функция</th>
                    <th>Куда передаётся</th>
                    <th className="num">ОУ</th>
                    <th className="num">Сейчас</th>
                    <th className="num">Норматив</th>
                    <th className="num">В центре</th>
                    <th className="num">Высвобождается</th>
                    <th className="num">Экономия в год</th>
                  </tr>
                </thead>
                <tbody>
                  {s.functions.map((f) => (
                    <Fragment key={f.function_code}>
                      <tr
                        className="clickable"
                        onClick={() =>
                          setExpanded(expanded === f.function_code ? null : f.function_code)
                        }
                      >
                        <td>{f.title}</td>
                        <td>{f.center}</td>
                        <td className="num">{f.organizations}</td>
                        <td className="num">{fmt(f.actual)}</td>
                        <td className="num">{fmt(f.norm)}</td>
                        <td className="num">{fmt(f.centralized)}</td>
                        <td className="num">{fmt(f.released)}</td>
                        <td className="num">{fmtMoney(f.saving_year)}</td>
                      </tr>
                      {expanded === f.function_code && (
                        <tr className="explain">
                          <td colSpan={8}>
                            {f.members.map((m) => (
                              <div key={m.organization_id}>
                                {m.organization}: факт {fmt(m.actual)} ст., норматив {fmt(m.norm)}{' '}
                                ст.
                              </div>
                            ))}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
              <p className="muted">
                Нажмите на строку, чтобы увидеть учреждения. Расчёт — основа для обсуждения:
                транспортную доступность и режим работы зданий он не учитывает.
              </p>
            </Card>
          </>
        )}
      </Async>
    </Page>
  )
}

function stageValues(scenario: Scenario, key: 'actual' | 'norm' | 'centralized') {
  return Object.fromEntries(scenario.stages.map((stage) => [stage.category, stage[key]]))
}
