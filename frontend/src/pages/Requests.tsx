import { CSSProperties, Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api, OrgRequest, RequestKind, RequestMeta, RequestStats, RequestStatus } from '../api'
import { useUser } from '../App'
import { STATUS_COLOR, StatusBar } from '../components/blocks'
import { AXIS, ChartTip, Legend, Meter, SERIES } from '../components/charts'
import { Icon, IconName } from '../components/icons'
import { Grouping, GROUPINGS, RequestTree } from '../components/RequestTree'
import {
  Async,
  Avatar,
  Badge,
  Card,
  Counter,
  Drawer,
  Empty,
  Field,
  Form,
  Kpi,
  Modal,
  Page,
  Tabs,
} from '../components/ui'
import {
  fmtDateTime,
  fmtDay,
  fmtHours,
  fmtInt,
  fmtRelative,
  REQUEST_KIND,
  REQUEST_STATUS,
  ROLE_LABELS,
  useApi,
} from '../lib'

type Tab = 'tree' | 'board' | 'stats'

const BOARD: RequestStatus[] = ['new', 'assigned', 'in_progress', 'on_hold', 'done']
const ACTIVE: RequestStatus[] = ['new', 'assigned', 'in_progress', 'on_hold']
const EVENT_ICON: Record<string, IconName> = {
  comment: 'message',
  status: 'check',
  assignee: 'user',
  deadline: 'clock',
}

/** Подпись срока: сколько осталось или на сколько опоздали. */
function Due({ request }: { request: OrgRequest }) {
  if (!request.due_at) return null
  if (request.status === 'on_hold') {
    return (
      <span>
        <Icon name="pause" size={13} /> срок приостановлен
      </span>
    )
  }
  if (!ACTIVE.includes(request.status)) return null
  return (
    <span className={request.overdue ? 'late' : ''}>
      <Icon name="clock" size={13} />
      {request.overdue ? 'просрочена ' : ''}
      {fmtRelative(request.due_at)}
    </span>
  )
}

function RequestCard({ request, onOpen }: { request: OrgRequest; onOpen: () => void }) {
  return (
    <div
      className={`task clickable kind-${request.kind} ${request.overdue ? 'overdue' : ''}`}
      onClick={onOpen}
    >
      <div className="task-title">{request.title}</div>
      <div className="task-meta">
        <span>№ {request.id}</span>
        <span>{request.topic_title}</span>
        {request.kind !== 'planned' && (
          <Badge tone={REQUEST_KIND[request.kind].tone}>{REQUEST_KIND[request.kind].label}</Badge>
        )}
      </div>
      <div className="task-meta">
        {request.assignee ? (
          <span>
            <Avatar name={request.assignee.name} small /> {request.assignee.name}
          </span>
        ) : (
          <span className="late">нет исполнителя</span>
        )}
        <Due request={request} />
        {request.comments > 0 && (
          <span>
            <Icon name="message" size={13} /> {request.comments}
          </span>
        )}
      </div>
    </div>
  )
}

function NewRequest({
  meta,
  onClose,
  onCreated,
}: {
  meta: RequestMeta
  onClose: () => void
  onCreated: (request: OrgRequest) => void
}) {
  const single = meta.organizations.length === 1
  const [draft, setDraft] = useState({
    title: '',
    text: '',
    kind: 'planned' as RequestKind,
    topic: '',
    organization: single ? String(meta.organizations[0].id) : '',
    building: '',
    location: '',
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })
  const buildings =
    meta.organizations.find((o) => String(o.id) === draft.organization)?.buildings ?? []
  const topic = meta.topics.find((t) => t.code === draft.topic)

  async function submit() {
    const created = await api<OrgRequest>('/requests', {
      body: {
        title: draft.title,
        text: draft.text,
        kind: draft.kind,
        topic: draft.topic || null,
        organization_id: draft.organization ? Number(draft.organization) : null,
        building_id: draft.building ? Number(draft.building) : null,
        location: draft.location || null,
      },
    })
    onCreated(created)
    onClose()
  }

  return (
    <Modal title="Новая заявка" onClose={onClose}>
      <Form onSubmit={submit} submitLabel="Отправить заявку">
        <Field label="Что нужно сделать">
          <input
            value={draft.title}
            onChange={(e) => set('title', e.target.value)}
            placeholder="Например: починить дверцу шкафа в кабинете 14"
            maxLength={200}
            minLength={5}
            autoFocus
            required
          />
        </Field>
        <Field label="Подробности">
          <textarea
            rows={3}
            value={draft.text}
            onChange={(e) => set('text', e.target.value)}
            placeholder="Что случилось, когда заметили, что уже пробовали"
          />
        </Field>
        <Field label="Срочность">
          <div className="kind-pick">
            {meta.kinds.map((kind) => (
              <button
                key={kind.code}
                type="button"
                className={draft.kind === kind.code ? 'active' : ''}
                onClick={() => set('kind', kind.code)}
              >
                {kind.title}
                <small>
                  {kind.hours ? `срок ${kind.hours} ч` : `срок ${topic?.days ?? '2–14'} дн.`}
                </small>
              </button>
            ))}
          </div>
        </Field>
        <div className="row">
          {!single && (
            <Field label="Учреждение">
              <select
                value={draft.organization}
                onChange={(e) => setDraft({ ...draft, organization: e.target.value, building: '' })}
                required
              >
                <option value="">Выберите…</option>
                {meta.organizations.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {buildings.length > 0 && (
            <Field label="Корпус">
              <select value={draft.building} onChange={(e) => set('building', e.target.value)}>
                <option value="">Не указан</option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        <div className="row">
          <Field label="Кабинет, этаж">
            <input value={draft.location} onChange={(e) => set('location', e.target.value)} />
          </Field>
          <Field label="Тема">
            <select value={draft.topic} onChange={(e) => set('topic', e.target.value)}>
              <option value="">Определить автоматически</option>
              {meta.topics.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.title}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <p className="muted">
          Тему, ответственного и срок система определит сама: исполнителем станет наименее
          загруженный сотрудник нужной службы.
        </p>
      </Form>
    </Modal>
  )
}

// Путь заявки, как его видит человек. «Ждёт ответа» — пауза на шаге «В работе».
const STEPS: [RequestStatus, string][] = [
  ['new', 'Создана'],
  ['assigned', 'Назначена'],
  ['in_progress', 'В работе'],
  ['done', 'Выполнена'],
  ['closed', 'Принята'],
]

function StatusPath({ request }: { request: OrgRequest }) {
  if (request.status === 'rejected') {
    return (
      <div className="notice notice-error">
        <Icon name="x" />
        <span>Заявка отклонена или отозвана. Причина — в ходе работы ниже.</span>
      </div>
    )
  }
  const current = request.status === 'on_hold' ? 2 : STEPS.findIndex(([s]) => s === request.status)
  return (
    <ol className="steps">
      {STEPS.map(([status, label], i) => (
        <li key={status} className={i < current ? 'passed' : i === current ? 'current' : ''}>
          <span className="step-dot">{i < current ? <Icon name="check" size={12} /> : i + 1}</span>
          {i === current && request.status === 'on_hold' ? 'Ждёт ответа' : label}
        </li>
      ))}
    </ol>
  )
}

/** Одна фраза о том, что происходит с заявкой и за кем ход. */
function situation(request: OrgRequest) {
  const who = request.assignee?.name
  switch (request.status) {
    case 'new':
      return 'Исполнитель пока не найден. Руководитель назначит его вручную.'
    case 'assigned':
      return `Исполнитель — ${who}. Заявку ещё не взяли в работу.`
    case 'in_progress':
      return `Заявку выполняет ${who}.`
    case 'on_hold':
      return 'Исполнитель задал вопрос и ждёт ответа заявителя. Пока ждём, срок не идёт.'
    case 'done':
      return 'Работа выполнена. Заявитель проверяет и принимает её; если промолчит, заявка закроется сама через несколько дней.'
    case 'closed':
      return 'Работа принята, заявка закрыта.'
    default:
      return ''
  }
}

interface Action {
  status: RequestStatus
  label: string
  tone: 'primary' | 'danger' | ''
  // Без текста в поле комментария это действие сервер не примет
  needsText?: string
  confirm?: string
}

function describe(status: RequestStatus, request: OrgRequest): Action {
  switch (status) {
    case 'in_progress':
      return request.status === 'done'
        ? { status, label: 'Вернуть на доработку', tone: '', needsText: 'Напишите, что не сделано' }
        : { status, label: 'Взять в работу', tone: 'primary' }
    case 'on_hold':
      return { status, label: 'Задать вопрос заявителю', tone: '', needsText: 'Напишите вопрос' }
    case 'done':
      return { status, label: 'Готово, отчитаться', tone: 'primary' }
    case 'closed':
      return { status, label: request.is_author ? 'Принять работу' : 'Закрыть', tone: 'primary' }
    case 'rejected':
      return request.is_author
        ? { status, label: 'Отозвать заявку', tone: 'danger', confirm: 'Отозвать заявку?' }
        : { status, label: 'Отклонить', tone: 'danger', needsText: 'Напишите причину отказа' }
    default:
      return { status, label: REQUEST_STATUS[status].label, tone: '' }
  }
}

function RequestDrawer({
  id,
  onClose,
  onChanged,
}: {
  id: number
  onClose: () => void
  onChanged: () => void
}) {
  const state = useApi<OrgRequest>(`/requests/${id}`)
  const user = useUser()
  const [text, setText] = useState('')
  const [due, setDue] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setText('')
      setDue(null)
      await state.reload()
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось выполнить действие')
    } finally {
      setBusy(false)
    }
  }

  const request = state.data
  if (!request) {
    return (
      <Drawer title={<h2>Заявка № {id}</h2>} onClose={onClose}>
        {state.error ? (
          <div className="notice notice-error">{state.error}</div>
        ) : (
          <div className="skeleton" style={{ height: 240 }} />
        )}
      </Drawer>
    )
  }

  const closed = request.status === 'closed' || request.status === 'rejected'
  const isAssignee = request.assignee?.id === user.id
  const canComment = !closed && user.role !== 'observer'
  // Синей остаётся одна кнопка — следующий обычный шаг, остальные действия рядом
  const actions = request.actions
    .map((status) => describe(status, request))
    .sort((a, b) => Number(b.tone === 'primary') - Number(a.tone === 'primary'))
    .map((action, i): Action =>
      i > 0 && action.tone === 'primary' ? { ...action, tone: '' } : action,
    )
  // Доля срока, которая уже прошла, — для полосы под сроком
  const total = request.due_at
    ? new Date(request.due_at).getTime() - new Date(request.created_at).getTime()
    : 0
  const end = new Date(request.resolved_at ?? Date.now()).getTime()
  const spent = total > 0 ? (end - new Date(request.created_at).getTime()) / total : 0

  function act(action: Action) {
    if (action.needsText && !text.trim()) {
      setError(`${action.needsText} в поле выше, затем нажмите «${action.label}» ещё раз`)
      input.current?.focus()
      return
    }
    if (action.confirm && !window.confirm(action.confirm)) return
    // Вопрос от исполнителя уходит в переписку, а статус меняется сам
    if (action.status === 'on_hold' && isAssignee && request?.status !== 'on_hold') {
      void run(() => api(`/requests/${id}/comments`, { body: { text, needs_reply: true } }))
      return
    }
    void run(() =>
      api(`/requests/${id}/status`, { body: { status: action.status, comment: text || null } }),
    )
  }

  return (
    <Drawer
      onClose={onClose}
      title={
        <>
          <div className="chips" style={{ marginBottom: 6 }}>
            <span className="muted">№ {request.id}</span>
            <Badge tone={REQUEST_STATUS[request.status].tone}>
              {REQUEST_STATUS[request.status].label}
            </Badge>
            {request.kind !== 'planned' && (
              <Badge tone={REQUEST_KIND[request.kind].tone}>
                {REQUEST_KIND[request.kind].label}
              </Badge>
            )}
            {request.overdue && <Badge tone="red">Просрочена</Badge>}
          </div>
          <h2>{request.title}</h2>
        </>
      }
      footer={
        canComment || actions.length ? (
          <>
            {canComment && (
              <textarea
                ref={input}
                rows={2}
                style={{ width: '100%' }}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={
                  isAssignee
                    ? 'Сообщение заявителю, вопрос или отчёт о выполнении'
                    : 'Сообщение по заявке'
                }
              />
            )}
            {error && <div className="chat-error">{error}</div>}
            <div className="actions wrap" style={{ marginTop: 8 }}>
              {actions.map((action) => (
                <button
                  key={action.status}
                  disabled={busy}
                  className={action.tone}
                  onClick={() => act(action)}
                >
                  {action.label}
                </button>
              ))}
              {canComment && (
                <button
                  disabled={busy || !text.trim()}
                  onClick={() => run(() => api(`/requests/${id}/comments`, { body: { text } }))}
                >
                  <Icon name="message" size={16} /> Отправить сообщение
                </button>
              )}
            </div>
          </>
        ) : undefined
      }
    >
      <StatusPath request={request} />
      {request.my_turn ? (
        <div className="notice notice-info turn-notice">
          <Icon name="arrow" />
          <span>
            <strong>Ваш ход: {request.my_turn.toLowerCase()}.</strong>
            <br />
            Кнопки — внизу панели.
          </span>
        </div>
      ) : (
        situation(request) && <p className="muted">{situation(request)}</p>
      )}

      <p style={{ whiteSpace: 'pre-wrap' }}>{request.text}</p>
      {request.resolution && (
        <div className="notice notice-info">
          <Icon name="check" />
          <span>
            <strong>Отчёт исполнителя:</strong> {request.resolution}
          </span>
        </div>
      )}

      <dl className="facts">
        <dt>Срок</dt>
        <dd>
          {request.due_at ? fmtDateTime(request.due_at) : '—'}
          {request.due_at && ACTIVE.includes(request.status) && (
            <span className="muted"> · {fmtRelative(request.due_at)}</span>
          )}
          <div className="sla">
            <i
              className={spent > 1 ? 'late' : spent > 0.75 ? 'warn' : ''}
              style={{ width: `${Math.min(spent, 1) * 100}%` }}
            />
          </div>
          {request.can_manage &&
            !closed &&
            (due === null ? (
              <button className="ghost small" onClick={() => setDue('')}>
                Изменить срок
              </button>
            ) : (
              <div className="actions" style={{ marginTop: 8 }}>
                <input
                  type="datetime-local"
                  aria-label="Новый срок"
                  value={due}
                  onChange={(e) => setDue(e.target.value)}
                />
                <button
                  className="primary small"
                  disabled={!due || busy}
                  onClick={() =>
                    run(() =>
                      api(`/requests/${id}`, {
                        method: 'PATCH',
                        body: { due_at: new Date(due).toISOString() },
                      }),
                    )
                  }
                >
                  Сохранить
                </button>
                <button className="ghost small" onClick={() => setDue(null)}>
                  Отмена
                </button>
              </div>
            ))}
        </dd>
        <dt>Исполнитель</dt>
        <dd>
          {request.can_manage && !closed && request.assignable ? (
            <select
              value={request.assignee?.id ?? ''}
              disabled={busy}
              onChange={(e) =>
                run(() =>
                  api(`/requests/${id}`, {
                    method: 'PATCH',
                    body: { assignee_id: e.target.value ? Number(e.target.value) : null },
                  }),
                )
              }
            >
              <option value="">Не назначен</option>
              {request.assignable.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {ROLE_LABELS[p.role]}
                </option>
              ))}
            </select>
          ) : (
            (request.assignee?.name ?? 'Не назначен')
          )}
          <div className="muted">Отвечает: {ROLE_LABELS[request.routed_role]}</div>
        </dd>
        <dt>Тема</dt>
        <dd>
          {request.topic_title}
          <span className="muted">
            {' '}
            ·{' '}
            {request.classified_by === 'llm'
              ? 'определена моделью'
              : request.classified_by === 'rules'
                ? 'определена по ключевым словам'
                : 'указана вручную'}
          </span>
        </dd>
        <dt>Где</dt>
        <dd>
          {request.organization}
          <div className="muted">
            {[request.building, request.location].filter(Boolean).join(', ') || 'место не указано'}
          </div>
        </dd>
        <dt>Заявитель</dt>
        <dd>
          {request.author?.name ?? '—'}
          <span className="muted"> · {fmtDateTime(request.created_at)}</span>
        </dd>
      </dl>

      <h3>Ход работы</h3>
      {request.events?.map((event) => (
        <div key={event.id} className={`event ${event.kind === 'comment' ? 'comment' : 'system'}`}>
          <span className="event-dot">
            <Icon name={EVENT_ICON[event.kind]} size={13} />
          </span>
          <div className="event-body">
            {event.text}
            <small>
              {event.author ?? 'Система'} · {fmtDateTime(event.created_at)}
            </small>
          </div>
        </div>
      ))}
    </Drawer>
  )
}

function StatsView({ onFilter }: { onFilter: (status: string) => void }) {
  const state = useApi<RequestStats>('/requests/stats')
  return (
    <Async state={state}>
      {(s) => {
        const peak = Math.max(...s.by_topic.map((t) => t.total), 1)
        return (
          <>
            <div className="kpis">
              <Kpi
                icon="inbox"
                label="В работе"
                value={<Counter value={s.active} format={fmtInt} />}
                note={`без исполнителя: ${s.unassigned}, ждут подтверждения: ${s.waiting_confirmation}`}
              />
              <Kpi
                icon="alert"
                tone={s.overdue ? 'critical' : 'good'}
                label="Просрочено"
                value={<Counter value={s.overdue} format={fmtInt} />}
                note={
                  s.overdue ? (
                    <button className="ghost small" onClick={() => onFilter('overdue')}>
                      показать просроченные
                    </button>
                  ) : (
                    'все заявки в сроке'
                  )
                }
              />
              <Kpi
                icon="check"
                tone={(s.in_time_pct ?? 100) < 80 ? 'warn' : 'good'}
                label="Выполнено в срок"
                value={
                  s.in_time_pct === null ? (
                    '—'
                  ) : (
                    <Counter value={s.in_time_pct} format={(v) => `${fmtInt(v)} %`} />
                  )
                }
                note={`${s.resolved} заявок за ${s.days} дней`}
              />
              <Kpi
                icon="clock"
                label="Среднее время выполнения"
                value={fmtHours(s.avg_hours)}
                note="от создания до отчёта исполнителя"
              />
            </div>

            <div className="grid-wide">
              <Card title={`Поступило и выполнено за ${s.days} дней`}>
                <ResponsiveContainer width="100%" height={230}>
                  <AreaChart data={s.flow.map((p) => ({ ...p, name: fmtDay(p.date) }))}>
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
              </Card>

              <Card title="По статусам">
                <StatusBar items={s.by_status} />
                <h3 style={{ marginTop: 20 }}>Срочность открытых</h3>
                <div className="chips">
                  {s.by_kind.map((k) => (
                    <Badge key={k.kind} tone={REQUEST_KIND[k.kind].tone}>
                      {k.title}: {k.count}
                    </Badge>
                  ))}
                </div>
              </Card>
            </div>

            <div className="grid-2">
              <Card title="По темам">
                <p className="card-sub">Сколько заявок и как быстро они выполняются.</p>
                {s.by_topic.map((t) => (
                  <Meter
                    key={t.topic}
                    label={
                      <>
                        {t.title}
                        <div className="muted">
                          {t.avg_hours === null ? 'ещё не выполнялись' : fmtHours(t.avg_hours)}
                          {t.overdue > 0 && ` · просрочено ${t.overdue}`}
                        </div>
                      </>
                    }
                    value={t.total}
                    max={peak}
                    suffix=""
                    low={t.overdue > 0}
                  />
                ))}
              </Card>

              <Card title="Нагрузка на исполнителей">
                <table>
                  <thead>
                    <tr>
                      <th>Исполнитель</th>
                      <th className="num">В работе</th>
                      <th className="num">Просрочено</th>
                      <th className="num">Выполнено</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.by_assignee.map((p) => (
                      <tr key={p.id ?? 'none'}>
                        <td>
                          <span className="chips">
                            <Avatar name={p.name} small /> {p.name}
                          </span>
                        </td>
                        <td className="num">{p.active}</td>
                        <td className="num">
                          {p.overdue ? <span className="delta-minus">{p.overdue}</span> : '—'}
                        </td>
                        <td className="num">{p.done}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {s.by_organization.length > 1 && (
                  <>
                    <h3 style={{ marginTop: 20 }}>Откуда приходят</h3>
                    {s.by_organization.map((o) => (
                      <Meter
                        key={o.id}
                        label={o.name}
                        value={o.total}
                        max={s.by_organization[0].total}
                        suffix=""
                      />
                    ))}
                  </>
                )}
              </Card>
            </div>
          </>
        )
      }}
    </Async>
  )
}

// Подписи этапов во множественном числе и короткое объяснение, что на этапе происходит
const PIPELINE: [RequestStatus, string, string][] = [
  ['new', 'Новые', 'ищем исполнителя'],
  ['assigned', 'Назначены', 'исполнитель знает'],
  ['in_progress', 'В работе', 'делают'],
  ['on_hold', 'Ждут ответа', 'вопрос заявителю'],
  ['done', 'Выполнены', 'ждут приёмки'],
  ['closed', 'Закрыты', 'работа принята'],
  ['rejected', 'Отклонены', 'или отозваны'],
]

function Pipeline({
  requests,
  value,
  onChange,
}: {
  requests: OrgRequest[]
  value: RequestStatus | null
  onChange: (status: RequestStatus | null) => void
}) {
  return (
    <div className="pipeline" role="group" aria-label="Этапы заявки">
      {PIPELINE.map(([status, label, note], i) => {
        const count = requests.filter((r) => r.status === status).length
        return (
          <Fragment key={status}>
            {i > 0 && i < 6 && <Icon name="chevron" size={14} />}
            {i === 6 && <span className="pipeline-gap" />}
            <button
              className={`pipeline-step ${value === status ? 'active' : ''}`}
              style={{ '--step': STATUS_COLOR[status] } as CSSProperties}
              aria-pressed={value === status}
              onClick={() => onChange(value === status ? null : status)}
            >
              <strong>{count}</strong>
              <span>{label}</span>
              <small>{note}</small>
            </button>
          </Fragment>
        )
      })}
    </div>
  )
}

const GROUPING_KEY = 'hr-edu-requests-grouping'

export function Requests() {
  const user = useUser()
  const [params, setParams] = useSearchParams()
  const state = useApi<OrgRequest[]>('/requests')
  const meta = useApi<RequestMeta>('/requests/meta')
  // Сотруднику и хозяйственной службе сводка и доска ни к чему: заявок у них немного
  const simple = user.role === 'employee' || user.role === 'executor'
  const [tab, setTab] = useState<Tab>('tree')
  const [grouping, setGrouping] = useState<Grouping>(() => {
    const saved = localStorage.getItem(GROUPING_KEY) as Grouping | null
    return saved ?? (simple ? 'status' : 'place')
  })
  const [creating, setCreating] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<RequestStatus | null>(null)
  const [mine, setMine] = useState(false)
  const [overdue, setOverdue] = useState(false)
  const opened = Number(params.get('open')) || null

  const open = (id: number | null) => setParams(id ? { open: String(id) } : {}, { replace: true })

  function changed() {
    void state.reload()
    // Счётчики в меню живут в другом компоненте — подскажем им обновиться
    window.dispatchEvent(new Event('requests-changed'))
  }

  // Данные обновляются сами: статусы меняются и без участия пользователя
  useEffect(() => {
    const timer = setInterval(() => void state.reload(), 60_000)
    return () => clearInterval(timer)
  }, [state.reload])

  useEffect(() => localStorage.setItem(GROUPING_KEY, grouping), [grouping])

  const searched = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (state.data ?? []).filter((r) => {
      if (mine && !r.my_turn) return false
      if (overdue && !r.overdue) return false
      if (!needle) return true
      return `${r.id} ${r.title} ${r.text} ${r.organization} ${r.assignee?.name ?? ''}`
        .toLowerCase()
        .includes(needle)
    })
  }, [state.data, search, mine, overdue])

  // Без выбранного этапа показываем то, что ещё не закрыто: архив только мешает
  const filtered = useMemo(
    () =>
      searched.filter((r) =>
        status ? r.status === status : r.status !== 'closed' && r.status !== 'rejected',
      ),
    [searched, status],
  )
  const myTurn = state.data?.filter((r) => r.my_turn).length ?? 0
  const late = state.data?.filter((r) => r.overdue).length ?? 0

  const tabs: [Tab, string][] = [
    ['tree', 'Дерево'],
    ['board', 'Доска'],
    ['stats', 'Сводка'],
  ]

  return (
    <Page
      title={user.role === 'employee' ? 'Мои заявки' : 'Заявки'}
      hint={
        user.role === 'employee'
          ? 'Опишите, что нужно сделать, — исполнителя и срок система подберёт сама. Здесь видно, на каком этапе каждая ваша заявка.'
          : 'Каждая заявка проходит путь слева направо. Нажмите на этап, чтобы увидеть только его заявки, или на заявку, чтобы открыть её.'
      }
      actions={
        user.role !== 'observer' &&
        meta.data && (
          <button className="primary" onClick={() => setCreating(true)}>
            <Icon name="plus" size={16} /> Новая заявка
          </button>
        )
      }
    >
      {!simple && <Tabs value={tab} onChange={setTab} tabs={tabs} />}

      {tab === 'stats' ? (
        <StatsView
          onFilter={() => {
            setStatus(null)
            setOverdue(true)
            setTab('tree')
          }}
        />
      ) : (
        <>
          <Pipeline requests={searched} value={status} onChange={setStatus} />

          <div className="toolbar">
            <button
              className={`chip ${mine ? 'chip-on' : ''}`}
              aria-pressed={mine}
              onClick={() => setMine(!mine)}
            >
              Ждут меня · {myTurn}
            </button>
            <button
              className={`chip ${overdue ? 'chip-on chip-late' : ''}`}
              aria-pressed={overdue}
              onClick={() => setOverdue(!overdue)}
            >
              Просрочены · {late}
            </button>
            <input
              type="search"
              placeholder="Поиск: номер, текст, учреждение, исполнитель"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {tab === 'tree' && (
              <select
                value={grouping}
                onChange={(e) => setGrouping(e.target.value as Grouping)}
                aria-label="Группировка"
              >
                {GROUPINGS.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            )}
            <span className="spacer" />
            <span className="muted">
              {status ? PIPELINE.find(([s]) => s === status)?.[1] : 'Открытые'}: {filtered.length}
            </span>
          </div>

          <Async state={state}>
            {() =>
              filtered.length === 0 ? (
                <Empty>
                  {state.data?.length
                    ? 'Под выбранные условия заявок нет. Снимите фильтр или выберите другой этап.'
                    : 'Заявок пока нет. Чтобы создать первую, нажмите «Новая заявка» справа вверху.'}
                </Empty>
              ) : tab === 'board' ? (
                <div className="board wide">
                  {(status ? [status] : BOARD).map((column) => {
                    const items = filtered.filter((r) => r.status === column)
                    return (
                      <div key={column} className="board-column">
                        <h3>
                          {REQUEST_STATUS[column].label} <span>{items.length}</span>
                        </h3>
                        {items.slice(0, 40).map((request) => (
                          <RequestCard
                            key={request.id}
                            request={request}
                            onOpen={() => open(request.id)}
                          />
                        ))}
                        {items.length > 40 && (
                          <p className="muted">
                            и ещё {items.length - 40} — удобнее смотреть в дереве
                          </p>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <RequestTree requests={filtered} grouping={grouping} onOpen={open} />
              )
            }
          </Async>
        </>
      )}

      {creating && meta.data && (
        <NewRequest
          meta={meta.data}
          onClose={() => setCreating(false)}
          onCreated={(request) => {
            changed()
            if (tab === 'stats') setTab('tree')
            open(request.id)
          }}
        />
      )}
      {opened && (
        <RequestDrawer key={opened} id={opened} onClose={() => open(null)} onChanged={changed} />
      )}
    </Page>
  )
}
