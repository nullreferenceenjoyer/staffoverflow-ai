import { Fragment, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api, OrgDetails, Position, Project } from '../api'
import { useUser } from '../App'
import {
  ActionButton,
  Async,
  Badge,
  Card,
  Delta,
  Empty,
  Field,
  Form,
  Kpi,
  Modal,
  Page,
  Tabs,
} from '../components/ui'
import {
  canEdit,
  canPlan,
  CATEGORY_LABELS,
  fmt,
  fmtInt,
  fmtMoney,
  FORM_LABELS,
  LEVEL_LABELS,
  ORG_TYPE_LABELS,
  useApi,
} from '../lib'

type Tab = 'compare' | 'positions' | 'data' | 'forecast'

function Comparison({ org }: { org: OrgDetails }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <>
      <Card title="Факт и норматив по функциям">
        <table>
          <thead>
            <tr>
              <th>Функция</th>
              <th>Категория</th>
              <th className="num">Факт, ст.</th>
              <th className="num">из них вакансии</th>
              <th className="num">Норматив, ст.</th>
              <th className="num">Отклонение</th>
            </tr>
          </thead>
          <tbody>
            {org.lines.map((line) => (
              <Fragment key={line.function_code}>
                <tr
                  className={line.explanations.length ? 'clickable' : undefined}
                  onClick={() =>
                    setExpanded(expanded === line.function_code ? null : line.function_code)
                  }
                >
                  <td>{line.title}</td>
                  <td>{CATEGORY_LABELS[line.category]}</td>
                  <td className="num">{fmt(line.actual_rate)}</td>
                  <td className="num">{line.vacant_rate ? fmt(line.vacant_rate) : ''}</td>
                  <td className="num">
                    {line.has_norm ? fmt(line.norm_rate) : <span className="muted">нет нормы</span>}
                  </td>
                  <td className="num">{line.has_norm && <Delta value={line.delta} />}</td>
                </tr>
                {expanded === line.function_code && line.explanations.length > 0 && (
                  <tr className="explain">
                    <td colSpan={6}>
                      {line.explanations.map((text) => (
                        <div key={text}>{text}</div>
                      ))}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        <p className="muted">Нажмите на строку, чтобы увидеть формулу расчёта норматива.</p>
      </Card>

      {org.allowances.length > 0 && (
        <Card title="Расчётные надбавки, ₽ в месяц">
          <table>
            <tbody>
              {org.allowances.map((a) => (
                <tr key={a.title}>
                  <td>{a.title}</td>
                  <td className="num">{fmtInt(a.value)} ₽</td>
                  <td className="muted">{a.legal_ref ?? 'допущение'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}

function Positions({
  orgId,
  editable,
  onChange,
}: {
  orgId: number
  editable: boolean
  onChange: () => void
}) {
  const state = useApi<Position[]>(`/organizations/${orgId}/positions`)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({
    title: '',
    department: '',
    rate: '1',
    monthly_pay: '0',
    is_vacant: false,
  })

  async function add() {
    await api(`/organizations/${orgId}/positions`, {
      body: { ...draft, department: draft.department || null },
    })
    setAdding(false)
    await state.reload()
    onChange()
  }

  async function remove(id: number) {
    await api(`/positions/${id}`, { method: 'DELETE' })
    await state.reload()
    onChange()
  }

  return (
    <Card
      title="Штатное расписание"
      aside={editable && <button onClick={() => setAdding(true)}>Добавить строку</button>}
    >
      <Async state={state}>
        {(positions) =>
          positions.length === 0 ? (
            <Empty>
              Штатное расписание не загружено. Воспользуйтесь импортом в списке учреждений.
            </Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Должность</th>
                  <th>Подразделение</th>
                  <th>Категория</th>
                  <th className="num">Ставка</th>
                  <th className="num">Начисления в месяц</th>
                  <th className="num">Часов в неделю</th>
                  <th>Занятость</th>
                  {editable && <th />}
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td>{p.title}</td>
                    <td>{p.department ?? '—'}</td>
                    <td>{CATEGORY_LABELS[p.category]}</td>
                    <td className="num">{fmt(p.rate)}</td>
                    <td className="num">{fmtInt(p.monthly_pay)} ₽</td>
                    <td className="num">{p.weekly_hours ?? ''}</td>
                    <td>{p.employee_ref ? 'занята' : <Badge tone="amber">вакансия</Badge>}</td>
                    {editable && (
                      <td>
                        <ActionButton
                          className="ghost"
                          confirm={`Удалить строку «${p.title}»?`}
                          onClick={() => remove(p.id)}
                        >
                          Удалить
                        </ActionButton>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Async>
      {adding && (
        <Modal title="Новая строка штатного расписания" onClose={() => setAdding(false)}>
          <Form onSubmit={add}>
            <Field label="Должность">
              <input
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                required
              />
            </Field>
            <Field label="Подразделение">
              <input
                value={draft.department}
                onChange={(e) => setDraft({ ...draft, department: e.target.value })}
              />
            </Field>
            <div className="row">
              <Field label="Ставка">
                <input
                  type="number"
                  step="0.05"
                  min="0.05"
                  max="3"
                  value={draft.rate}
                  onChange={(e) => setDraft({ ...draft, rate: e.target.value })}
                />
              </Field>
              <Field label="Начисления в месяц, ₽">
                <input
                  type="number"
                  min="0"
                  value={draft.monthly_pay}
                  onChange={(e) => setDraft({ ...draft, monthly_pay: e.target.value })}
                />
              </Field>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.is_vacant}
                onChange={(e) => setDraft({ ...draft, is_vacant: e.target.checked })}
              />
              Вакансия
            </label>
            <p className="muted">Категория и функция определяются по названию должности.</p>
          </Form>
        </Modal>
      )}
    </Card>
  )
}

function SourceData({
  org,
  editable,
  onChange,
}: {
  org: OrgDetails
  editable: boolean
  onChange: () => void
}) {
  const year = Math.max(...org.enrollments.map((e) => e.academic_year), new Date().getFullYear())
  const [enrollment, setEnrollment] = useState({
    academic_year: String(year),
    level: 'primary',
    study_form: 'full_time',
    classes_count: '0',
    students_count: '0',
    special_needs_count: '0',
  })
  const [building, setBuilding] = useState({ name: '', area_sqm: '', floors: '2' })
  const [dialog, setDialog] = useState<'enrollment' | 'building' | null>(null)

  async function saveEnrollment() {
    await api(`/organizations/${org.id}/enrollments`, { method: 'PUT', body: enrollment })
    setDialog(null)
    onChange()
  }

  async function saveBuilding() {
    await api(`/organizations/${org.id}/buildings`, { body: building })
    setDialog(null)
    onChange()
  }

  const numberField = (
    key: 'classes_count' | 'students_count' | 'special_needs_count',
    label: string,
  ) => (
    <Field label={label}>
      <input
        type="number"
        min="0"
        value={enrollment[key]}
        onChange={(e) => setEnrollment({ ...enrollment, [key]: e.target.value })}
      />
    </Field>
  )

  return (
    <>
      <Card
        title="Контингент"
        aside={
          editable && <button onClick={() => setDialog('enrollment')}>Добавить или изменить</button>
        }
      >
        <table>
          <thead>
            <tr>
              <th>Учебный год</th>
              <th>Ступень</th>
              <th>Форма</th>
              <th className="num">Классов (групп)</th>
              <th className="num">Обучающихся</th>
              <th className="num">из них с ОВЗ</th>
              {editable && <th />}
            </tr>
          </thead>
          <tbody>
            {org.enrollments.map((e) => (
              <tr key={e.id}>
                <td>
                  {e.academic_year}/{String(e.academic_year + 1).slice(2)}
                </td>
                <td>{LEVEL_LABELS[e.level]}</td>
                <td>{FORM_LABELS[e.study_form]}</td>
                <td className="num">{e.classes_count}</td>
                <td className="num">{fmtInt(e.students_count)}</td>
                <td className="num">{e.special_needs_count}</td>
                {editable && (
                  <td>
                    <ActionButton
                      className="ghost"
                      confirm="Удалить строку контингента?"
                      onClick={async () => {
                        await api(`/enrollments/${e.id}`, { method: 'DELETE' })
                        onChange()
                      }}
                    >
                      Удалить
                    </ActionButton>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">В расчёт идёт последний учебный год, остальные нужны для прогноза.</p>
      </Card>

      <Card
        title="Здания"
        aside={editable && <button onClick={() => setDialog('building')}>Добавить</button>}
      >
        <table>
          <thead>
            <tr>
              <th>Здание</th>
              <th className="num">Площадь, м²</th>
              <th className="num">Этажей</th>
              <th className="num">Год постройки</th>
              {editable && <th />}
            </tr>
          </thead>
          <tbody>
            {org.buildings.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td>
                <td className="num">{fmt(b.area_sqm)}</td>
                <td className="num">{b.floors}</td>
                <td className="num">{b.year_built ?? '—'}</td>
                {editable && (
                  <td>
                    <ActionButton
                      className="ghost"
                      confirm={`Удалить здание «${b.name}»?`}
                      onClick={async () => {
                        await api(`/buildings/${b.id}`, { method: 'DELETE' })
                        onChange()
                      }}
                    >
                      Удалить
                    </ActionButton>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {dialog === 'enrollment' && (
        <Modal title="Контингент" onClose={() => setDialog(null)}>
          <Form onSubmit={saveEnrollment}>
            <div className="row">
              <Field label="Год начала учебного года">
                <input
                  type="number"
                  value={enrollment.academic_year}
                  onChange={(e) => setEnrollment({ ...enrollment, academic_year: e.target.value })}
                />
              </Field>
              <Field label="Ступень">
                <select
                  value={enrollment.level}
                  onChange={(e) => setEnrollment({ ...enrollment, level: e.target.value })}
                >
                  {Object.entries(LEVEL_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Форма обучения">
                <select
                  value={enrollment.study_form}
                  onChange={(e) => setEnrollment({ ...enrollment, study_form: e.target.value })}
                >
                  {Object.entries(FORM_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="row">
              {numberField('classes_count', 'Классов (групп)')}
              {numberField('students_count', 'Обучающихся')}
              {numberField('special_needs_count', 'из них с ОВЗ')}
            </div>
            <p className="muted">
              Если строка с таким годом, ступенью и формой уже есть, она будет обновлена.
            </p>
          </Form>
        </Modal>
      )}
      {dialog === 'building' && (
        <Modal title="Новое здание" onClose={() => setDialog(null)}>
          <Form onSubmit={saveBuilding}>
            <Field label="Название">
              <input
                value={building.name}
                onChange={(e) => setBuilding({ ...building, name: e.target.value })}
                required
              />
            </Field>
            <div className="row">
              <Field label="Площадь, м²">
                <input
                  type="number"
                  min="1"
                  value={building.area_sqm}
                  onChange={(e) => setBuilding({ ...building, area_sqm: e.target.value })}
                  required
                />
              </Field>
              <Field label="Этажей">
                <input
                  type="number"
                  min="1"
                  value={building.floors}
                  onChange={(e) => setBuilding({ ...building, floors: e.target.value })}
                />
              </Field>
            </div>
          </Form>
        </Modal>
      )}
    </>
  )
}

interface ForecastPoint {
  year: number
  students: number
  teaching_norm: number
}

function Forecast({ orgId }: { orgId: number }) {
  const state = useApi<{ history: ForecastPoint[]; forecast: ForecastPoint[] }>(
    `/organizations/${orgId}/forecast`,
  )
  return (
    <Card title="Прогноз контингента и потребности в педагогах">
      <Async state={state}>
        {({ history, forecast }) => {
          if (history.length < 2) {
            return <Empty>Для прогноза нужны данные о контингенте хотя бы за два года.</Empty>
          }
          // Последняя фактическая точка дублируется в прогнозный ряд, чтобы линии соединились
          const last = history[history.length - 1]
          const points = [
            ...history.map((p) => ({ year: p.year, students: p.students, need: p.teaching_norm })),
            ...forecast.map((p) => ({
              year: p.year,
              studentsF: p.students,
              needF: p.teaching_norm,
            })),
          ].map((p) =>
            p.year === last.year
              ? { ...p, studentsF: last.students, needF: last.teaching_norm }
              : p,
          )
          return (
            <>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={points}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                  <YAxis yAxisId="students" tick={{ fontSize: 12 }} />
                  <YAxis yAxisId="need" orientation="right" tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Legend />
                  <Line
                    isAnimationActive={false}
                    yAxisId="students"
                    dataKey="students"
                    name="Обучающихся"
                    stroke="#3b6fd4"
                    strokeWidth={2}
                  />
                  <Line
                    isAnimationActive={false}
                    yAxisId="students"
                    dataKey="studentsF"
                    name="Обучающихся, прогноз"
                    stroke="#3b6fd4"
                    strokeDasharray="5 4"
                    strokeWidth={2}
                  />
                  <Line
                    isAnimationActive={false}
                    yAxisId="need"
                    dataKey="need"
                    name="Педагогов по нормативу, ст."
                    stroke="#d9892b"
                    strokeWidth={2}
                  />
                  <Line
                    isAnimationActive={false}
                    yAxisId="need"
                    dataKey="needF"
                    name="Педагогов, прогноз"
                    stroke="#d9892b"
                    strokeDasharray="5 4"
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
              <p className="muted">
                Прогноз — линейный тренд по годам. Наполняемость классов и доля детей с ОВЗ
                считаются неизменными.
              </p>
            </>
          )
        }}
      </Async>
    </Card>
  )
}

export function OrganizationPage() {
  const { id } = useParams()
  const user = useUser()
  const navigate = useNavigate()
  const state = useApi<OrgDetails>(`/organizations/${id}`)
  const [tab, setTab] = useState<Tab>('compare')

  async function generateProject() {
    const project = await api<Project>('/projects/generate', {
      body: { kind: 'normalization', organization_id: Number(id) },
    })
    navigate(`/projects/${project.id}`)
  }

  return (
    <Async state={state}>
      {(org) => (
        <Page
          title={org.name}
          hint={`${ORG_TYPE_LABELS[org.org_type]} · ${org.municipality}`}
          actions={
            canPlan(user) && (
              <ActionButton className="primary" onClick={generateProject}>
                Сформировать проект штатного расписания
              </ActionButton>
            )
          }
        >
          <div className="kpis">
            <Kpi
              label="Факт"
              value={`${fmt(org.actual)} ст.`}
              note={`${fmtInt(org.students)} обучающихся`}
            />
            <Kpi
              label="Норматив"
              value={`${fmt(org.norm)} ст.`}
              note={`соответствие ${fmt(org.compliance)} %`}
            />
            <Kpi
              label="Избыток / нехватка"
              value={`${fmt(org.surplus)} / ${fmt(org.shortage)} ст.`}
            />
            <Kpi
              label="Потенциал экономии"
              value={fmtMoney(org.saving_potential_year)}
              note={`ФОТ ${fmtMoney(org.fot_actual_year)} в год`}
            />
          </div>
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              ['compare', 'Сравнение с нормативом'],
              ['positions', 'Штатное расписание'],
              ['data', 'Контингент и здания'],
              ['forecast', 'Прогноз'],
            ]}
          />
          {tab === 'compare' && <Comparison org={org} />}
          {tab === 'positions' && (
            <Positions orgId={org.id} editable={canEdit(user)} onChange={state.reload} />
          )}
          {tab === 'data' && (
            <SourceData org={org} editable={canEdit(user)} onChange={state.reload} />
          )}
          {tab === 'forecast' && <Forecast orgId={org.id} />}
        </Page>
      )}
    </Async>
  )
}
