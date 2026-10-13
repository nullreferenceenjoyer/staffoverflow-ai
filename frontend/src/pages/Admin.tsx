import { useState } from 'react'

import { api, Municipality, OrgSummary, Role, User } from '../api'
import { Async, Badge, Card, Field, Form, Modal, Page, Tabs } from '../components/ui'
import { fmtDateTime, ROLE_LABELS, useApi } from '../lib'

// Роли, которые работают в пределах одного учреждения
const ORG_ROLES: Role[] = ['director', 'executor', 'employee']

interface AuditRow {
  id: number
  created_at: string
  user_email: string | null
  action: string
  entity: string | null
  entity_id: string | null
  details: Record<string, unknown> | null
  ip: string | null
}

function UserEditor({
  user,
  onClose,
  onSaved,
}: {
  user: User | null
  onClose: () => void
  onSaved: () => void
}) {
  const municipalities = useApi<Municipality[]>('/municipalities')
  const organizations = useApi<OrgSummary[]>('/organizations')
  const [draft, setDraft] = useState({
    email: user?.email ?? '',
    full_name: user?.full_name ?? '',
    password: '',
    role: (user?.role ?? 'director') as Role,
    municipality_id: user?.municipality_id ?? null,
    organization_id: user?.organization_id ?? null,
    telegram_chat_id: user?.telegram_chat_id ?? null,
    max_chat_id: user?.max_chat_id ?? null,
    is_active: user?.is_active ?? true,
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })

  async function save() {
    // Привязка к территории нужна только тем ролям, у которых она ограничивает доступ
    const body = {
      ...draft,
      municipality_id: draft.role === 'municipal_specialist' ? draft.municipality_id : null,
      organization_id: ORG_ROLES.includes(draft.role) ? draft.organization_id : null,
    }
    if (user) {
      const { email: _email, password, ...rest } = body
      await api(`/users/${user.id}`, {
        method: 'PATCH',
        body: password ? { ...rest, password } : rest,
      })
    } else {
      const { is_active: _active, ...rest } = body
      await api('/users', { body: rest })
    }
    onSaved()
    onClose()
  }

  const numberOrNull = (value: string) => (value ? Number(value) : null)

  return (
    <Modal title={user ? user.email : 'Новый пользователь'} onClose={onClose}>
      <Form onSubmit={save}>
        {!user && (
          <Field label="E-mail">
            <input
              type="email"
              value={draft.email}
              onChange={(e) => set('email', e.target.value)}
              required
            />
          </Field>
        )}
        <Field label="ФИО">
          <input
            value={draft.full_name}
            onChange={(e) => set('full_name', e.target.value)}
            required
          />
        </Field>
        <Field label={user ? 'Новый пароль (пусто — не менять)' : 'Пароль, от 8 символов'}>
          <input
            type="password"
            value={draft.password}
            onChange={(e) => set('password', e.target.value)}
            minLength={8}
            required={!user}
            autoComplete="new-password"
          />
        </Field>
        <Field label="Роль">
          <select value={draft.role} onChange={(e) => set('role', e.target.value as Role)}>
            {Object.entries(ROLE_LABELS).map(([role, label]) => (
              <option key={role} value={role}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        {draft.role === 'municipal_specialist' && (
          <Field label="Муниципалитет">
            <select
              value={draft.municipality_id ?? ''}
              onChange={(e) => set('municipality_id', numberOrNull(e.target.value))}
              required
            >
              <option value="">Выберите…</option>
              {municipalities.data?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {ORG_ROLES.includes(draft.role) && (
          <Field label="Учреждение">
            <select
              value={draft.organization_id ?? ''}
              onChange={(e) => set('organization_id', numberOrNull(e.target.value))}
              required
            >
              <option value="">Выберите…</option>
              {organizations.data?.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <p className="muted">Идентификатор чата бот сообщает пользователю при первом обращении.</p>
        <div className="row">
          <Field label="Чат в MAX">
            <input
              type="number"
              value={draft.max_chat_id ?? ''}
              onChange={(e) => set('max_chat_id', numberOrNull(e.target.value))}
            />
          </Field>
          <Field label="Чат в Telegram">
            <input
              type="number"
              value={draft.telegram_chat_id ?? ''}
              onChange={(e) => set('telegram_chat_id', numberOrNull(e.target.value))}
            />
          </Field>
        </div>
        {user && (
          <label className="check">
            <input
              type="checkbox"
              checked={draft.is_active}
              onChange={(e) => set('is_active', e.target.checked)}
            />
            Учётная запись активна
          </label>
        )}
      </Form>
    </Modal>
  )
}

function Users() {
  const state = useApi<User[]>('/users')
  const [editing, setEditing] = useState<User | 'new' | null>(null)
  return (
    <Card
      title="Пользователи"
      aside={
        <button className="primary" onClick={() => setEditing('new')}>
          Добавить
        </button>
      }
    >
      <Async state={state}>
        {(users) => (
          <table>
            <thead>
              <tr>
                <th>ФИО</th>
                <th>E-mail</th>
                <th>Роль</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.full_name}</td>
                  <td>{user.email}</td>
                  <td>{ROLE_LABELS[user.role]}</td>
                  <td>
                    {user.is_active ? <Badge tone="green">активен</Badge> : <Badge>отключён</Badge>}
                  </td>
                  <td>
                    <button onClick={() => setEditing(user)}>Изменить</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
      {editing && (
        <UserEditor
          user={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={state.reload}
        />
      )}
    </Card>
  )
}

function Audit() {
  const state = useApi<AuditRow[]>('/audit', { limit: 300 })
  return (
    <Card title="Журнал действий">
      <Async state={state}>
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Пользователь</th>
                <th>Действие</th>
                <th>Объект</th>
                <th>Подробности</th>
                <th>IP</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="nowrap">{fmtDateTime(row.created_at)}</td>
                  <td>{row.user_email ?? '—'}</td>
                  <td>{row.action}</td>
                  <td>{row.entity ? `${row.entity} #${row.entity_id}` : ''}</td>
                  <td className="muted reason">{row.details ? JSON.stringify(row.details) : ''}</td>
                  <td className="muted">{row.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </Card>
  )
}

export function Admin() {
  const [tab, setTab] = useState<'users' | 'audit'>('users')
  return (
    <Page title="Администрирование">
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          ['users', 'Пользователи'],
          ['audit', 'Журнал действий'],
        ]}
      />
      {tab === 'users' ? <Users /> : <Audit />}
    </Page>
  )
}
