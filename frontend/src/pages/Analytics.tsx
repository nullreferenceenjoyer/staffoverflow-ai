import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Category, CentralFunction, Deviation, download } from '../api'
import { Async, Card, Delta, Empty, MunicipalitySelect, Page, Tabs } from '../components/ui'
import { CATEGORY_LABELS, fmt, fmtInt, fmtMoney, useApi } from '../lib'

type Tab = 'deviations' | 'duplicates' | 'inefficiency'

function Deviations({ municipality }: { municipality: number | null }) {
  const [category, setCategory] = useState<Category | ''>('')
  const state = useApi<Deviation[]>('/analytics/deviations', {
    municipality_id: municipality,
    category: category || null,
  })
  return (
    <Card
      title="Отклонения факта от норматива"
      aside={
        <div className="actions">
          <select value={category} onChange={(e) => setCategory(e.target.value as Category | '')}>
            <option value="">Все категории</option>
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <button
            onClick={() =>
              download('/analytics/deviations.csv', 'deviations.csv', {
                municipality_id: municipality,
              })
            }
          >
            Выгрузить CSV
          </button>
        </div>
      }
    >
      <Async state={state}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>Существенных отклонений нет.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Учреждение</th>
                  <th>Функция</th>
                  <th className="num">Факт</th>
                  <th className="num">Норматив</th>
                  <th className="num">Отклонение</th>
                  <th className="num">Влияние на ФОТ в год</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.organization_id}-${r.title}`} title={r.explanations.join('\n')}>
                    <td>
                      <Link to={`/organizations/${r.organization_id}`}>{r.organization}</Link>
                    </td>
                    <td>
                      {r.title} <span className="muted">· {CATEGORY_LABELS[r.category]}</span>
                    </td>
                    <td className="num">{fmt(r.actual)}</td>
                    <td className="num">{fmt(r.norm)}</td>
                    <td className="num">
                      <Delta value={r.delta} />
                    </td>
                    <td className="num">{fmtMoney(r.fot_effect_year)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Async>
    </Card>
  )
}

interface Duplicates {
  internal: {
    organization_id: number
    organization: string
    title: string
    departments: string[]
    rate: number
  }[]
  across_organizations: CentralFunction[]
}

function DuplicatesTab({ municipality }: { municipality: number | null }) {
  const state = useApi<Duplicates>('/analytics/duplicates', { municipality_id: municipality })
  return (
    <Async state={state}>
      {(data) => (
        <>
          <Card title="Одна функция в нескольких подразделениях учреждения">
            {data.internal.length === 0 ? (
              <Empty>Дублирования внутри учреждений не найдено.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Учреждение</th>
                    <th>Функция</th>
                    <th>Подразделения</th>
                    <th className="num">Ставок</th>
                  </tr>
                </thead>
                <tbody>
                  {data.internal.map((r) => (
                    <tr key={`${r.organization_id}-${r.title}`}>
                      <td>
                        <Link to={`/organizations/${r.organization_id}`}>{r.organization}</Link>
                      </td>
                      <td>{r.title}</td>
                      <td>{r.departments.join(', ')}</td>
                      <td className="num">{fmt(r.rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card
            title="Функции АУП, которые каждое учреждение ведёт само"
            aside={<Link to="/centralization">Сценарий централизации</Link>}
          >
            <table>
              <thead>
                <tr>
                  <th>Функция</th>
                  <th className="num">Учреждений</th>
                  <th className="num">Ставок сейчас</th>
                  <th className="num">По нормативу</th>
                  <th className="num">В общем центре</th>
                </tr>
              </thead>
              <tbody>
                {data.across_organizations.map((f) => (
                  <tr key={f.function_code}>
                    <td>{f.title}</td>
                    <td className="num">{f.organizations}</td>
                    <td className="num">{fmt(f.actual)}</td>
                    <td className="num">{fmt(f.norm)}</td>
                    <td className="num">{fmt(f.centralized)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </Async>
  )
}

interface Inefficiency {
  underloaded: {
    organization_id: number
    organization: string
    title: string
    rate: number
    weekly_hours: number
    expected_hours: number
  }[]
  vacancies: {
    organization_id: number
    organization: string
    title: string
    rate: number
    monthly_pay: number
  }[]
}

function InefficiencyTab({ municipality }: { municipality: number | null }) {
  const state = useApi<Inefficiency>('/analytics/inefficiency', { municipality_id: municipality })
  return (
    <Async state={state}>
      {(data) => (
        <div className="grid-2">
          <Card title="Недогруженные ставки">
            <p className="muted">Фактических часов меньше 80 % от нормы на занимаемую ставку.</p>
            {data.underloaded.length === 0 ? (
              <Empty>Нет данных о нагрузке или недогруза нет.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Учреждение</th>
                    <th>Должность</th>
                    <th className="num">Ставка</th>
                    <th className="num">Часов / норма</th>
                  </tr>
                </thead>
                <tbody>
                  {data.underloaded.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <Link to={`/organizations/${r.organization_id}`}>{r.organization}</Link>
                      </td>
                      <td>{r.title}</td>
                      <td className="num">{fmt(r.rate)}</td>
                      <td className="num">
                        {fmt(r.weekly_hours)} / {fmt(r.expected_hours)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Вакантные ставки">
            <p className="muted">Их можно сократить без высвобождения работников.</p>
            {data.vacancies.length === 0 ? (
              <Empty>Вакансий нет.</Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Учреждение</th>
                    <th>Функция</th>
                    <th className="num">Ставок</th>
                    <th className="num">ФОТ в месяц</th>
                  </tr>
                </thead>
                <tbody>
                  {data.vacancies.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <Link to={`/organizations/${r.organization_id}`}>{r.organization}</Link>
                      </td>
                      <td>{r.title}</td>
                      <td className="num">{fmt(r.rate)}</td>
                      <td className="num">{fmtInt(r.monthly_pay)} ₽</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </Async>
  )
}

export function Analytics() {
  const [tab, setTab] = useState<Tab>('deviations')
  const [municipality, setMunicipality] = useState<number | null>(null)
  return (
    <Page
      title="Отклонения"
      hint="Где фактический штат расходится с нормативом и где ставки используются неэффективно"
      actions={<MunicipalitySelect value={municipality} onChange={setMunicipality} />}
    >
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          ['deviations', 'От нормативов'],
          ['duplicates', 'Дублирование функций'],
          ['inefficiency', 'Использование ставок'],
        ]}
      />
      {tab === 'deviations' && <Deviations municipality={municipality} />}
      {tab === 'duplicates' && <DuplicatesTab municipality={municipality} />}
      {tab === 'inefficiency' && <InefficiencyTab municipality={municipality} />}
    </Page>
  )
}
