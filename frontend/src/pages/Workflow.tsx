import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, Role, Task, WorkflowStep, WorkflowTemplate } from '../api'
import { useUser } from '../App'
import { ActionButton, Async, Card, Empty, Field, Form, Modal, Page, Tabs } from '../components/ui'
import { canPlan, fmtDate, ROLE_LABELS, TASK_STATUS, useApi } from '../lib'

const COLUMNS: Task['status'][] = ['todo', 'in_progress', 'done']
const NEXT_STATUS: Partial<Record<Task['status'], [Task['status'], string]>> = {
  todo: ['in_progress', 'Взять в работу'],
  in_progress: ['done', 'Завершить'],
}

function isOverdue(task: Task) {
  return (
    task.status !== 'done' && task.due_date !== null && new Date(task.due_date) < startOfToday()
  )
}

function startOfToday() {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

function Board() {
  const user = useUser()
  const state = useApi<Task[]>('/tasks')
  const [onlyMine, setOnlyMine] = useState(false)

  async function move(task: Task, status: Task['status']) {
    await api(`/tasks/${task.id}`, { method: 'PATCH', body: { status } })
    await state.reload()
  }

  return (
    <Async state={state}>
      {(tasks) => {
        const visible = onlyMine ? tasks.filter((t) => t.assignee_role === user.role) : tasks
        const waiting = visible.filter((t) => t.status === 'waiting').length
        if (tasks.length === 0) {
          return (
            <Empty>
              Задач нет. Запустите сценарий из карточки <Link to="/projects">проекта</Link>.
            </Empty>
          )
        }
        return (
          <>
            <label className="check">
              <input
                type="checkbox"
                checked={onlyMine}
                onChange={(e) => setOnlyMine(e.target.checked)}
              />
              Только адресованные моей роли
            </label>
            <div className="board">
              {COLUMNS.map((status) => (
                <div key={status} className="board-column">
                  <h3>{TASK_STATUS[status]}</h3>
                  {visible
                    .filter((t) => t.status === status)
                    .map((task) => {
                      const next = NEXT_STATUS[task.status]
                      // Двигать задачу может исполнитель по роли или тот, кто ведёт планирование
                      const allowed = canPlan(user) || task.assignee_role === user.role
                      return (
                        <div key={task.id} className={`task ${isOverdue(task) ? 'overdue' : ''}`}>
                          <div>{task.title}</div>
                          <div className="muted">
                            {ROLE_LABELS[task.assignee_role]} · срок {fmtDate(task.due_date)}
                            {isOverdue(task) && ' · просрочено'}
                          </div>
                          {next && allowed && (
                            <ActionButton className="small" onClick={() => move(task, next[0])}>
                              {next[1]}
                            </ActionButton>
                          )}
                        </div>
                      )
                    })}
                </div>
              ))}
            </div>
            {waiting > 0 && (
              <p className="muted">
                Задач, ожидающих завершения предыдущих шагов: {waiting}. Они откроются
                автоматически.
              </p>
            )}
          </>
        )
      }}
    </Async>
  )
}

const EMPTY_STEP: WorkflowStep = { title: '', role: 'municipal_specialist', duration_days: 3 }

function TemplateEditor({
  template,
  onClose,
  onSaved,
}: {
  template: WorkflowTemplate | null
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(template?.name ?? '')
  const [description, setDescription] = useState(template?.description ?? '')
  const [steps, setSteps] = useState<WorkflowStep[]>(template?.steps ?? [{ ...EMPTY_STEP }])

  const update = (index: number, patch: Partial<WorkflowStep>) =>
    setSteps(steps.map((step, i) => (i === index ? { ...step, ...patch } : step)))

  function move(index: number, shift: -1 | 1) {
    const target = index + shift
    if (target < 0 || target >= steps.length) return
    const next = [...steps]
    ;[next[index], next[target]] = [next[target], next[index]]
    setSteps(next)
  }

  async function save() {
    const body = { name, description: description || null, steps }
    if (template) await api(`/workflow/templates/${template.id}`, { method: 'PUT', body })
    else await api('/workflow/templates', { body })
    onSaved()
    onClose()
  }

  const total = steps.reduce((sum, step) => sum + Number(step.duration_days || 0), 0)

  return (
    <Modal title={template ? 'Сценарий' : 'Новый сценарий'} onClose={onClose} wide>
      <Form onSubmit={save}>
        <Field label="Название">
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Описание">
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="steps-editor">
          {steps.map((step, index) => (
            <div key={index} className="step-row">
              <span className="step-number">{index + 1}</span>
              <input
                placeholder="Что нужно сделать"
                value={step.title}
                onChange={(e) => update(index, { title: e.target.value })}
                required
              />
              <select
                value={step.role}
                onChange={(e) => update(index, { role: e.target.value as Role })}
              >
                {Object.entries(ROLE_LABELS)
                  .filter(([role]) => role !== 'observer')
                  .map(([role, label]) => (
                    <option key={role} value={role}>
                      {label}
                    </option>
                  ))}
              </select>
              <input
                type="number"
                min="1"
                max="180"
                title="Срок, дней"
                value={step.duration_days}
                onChange={(e) => update(index, { duration_days: Number(e.target.value) })}
              />
              <button type="button" className="ghost" onClick={() => move(index, -1)} title="Выше">
                ↑
              </button>
              <button type="button" className="ghost" onClick={() => move(index, 1)} title="Ниже">
                ↓
              </button>
              <button
                type="button"
                className="ghost"
                disabled={steps.length === 1}
                onClick={() => setSteps(steps.filter((_, i) => i !== index))}
                title="Удалить шаг"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <div className="actions">
          <button type="button" onClick={() => setSteps([...steps, { ...EMPTY_STEP }])}>
            Добавить шаг
          </button>
          <span className="muted">Шаги выполняются по порядку. Общий срок: {total} дн.</span>
        </div>
      </Form>
    </Modal>
  )
}

function Templates() {
  const user = useUser()
  const state = useApi<WorkflowTemplate[]>('/workflow/templates')
  const [editing, setEditing] = useState<WorkflowTemplate | null | 'new'>(null)

  return (
    <>
      {canPlan(user) && (
        <div className="actions">
          <button className="primary" onClick={() => setEditing('new')}>
            Новый сценарий
          </button>
        </div>
      )}
      <Async state={state}>
        {(templates) => (
          <div className="grid-2">
            {templates.map((template) => (
              <Card
                key={template.id}
                title={template.name}
                aside={
                  canPlan(user) && (
                    <div className="actions">
                      <button onClick={() => setEditing(template)}>Изменить</button>
                      <ActionButton
                        className="ghost"
                        confirm={`Удалить сценарий «${template.name}»?`}
                        onClick={async () => {
                          await api(`/workflow/templates/${template.id}`, { method: 'DELETE' })
                          await state.reload()
                        }}
                      >
                        Удалить
                      </ActionButton>
                    </div>
                  )
                }
              >
                {template.description && <p className="muted">{template.description}</p>}
                <ol className="chain">
                  {template.steps.map((step, index) => (
                    <li key={index}>
                      <strong>{step.title}</strong>
                      <span className="muted">
                        {ROLE_LABELS[step.role]} · {step.duration_days} дн.
                      </span>
                    </li>
                  ))}
                </ol>
              </Card>
            ))}
          </div>
        )}
      </Async>
      {editing && (
        <TemplateEditor
          template={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={state.reload}
        />
      )}
    </>
  )
}

export function Workflow() {
  const [tab, setTab] = useState<'board' | 'templates'>('board')
  return (
    <Page
      title="Задачи"
      hint="Этапы работ по проектам: кто отвечает и к какому сроку. О приближении срока система напомнит сама."
    >
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          ['board', 'Доска задач'],
          ['templates', 'Конструктор сценариев'],
        ]}
      />
      {tab === 'board' ? <Board /> : <Templates />}
    </Page>
  )
}
