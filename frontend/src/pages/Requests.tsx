import { useEffect, useMemo, useState } from 'react'
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
import { StatusBar } from '../components/blocks'
import { AXIS, ChartTip, Legend, Meter, SERIES } from '../components/charts'
import { Gantt, GanttItem } from '../components/Gantt'
import { Icon, IconName } from '../components/icons'
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

type Tab = 'dashboard' | 'board' | 'list' | 'gantt'

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

const ACTION_LABELS: Record<string, string> = {
  on_hold: 'Запросить уточнение',
  done: 'Выполнено',
  rejected: 'Отклонить',
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
  const [needsReply, setNeedsReply] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setText('')
      setNeedsReply(false)
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
  // Доля срока, которая уже прошла, — для полосы под сроком
  const total = request.due_at
    ? new Date(request.due_at).getTime() - new Date(request.created_at).getTime()
    : 0
  const end = new Date(request.resolved_at ?? Date.now()).getTime()
  const spent = total > 0 ? (end - new Date(request.created_at).getTime()) / total : 0

  const actionLabel = (status: RequestStatus) => {
    if (status === 'in_progress') {
      return request.status === 'done' ? 'Вернуть в работу' : 'Взять в работу'
    }
    if (status === 'closed') return request.is_author ? 'Принять работу' : 'Закрыть'
    return ACTION_LABELS[status]
  }

  return (
    <Drawer
      onClose={onClose}
      title={
        <>
          <div className="chips" style={{ marginBottom: 6 }}>
            <span className="muted">№ {request.id}</span>
            <Badge tone={REQUEST_STATUS[request.status].tone}>
              {request.overdue && <span className="dot live" />}
              {REQUEST_STATUS[request.status].label}
            </Badge>
            <Badge tone={REQUEST_KIND[request.kind].tone}>{REQUEST_KIND[request.kind].label}</Badge>
            {request.overdue && <Badge tone="red">Просрочена</Badge>}
          </div>
          <h2>{request.title}</h2>
        </>
      }
      footer={
        canComment || request.actions.length ? (
          <>
            {canComment && (
              <textarea
                rows={2}
                style={{ width: '100%' }}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Комментарий или отчёт о выполнении"
              />
            )}
            {error && <div className="chat-error">{error}</div>}
            <div className="actions wrap" style={{ marginTop: 8 }}>
              {canComment && (
                <button
                  disabled={busy || !text.trim()}
                  onClick={() =>
                    run(() =>
                      api(`/requests/${id}/comments`, {
                        body: { text, needs_reply: needsReply },
                      }),
                    )
                  }
                >
                  <Icon name="message" size={16} /> Написать
                </button>
              )}
              {request.actions.map((status) => (
                <button
                  key={status}
                  disabled={busy}
                  className={
                    status === 'rejected' ? 'danger' : status === 'on_hold' ? '' : 'primary'
                  }
                  onClick={() =>
                    run(() =>
                      api(`/requests/${id}/status`, { body: { status, comment: text || null } }),
                    )
                  }
                >
                  {actionLabel(status)}
                </button>
              ))}
            </div>
            {isAssignee && canComment && (
              <label className="check muted" style={{ marginTop: 8 }}>
                <input
                  type="checkbox"
                  checked={needsReply}
                  onChange={(e) => setNeedsReply(e.target.checked)}
                />
                Это вопрос заявителю — приостановить срок до ответа
              </label>
            )}
          </>
        ) : undefined
      }
    >
      <p style={{ marginTop: 0, whiteSpace: 'pre-wrap' }}>{request.text}</p>
      {request.resolution && (
        <div className="notice notice-info">
          <Icon name="check" />
          <span>{request.resolution}</span>
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
          {request.can_manage && !closed && (
            <input
              type="datetime-local"
              style={{ marginTop: 8 }}
              aria-label="Изменить срок"
              onChange={(e) =>
                e.target.value &&
                run(() =>
                  api(`/requests/${id}`, {
                    method: 'PATCH',
                    body: { due_at: new Date(e.target.value).toISOString() },
                  }),
                )
              }
            />
          )}
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

export function Requests() {
  const user = useUser()
  const [params, setParams] = useSearchParams()
  const state = useApi<OrgRequest[]>('/requests')
  const meta = useApi<RequestMeta>('/requests/meta')
  // Сотруднику сводка ни к чему — у него только свои заявки
  const [tab, setTab] = useState<Tab>(user.role === 'employee' ? 'list' : 'dashboard')
  const [creating, setCreating] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [topic, setTopic] = useState('')
  const [mine, setMine] = useState(false)
  const opened = Number(params.get('open')) || null

  const open = (id: number | null) => setParams(id ? { open: String(id) } : {}, { replace: true })

  // Данные обновляются сами: статусы меняются и без участия пользователя
  useEffect(() => {
    const timer = setInterval(() => void state.reload(), 60_000)
    return () => clearInterval(timer)
  }, [state.reload])

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (state.data ?? []).filter((r) => {
      if (status === 'overdue' ? !r.overdue : status && r.status !== status) return false
      if (topic && r.topic !== topic) return false
      if (mine && r.assignee?.id !== user.id && !r.is_author) return false
      if (!needle) return true
      return `${r.id} ${r.title} ${r.text} ${r.organization}`.toLowerCase().includes(needle)
    })
  }, [state.data, search, status, topic, mine, user.id])

  const gantt: GanttItem[] = useMemo(
    () =>
      filtered
        .filter((r) => r.due_at && (ACTIVE.includes(r.status) || r.status === 'done'))
        .sort((a, b) => (a.assignee?.name ?? 'яя').localeCompare(b.assignee?.name ?? 'яя'))
        .slice(0, 80)
        .map((r) => {
          const start = new Date(r.created_at).getTime()
          const end = new Date(r.due_at as string).getTime()
          return {
            id: r.id,
            label: r.title,
            note: `№ ${r.id} · ${r.topic_title}`,
            group: r.assignee?.name ?? 'Без исполнителя',
            start: r.created_at,
            end: r.due_at as string,
            progress: r.status === 'done' ? 1 : (Date.now() - start) / Math.max(end - start, 1),
            tone: r.overdue
              ? 'red'
              : r.status === 'done'
                ? 'green'
                : r.status === 'on_hold'
                  ? 'amber'
                  : 'blue',
            tip: `${REQUEST_STATUS[r.status].label}${r.overdue ? ', просрочена' : ''} · ${r.organization}`,
            onClick: () => open(r.id),
          } satisfies GanttItem
        }),
    [filtered],
  )

  const tabs: [Tab, string][] = [
    ['dashboard', 'Дашборд'],
    ['board', 'Доска'],
    ['list', 'Список'],
    ['gantt', 'Сроки'],
  ]

  return (
    <Page
      title="Заявки"
      hint="От «починить мебель» до «нужна ставка логопеда». Тема, ответственный и срок определяются автоматически, статус меняется по ходу работы."
      actions={
        user.role !== 'observer' &&
        meta.data && (
          <button className="primary" onClick={() => setCreating(true)}>
            <Icon name="plus" size={16} /> Новая заявка
          </button>
        )
      }
    >
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={user.role === 'employee' ? tabs.filter(([key]) => key !== 'dashboard') : tabs}
      />

      {tab === 'dashboard' ? (
        <StatsView
          onFilter={(value) => {
            setStatus(value)
            setTab('list')
          }}
        />
      ) : (
        <>
          <div className="toolbar">
            <input
              type="search"
              placeholder="Поиск по номеру, тексту, учреждению"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Все статусы</option>
              <option value="overdue">Просроченные</option>
              {meta.data?.statuses.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.title}
                </option>
              ))}
            </select>
            <select value={topic} onChange={(e) => setTopic(e.target.value)}>
              <option value="">Все темы</option>
              {meta.data?.topics.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.title}
                </option>
              ))}
            </select>
            {user.role !== 'employee' && (
              <label className="check">
                <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
                Только мои
              </label>
            )}
            <span className="spacer" />
            <span className="muted">Найдено: {filtered.length}</span>
          </div>

          <Async state={state}>
            {() =>
              filtered.length === 0 ? (
                <Empty>Заявок нет. Создайте первую — кнопка справа вверху.</Empty>
              ) : tab === 'board' ? (
                <div className="board wide">
                  {BOARD.map((column) => {
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
                      </div>
                    )
                  })}
                </div>
              ) : tab === 'gantt' ? (
                <Card title="Заявки на шкале времени">
                  <p className="card-sub">
                    Полоса — от создания до срока, заливка — сколько срока уже прошло. Красные
                    просрочены.
                  </p>
                  <Gantt items={gantt} empty="Нет открытых заявок со сроком" />
                </Card>
              ) : (
                <Card>
                  <table>
                    <thead>
                      <tr>
                        <th>№</th>
                        <th>Заявка</th>
                        <th>Статус</th>
                        <th>Исполнитель</th>
                        <th>Срок</th>
                        <th>Создана</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.slice(0, 300).map((r) => (
                        <tr key={r.id} className="clickable" onClick={() => open(r.id)}>
                          <td className="muted">{r.id}</td>
                          <td>
                            <strong>{r.title}</strong>
                            <div className="muted">
                              {r.topic_title} · {r.organization}
                            </div>
                          </td>
                          <td>
                            <div className="chips">
                              <Badge tone={REQUEST_STATUS[r.status].tone}>
                                {REQUEST_STATUS[r.status].label}
                              </Badge>
                              {r.kind !== 'planned' && (
                                <Badge tone={REQUEST_KIND[r.kind].tone}>
                                  {REQUEST_KIND[r.kind].label}
                                </Badge>
                              )}
                            </div>
                          </td>
                          <td>{r.assignee?.name ?? <span className="muted">не назначен</span>}</td>
                          <td className="nowrap">
                            {r.due_at ? fmtDateTime(r.due_at) : '—'}
                            {r.overdue && <div className="delta-minus">просрочена</div>}
                          </td>
                          <td className="nowrap muted">{fmtDateTime(r.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
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
            void state.reload()
            if (tab === 'dashboard') setTab('board')
            open(request.id)
          }}
        />
      )}
      {opened && (
        <RequestDrawer
          key={opened}
          id={opened}
          onClose={() => open(null)}
          onChanged={() => void state.reload()}
        />
      )}
    </Page>
  )
}
