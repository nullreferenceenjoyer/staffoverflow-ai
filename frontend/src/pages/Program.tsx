import { useState } from 'react'

import { api, DigitalTool, Milestone, ProgramData } from '../api'
import { useUser } from '../App'
import {
  ActionButton,
  Async,
  Badge,
  Card,
  Empty,
  Field,
  Form,
  Kpi,
  Modal,
  Page,
} from '../components/ui'
import { canPlan, fmt, fmtDate, fmtDateTime, fmtInt, fmtMoney, useApi } from '../lib'

const MILESTONE_STATUS: Record<Milestone['status'], { label: string; tone: string }> = {
  planned: { label: 'Запланировано', tone: 'gray' },
  in_progress: { label: 'В работе', tone: 'blue' },
  done: { label: 'Выполнено', tone: 'green' },
}

// Инструмент должен закрывать не менее 80 % функционала ставки
export const MIN_COVERAGE = 80

function Progress({ value, target }: { value: number; target: number }) {
  const share = target > 0 ? Math.max(0, Math.min(value / target, 1)) : 0
  return (
    <div className="progress" title={`${fmt(value)} из ${fmt(target)}`}>
      <div style={{ width: `${share * 100}%` }} />
    </div>
  )
}

function MilestoneEditor({
  milestone,
  onClose,
  onSaved,
}: {
  milestone: Milestone | null
  onClose: () => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState({
    title: milestone?.title ?? '',
    start_date: milestone?.start_date ?? '',
    end_date: milestone?.end_date ?? '',
    responsible: milestone?.responsible ?? '',
    status: milestone?.status ?? 'planned',
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })

  async function save() {
    const body = { ...draft, responsible: draft.responsible || null }
    if (milestone) await api(`/program/milestones/${milestone.id}`, { method: 'PUT', body })
    else await api('/program/milestones', { body })
    onSaved()
    onClose()
  }

  return (
    <Modal title={milestone ? 'Мероприятие' : 'Новое мероприятие'} onClose={onClose}>
      <Form onSubmit={save}>
        <Field label="Что нужно сделать">
          <textarea
            rows={3}
            value={draft.title}
            onChange={(e) => set('title', e.target.value)}
            required
          />
        </Field>
        <div className="row">
          <Field label="Начало">
            <input
              type="date"
              value={draft.start_date}
              onChange={(e) => set('start_date', e.target.value)}
              required
            />
          </Field>
          <Field label="Завершение">
            <input
              type="date"
              value={draft.end_date}
              onChange={(e) => set('end_date', e.target.value)}
              required
            />
          </Field>
        </div>
        <Field label="Ответственные">
          <input value={draft.responsible} onChange={(e) => set('responsible', e.target.value)} />
        </Field>
        <Field label="Статус">
          <select
            value={draft.status}
            onChange={(e) => set('status', e.target.value as Milestone['status'])}
          >
            {Object.entries(MILESTONE_STATUS).map(([key, { label }]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>
      </Form>
    </Modal>
  )
}

function ToolEditor({
  tool,
  onClose,
  onSaved,
}: {
  tool: DigitalTool
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(tool.name)
  const [description, setDescription] = useState(tool.description ?? '')
  const [coverage, setCoverage] = useState(tool.coverage_pct?.toString() ?? '')

  async function save() {
    await api(`/digital-tools/${tool.function_code}`, {
      method: 'PUT',
      body: {
        name,
        description: description || null,
        coverage_pct: coverage === '' ? null : Number(coverage),
      },
    })
    onSaved()
    onClose()
  }

  return (
    <Modal title={tool.function} onClose={onClose}>
      <Form onSubmit={save}>
        <Field label="Инструмент">
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Что делает">
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label="Какую долю функционала ставки закрывает, %">
          <input
            type="number"
            min="0"
            max="100"
            value={coverage}
            onChange={(e) => setCoverage(e.target.value)}
            placeholder="не оценено"
          />
        </Field>
      </Form>
    </Modal>
  )
}

export function ProgramPage() {
  const user = useUser()
  const editable = canPlan(user)
  const state = useApi<ProgramData>('/program')
  const tools = useApi<DigitalTool[]>('/digital-tools')
  const [milestone, setMilestone] = useState<Milestone | 'new' | null>(null)
  const [tool, setTool] = useState<DigitalTool | null>(null)

  if (state.error) {
    return (
      <Page title="Паспорт проекта">
        <Empty>
          Паспорт проекта для доступного вам муниципалитета не заведён. Его создаёт региональный
          аналитик или специалист управления образования через API (PUT /api/program).
        </Empty>
      </Page>
    )
  }

  return (
    <Async state={state}>
      {(p) => {
        const s = p.scoreboard
        return (
          <Page
            title="Паспорт проекта"
            hint={`${p.title} · ${p.municipality} · ${fmtDate(p.start_date)} — ${fmtDate(p.end_date)}`}
            actions={
              editable && (
                <ActionButton
                  confirm={
                    s.baseline_fixed
                      ? 'Исходная точка уже зафиксирована. Заменить её текущими данными? Достигнутое сокращение обнулится.'
                      : 'Запомнить текущие ставки и ФОТ как исходную точку проекта?'
                  }
                  onClick={async () => {
                    await api('/program/baseline', { method: 'POST' })
                    await state.reload()
                  }}
                >
                  {s.baseline_fixed ? 'Обновить исходную точку' : 'Зафиксировать исходную точку'}
                </ActionButton>
              )
            }
          >
            {p.description && <p className="hint wide">{p.description}</p>}
            {!s.baseline_fixed && (
              <div className="notice">
                Исходная точка не зафиксирована, поэтому достигнутое сокращение пока равно нулю.
                Зафиксируйте её после загрузки штатных расписаний на дату старта проекта — от неё
                будет считаться прогресс.
              </div>
            )}

            <div className="kpis">
              <div className="kpi">
                <span className="kpi-label">
                  Цель: −{fmt(s.target_pct)} % ФОТ АУП и ВП до {fmtDate(p.end_date)}
                </span>
                <strong>{fmt(s.done_pct)} %</strong>
                <Progress value={s.done_pct} target={s.target_pct} />
                <span className="kpi-note">
                  {s.days_left >= 0 ? `осталось дней: ${s.days_left}` : 'срок истёк'}
                </span>
              </div>
              <Kpi
                label="Экономия ФОТ в год"
                value={fmtMoney(s.done_saving_year)}
                note={`цель ${fmtMoney(s.target_saving_year)}, по паспорту ${fmtMoney(s.plan_saving_year)}`}
              />
              <Kpi
                label="Расчётный потенциал"
                value={fmtMoney(s.potential_saving_year)}
                note={`${fmt(s.potential_pct)} % ФОТ — избыток сверх нормативов`}
              />
              <Kpi
                label="Сценарий централизации"
                value={fmtMoney(s.centralization_saving_year)}
                note={`высвобождается ${fmt(s.centralization_released)} ст.`}
              />
            </div>

            <Card title="План и факт по ставкам">
              <table>
                <thead>
                  <tr>
                    <th>Категория</th>
                    <th className="num">Ставок: старт → сейчас</th>
                    <th className="num">План сокращения</th>
                    <th className="num">Сокращено</th>
                    <th>Выполнение</th>
                    <th className="num">Часов в год: план / факт</th>
                    <th className="num">Избыток по расчёту</th>
                  </tr>
                </thead>
                <tbody>
                  {s.categories.map((c) => (
                    <tr key={c.category}>
                      <td>{c.category === 'admin' ? 'АУП' : 'ВП'}</td>
                      <td className="num">
                        {fmt(c.baseline_rate)} → {fmt(c.current_rate)}
                      </td>
                      <td className="num">
                        {fmt(c.plan_rates)}
                        <div className="muted">увольнения: {fmt(c.plan_dismissals)}</div>
                      </td>
                      <td className="num">{fmt(c.done_rates)}</td>
                      <td>
                        <Progress value={c.done_rates} target={c.plan_rates} />
                      </td>
                      <td className="num">
                        {fmtInt(c.plan_hours)} / {fmtInt(c.done_hours)}
                      </td>
                      <td className="num">
                        {fmt(c.potential_rates)}
                        <div className="muted">вакансии: {fmt(c.potential_vacant)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">
                План — из паспорта. «Сокращено» — разница между исходной точкой
                {s.baseline_at ? ` (${fmtDateTime(s.baseline_at)})` : ''} и текущим штатным
                расписанием по {s.organizations} учреждениям. Часы считаются по нормативу{' '}
                {fmtInt(s.hours_per_rate)} ч в год на ставку. «Избыток по расчёту» — что система
                видит сверх нормативов сейчас; вакансии из него можно снять, никого не увольняя.
              </p>
            </Card>

            <div className="grid-2">
              <Card
                title="Дорожная карта"
                aside={editable && <button onClick={() => setMilestone('new')}>Добавить</button>}
              >
                <ol className="timeline">
                  {p.milestones.map((m) => {
                    const overdue = m.status !== 'done' && new Date(m.end_date) < new Date()
                    return (
                      <li key={m.id}>
                        <strong>{m.title}</strong>
                        <span className="muted">
                          {fmtDate(m.start_date)} — {fmtDate(m.end_date)}
                          {m.responsible && ` · ${m.responsible}`}
                        </span>
                        <div className="actions">
                          <Badge tone={overdue ? 'red' : MILESTONE_STATUS[m.status].tone}>
                            {overdue ? 'Срок прошёл' : MILESTONE_STATUS[m.status].label}
                          </Badge>
                          {editable && (
                            <button className="ghost" onClick={() => setMilestone(m)}>
                              Изменить
                            </button>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              </Card>

              <Card title="Чем закрываются функции АУП">
                <p className="muted">
                  Принцип паспорта: каждая сокращаемая ставка АУП сопровождается цифровым
                  инструментом, который берёт на себя не менее {MIN_COVERAGE} % её функционала.
                  Покрытие оцениваете вы — пока оно не указано, сокращение по функции помечается в
                  проектах как не обеспеченное.
                </p>
                <Async state={tools}>
                  {(list) => (
                    <table>
                      <tbody>
                        {list.map((t) => (
                          <tr key={t.function_code}>
                            <td>
                              <strong>{t.function}</strong>
                              <div>{t.name}</div>
                              <div className="muted">{t.description}</div>
                            </td>
                            <td className="nowrap">
                              {t.coverage_pct === null ? (
                                <Badge tone="amber">не оценено</Badge>
                              ) : (
                                <Badge tone={t.coverage_pct >= MIN_COVERAGE ? 'green' : 'red'}>
                                  {t.coverage_pct} %
                                </Badge>
                              )}
                            </td>
                            {editable && (
                              <td>
                                <button className="ghost" onClick={() => setTool(t)}>
                                  Изменить
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </Async>
              </Card>
            </div>

            {milestone && (
              <MilestoneEditor
                milestone={milestone === 'new' ? null : milestone}
                onClose={() => setMilestone(null)}
                onSaved={state.reload}
              />
            )}
            {tool && (
              <ToolEditor tool={tool} onClose={() => setTool(null)} onSaved={tools.reload} />
            )}
          </Page>
        )
      }}
    </Async>
  )
}
