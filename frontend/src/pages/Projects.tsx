import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, DigitalTool, download, Project, ProjectItem, Task, WorkflowTemplate } from '../api'
import { useUser } from '../App'
import { MIN_COVERAGE } from './Program'
import { ActionButton, Async, Badge, Card, Delta, Empty, Kpi, Page } from '../components/ui'
import {
  canApprove,
  canPlan,
  CATEGORY_LABELS,
  fmt,
  fmtDate,
  fmtInt,
  fmtMoney,
  PROJECT_STATUS,
  ROLE_LABELS,
  TASK_STATUS,
  useApi,
} from '../lib'

const KIND_LABELS: Record<string, string> = {
  normalization: 'Приведение к нормативу',
  centralization: 'Централизация',
}

const DOCUMENT_KINDS = [
  ['order', 'Проект приказа'],
  ['memo', 'Служебная записка'],
  ['justification', 'Обоснование для комиссии'],
] as const

// Часов в год на одну ставку
const HOURS_PER_RATE = 1972

/** Сколько сокращаемых ставок вакантны, а сколько заняты работниками. */
function cutSplit(items: ProjectItem[] = []) {
  let total = 0
  let vacant = 0
  for (const item of items) {
    const cut = item.current_rate - item.proposed_rate
    if (cut <= 0) continue
    total += cut
    vacant += Math.min(item.vacant_rate, cut)
  }
  return { total, vacant, occupied: total - vacant }
}

/** Для сокращаемой ставки АУП показывает, каким инструментом закрывается её функция. */
function ToolNote({ item, tools }: { item: ProjectItem; tools: DigitalTool[] }) {
  if (item.category !== 'admin' || item.proposed_rate >= item.current_rate) return null
  const tool = tools.find((t) => t.function_code === item.function_code)
  if (!tool) {
    return <div className="delta-minus">Цифровой инструмент для функции не назначен.</div>
  }
  const covered = tool.coverage_pct !== null && tool.coverage_pct >= MIN_COVERAGE
  return (
    <div className={covered ? 'tool-ok' : 'delta-plus'}>
      Функцию закрывает: {tool.name}
      {tool.coverage_pct === null
        ? ' — покрытие не оценено'
        : ` — покрытие ${tool.coverage_pct} %${covered ? '' : `, нужно не менее ${MIN_COVERAGE} %`}`}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const meta = PROJECT_STATUS[status] ?? { label: status, tone: 'gray' }
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

export function Projects() {
  const state = useApi<Project[]>('/projects')
  return (
    <Page
      title="Проекты"
      hint="Проекты изменений штатных расписаний. Новый проект создаётся из карточки учреждения или из раздела «Централизация»."
    >
      <Card>
        <Async state={state}>
          {(projects) =>
            projects.length === 0 ? (
              <Empty>
                Проектов пока нет. Откройте <Link to="/organizations">учреждение</Link> с
                отклонениями и нажмите «Сформировать проект».
              </Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Проект</th>
                    <th>Тип</th>
                    <th>Статус</th>
                    <th className="num">Изменение ставок</th>
                    <th className="num">ФОТ в год</th>
                    <th>Создан</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <Link to={`/projects/${p.id}`}>{p.title}</Link>
                      </td>
                      <td>{KIND_LABELS[p.kind]}</td>
                      <td>
                        <StatusBadge status={p.status} />
                      </td>
                      <td className="num">
                        <Delta value={p.rate_delta} />
                      </td>
                      <td className="num">{fmtMoney(p.fot_effect_year)}</td>
                      <td>{fmtDate(p.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </Async>
      </Card>
    </Page>
  )
}

export function ProjectPage() {
  const { id } = useParams()
  const user = useUser()
  const navigate = useNavigate()
  const state = useApi<Project>(`/projects/${id}`)
  const tasks = useApi<Task[]>('/tasks', { project_id: Number(id) })
  const templates = useApi<WorkflowTemplate[]>('/workflow/templates')
  const tools = useApi<DigitalTool[]>('/digital-tools')
  const [template, setTemplate] = useState('')

  async function setStatus(status: string) {
    await api(`/projects/${id}/status`, { body: { status } })
    await state.reload()
  }

  async function generateDocument(kind: string) {
    await api(`/projects/${id}/documents`, { body: { kind } })
    await state.reload()
  }

  async function startWorkflow() {
    const templateId = template || templates.data?.[0]?.id
    await api(`/workflow/templates/${templateId}/start`, { body: { project_id: Number(id) } })
    await tasks.reload()
  }

  return (
    <Async state={state}>
      {(project) => (
        <Page
          title={project.title}
          hint={project.summary ?? undefined}
          actions={
            <>
              <StatusBadge status={project.status} />
              {project.status === 'draft' && canPlan(user) && (
                <>
                  <ActionButton className="primary" onClick={() => setStatus('review')}>
                    Отправить на согласование
                  </ActionButton>
                  <ActionButton
                    confirm="Удалить черновик проекта?"
                    onClick={async () => {
                      await api(`/projects/${id}`, { method: 'DELETE' })
                      navigate('/projects')
                    }}
                  >
                    Удалить
                  </ActionButton>
                </>
              )}
              {project.status === 'review' && canApprove(user) && (
                <>
                  <ActionButton className="primary" onClick={() => setStatus('approved')}>
                    Утвердить
                  </ActionButton>
                  <ActionButton onClick={() => setStatus('rejected')}>Отклонить</ActionButton>
                </>
              )}
              {project.status === 'approved' && canPlan(user) && (
                <ActionButton onClick={() => setStatus('implemented')}>
                  Отметить внедрённым
                </ActionButton>
              )}
              {project.status === 'rejected' && canPlan(user) && (
                <ActionButton onClick={() => setStatus('draft')}>Вернуть в черновик</ActionButton>
              )}
            </>
          }
        >
          <div className="kpis">
            <Kpi label="Изменение численности" value={`${fmt(project.rate_delta)} ст.`} />
            <Kpi
              label="Изменение ФОТ"
              value={fmtMoney(project.fot_effect_year)}
              note="в год, с начислениями; минус — экономия"
            />
            <Kpi
              label="Как сокращаются ставки"
              value={`${fmt(cutSplit(project.items).vacant)} ст. — вакансии`}
              note={`${fmt(cutSplit(project.items).occupied)} ст. заняты работниками; высвобождается ${fmtInt(cutSplit(project.items).total * HOURS_PER_RATE)} ч в год`}
            />
          </div>

          <Card title="Предлагаемые изменения">
            <table>
              <thead>
                <tr>
                  <th>Учреждение / центр</th>
                  <th>Функция</th>
                  <th className="num">Было</th>
                  <th className="num">Станет</th>
                  <th className="num">ФОТ в год</th>
                  <th>Обоснование</th>
                </tr>
              </thead>
              <tbody>
                {project.items?.map((item) => (
                  <tr key={item.id}>
                    <td>{item.organization_name}</td>
                    <td>
                      {item.title}
                      <div className="muted">{CATEGORY_LABELS[item.category]}</div>
                    </td>
                    <td className="num">{fmt(item.current_rate)}</td>
                    <td className="num">{fmt(item.proposed_rate)}</td>
                    <td className="num">{fmtMoney(item.fot_effect_year)}</td>
                    <td className="reason">
                      {item.reason}
                      <ToolNote item={item} tools={tools.data ?? []} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <div className="grid-2">
            <Card title="Документы">
              {canPlan(user) && (
                <div className="actions wrap">
                  {DOCUMENT_KINDS.map(([kind, label]) => (
                    <ActionButton key={kind} onClick={() => generateDocument(kind)}>
                      {label}
                    </ActionButton>
                  ))}
                </div>
              )}
              <p className="muted">
                Таблица изменений берётся из проекта как есть. Вводный текст пишет локальная модель,
                а если она недоступна — подставляется шаблон.
              </p>
              {project.documents?.map((doc) => (
                <div key={doc.id} className="document">
                  <div className="card-head">
                    <strong>{doc.title}</strong>
                    <button
                      onClick={() =>
                        download(`/documents/${doc.id}/download`, `${doc.kind}-${project.id}.docx`)
                      }
                    >
                      Скачать .docx
                    </button>
                  </div>
                  <p>{doc.narrative}</p>
                  <span className="muted">
                    {fmtDate(doc.created_at)} · текст: {doc.written_by_llm ? 'модель' : 'шаблон'}
                  </span>
                </div>
              ))}
            </Card>

            <Card title="Задачи по проекту" aside={<Link to="/workflow">Все задачи</Link>}>
              {tasks.data?.length ? (
                <ol className="timeline">
                  {tasks.data.map((task) => (
                    <li key={task.id} className={`task-${task.status}`}>
                      <strong>{task.title.split(' — ')[0]}</strong>
                      <span className="muted">
                        {ROLE_LABELS[task.assignee_role]} · до {fmtDate(task.due_date)} ·{' '}
                        {TASK_STATUS[task.status]}
                      </span>
                    </li>
                  ))}
                </ol>
              ) : canPlan(user) && templates.data?.length ? (
                <div className="actions wrap">
                  <select value={template} onChange={(e) => setTemplate(e.target.value)}>
                    {templates.data.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                  <ActionButton className="primary" onClick={startWorkflow}>
                    Запустить сценарий
                  </ActionButton>
                </div>
              ) : (
                <Empty>Сценарий работ по проекту не запущен.</Empty>
              )}
            </Card>
          </div>
        </Page>
      )}
    </Async>
  )
}
