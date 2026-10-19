import { useMemo, useState } from 'react'

import { api, Municipality, Organization, Role, User } from '../../api'
import { ImportDialog } from '../../components/ImportDialog'
import { Icon } from '../../components/icons'
import { Async, Badge, Card, Empty, Field, Form, Modal } from '../../components/ui'
import { fmtDateTime, ROLE_LABELS, useApi } from '../../lib'

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

export interface Directory {
  municipalities: Municipality[]
  organizations: Organization[]
  brigades: { id: number; name: string }[]
}

/** Где работает пользователь: учреждение, муниципалитет или весь регион. */
function placeOf(user: User, directory: Directory) {
  if (user.organization_id) {
    return directory.organizations.find((o) => o.id === user.organization_id)?.name ?? '—'
  }
  if (user.municipality_id) {
    return directory.municipalities.find((m) => m.id === user.municipality_id)?.name ?? '—'
  }
  if (user.brigade_id) {
    const name = directory.brigades.find((b) => b.id === user.brigade_id)?.name
    return name ? `Бригада «${name}»` : '—'
  }
  return ['admin', 'regional_analyst', 'observer'].includes(user.role) ? 'Весь регион' : '—'
}

/**
 * Выбор учреждения: учреждений сотни, поэтому список фильтруется по названию
 * и разбит по муниципалитетам. Выбранное остаётся в списке, даже если не подходит под поиск.
 */
function OrganizationPicker({
  directory,
  value,
  onChange,
}: {
  directory: Directory
  value: number | null
  onChange: (id: number | null) => void
}) {
  const [query, setQuery] = useState('')
  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return directory.municipalities
      .map((m) => ({
        municipality: m,
        items: directory.organizations.filter(
          (o) =>
            o.municipality_id === m.id &&
            (o.id === value || !needle || o.name.toLowerCase().includes(needle)),
        ),
      }))
      .filter((group) => group.items.length > 0)
  }, [directory, query, value])
  const found = groups.reduce((sum, group) => sum + group.items.length, 0)

  return (
    <div className="picker">
      <input
        type="search"
        placeholder="Найти по названию или номеру"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          // Нашлось одно — сразу его и выбираем, открывать список незачем
          const needle = e.target.value.trim().toLowerCase()
          const matches = needle
            ? directory.organizations.filter((o) => o.name.toLowerCase().includes(needle))
            : []
          if (matches.length === 1) onChange(matches[0].id)
        }}
        aria-label="Поиск учреждения"
      />
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        required
        aria-label="Учреждение"
      >
        <option value="">{found ? 'Выберите учреждение…' : 'Ничего не найдено'}</option>
        {groups.map(({ municipality, items }) => (
          <optgroup key={municipality.id} label={municipality.name}>
            {items.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  )
}

function UserEditor({
  user,
  directory,
  onClose,
  onSaved,
}: {
  user: User | null
  directory: Directory
  onClose: () => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState({
    email: user?.email ?? '',
    full_name: user?.full_name ?? '',
    password: '',
    role: (user?.role ?? 'employee') as Role,
    municipality_id: user?.municipality_id ?? null,
    organization_id: user?.organization_id ?? null,
    brigade_id: user?.brigade_id ?? null,
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
      brigade_id: draft.role === 'brigade' ? draft.brigade_id : null,
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
              onChange={(e) =>
                set('municipality_id', e.target.value ? Number(e.target.value) : null)
              }
              required
            >
              <option value="">Выберите…</option>
              {directory.municipalities.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {ORG_ROLES.includes(draft.role) && (
          <Field label="Учреждение">
            <OrganizationPicker
              directory={directory}
              value={draft.organization_id}
              onChange={(id) => set('organization_id', id)}
            />
          </Field>
        )}
        {draft.role === 'brigade' && (
          <Field label="Бригада">
            <select
              value={draft.brigade_id ?? ''}
              onChange={(e) => set('brigade_id', e.target.value ? Number(e.target.value) : null)}
              required
            >
              <option value="">Выберите бригаду…</option>
              {directory.brigades.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <p className="muted">
          {draft.role === 'brigade'
            ? 'Участник видит заявки, направленные его бригаде, по всем закреплённым за ней учреждениям.'
            : draft.role === 'executor'
              ? 'Сотрудник на точке получает простую хозяйственную работу своего учреждения.'
              : ORG_ROLES.includes(draft.role)
                ? 'Пользователь увидит заявки только этого учреждения.'
                : draft.role === 'municipal_specialist'
                  ? 'Специалист видит заявки всех учреждений своего муниципалитета.'
                  : 'Эта роль видит заявки всего региона.'}
        </p>
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

export function Users({
  directory,
  state,
}: {
  directory: Directory
  state: ReturnType<typeof useApi<User[]>>
}) {
  const [editing, setEditing] = useState<User | 'new' | null>(null)
  const [importing, setImporting] = useState(false)
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<Role | ''>('')

  return (
    <Card
      title="Пользователи"
      aside={
        <div className="actions wrap">
          <button onClick={() => setImporting(true)}>
            <Icon name="upload" size={16} /> Из Excel
          </button>
          <button className="primary" onClick={() => setEditing('new')}>
            Добавить
          </button>
        </div>
      }
    >
      <div className="toolbar">
        <input
          type="search"
          placeholder="Поиск: ФИО, e-mail, учреждение"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as Role | '')}
          aria-label="Роль"
        >
          <option value="">Все роли</option>
          {Object.entries(ROLE_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <Async state={state}>
        {(users) => {
          const needle = search.trim().toLowerCase()
          const shown = users.filter(
            (u) =>
              (!role || u.role === role) &&
              (!needle ||
                `${u.full_name} ${u.email} ${placeOf(u, directory)}`
                  .toLowerCase()
                  .includes(needle)),
          )
          return shown.length === 0 ? (
            <Empty>Под условия поиска никто не подходит.</Empty>
          ) : (
            <table className="stack">
              <thead>
                <tr>
                  <th>ФИО</th>
                  <th>E-mail</th>
                  <th>Роль</th>
                  <th>Учреждение или территория</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shown.map((user) => (
                  <tr key={user.id}>
                    <td data-label="ФИО">
                      <strong>{user.full_name}</strong>
                    </td>
                    <td data-label="E-mail">{user.email}</td>
                    <td data-label="Роль">{ROLE_LABELS[user.role]}</td>
                    <td data-label="Учреждение">{placeOf(user, directory)}</td>
                    <td data-label="Статус">
                      {user.is_active ? (
                        <Badge tone="green">активен</Badge>
                      ) : (
                        <Badge>отключён</Badge>
                      )}
                    </td>
                    <td className="row-action">
                      <button onClick={() => setEditing(user)}>Изменить</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }}
      </Async>
      {editing && (
        <UserEditor
          user={editing === 'new' ? null : editing}
          directory={directory}
          onClose={() => setEditing(null)}
          onSaved={state.reload}
        />
      )}
      {importing && (
        <ImportDialog
          kind="users"
          onClose={() => setImporting(false)}
          onDone={() => void state.reload()}
        />
      )}
    </Card>
  )
}

export function Audit() {
  const state = useApi<AuditRow[]>('/audit', { limit: 300 })
  return (
    <Card title="Журнал действий">
      <Async state={state}>
        {(rows) => (
          <table className="stack">
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
                  <td data-label="Время" className="nowrap">
                    {fmtDateTime(row.created_at)}
                  </td>
                  <td data-label="Пользователь">{row.user_email ?? '—'}</td>
                  <td data-label="Действие">{row.action}</td>
                  <td data-label="Объект">
                    {row.entity ? `${row.entity} #${row.entity_id}` : '—'}
                  </td>
                  <td data-label="Подробности" className="muted reason">
                    {row.details ? JSON.stringify(row.details) : '—'}
                  </td>
                  <td data-label="IP" className="muted">
                    {row.ip ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </Card>
  )
}
