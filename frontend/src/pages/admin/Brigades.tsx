import { useMemo, useState } from 'react'

import { api, Brigade, BrigadeSuggestions, Municipality, User } from '../../api'
import { Icon } from '../../components/icons'
import { Async, Badge, Card, Empty, Field, Form, Modal } from '../../components/ui'
import { useApi } from '../../lib'

export interface FieldTopic {
  code: string
  title: string
}

const numberOrNull = (value: string) => {
  const parsed = Number(value.replace(',', '.'))
  return value.trim() && Number.isFinite(parsed) ? parsed : null
}

const fmtKm = (value: number | null) =>
  value === null ? 'нет координат' : `${value.toLocaleString('ru-RU')} км`

function BrigadeEditor({
  brigade,
  municipalities,
  topics,
  users,
  brigades,
  onClose,
  onSaved,
}: {
  brigade: Brigade | null
  municipalities: Municipality[]
  topics: FieldTopic[]
  users: User[]
  brigades: Brigade[]
  onClose: () => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState({
    name: brigade?.name ?? '',
    municipality_id: brigade?.municipality_id ?? null,
    base_address: brigade?.base_address ?? '',
    latitude: brigade?.latitude?.toString() ?? '',
    longitude: brigade?.longitude?.toString() ?? '',
    topics: brigade?.topics ?? [],
    is_active: brigade?.is_active ?? true,
    member_ids: brigade?.members.map((m) => m.id) ?? [],
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })
  // В бригаду можно взять только пользователей с ролью «Выездная бригада»
  const crew = users.filter((u) => u.role === 'brigade')
  const brigadeName = (id: number | null) => brigades.find((b) => b.id === id)?.name

  function toggle<T>(list: T[], value: T) {
    return list.includes(value) ? list.filter((x) => x !== value) : [...list, value]
  }

  async function save() {
    const body = {
      ...draft,
      base_address: draft.base_address || null,
      latitude: numberOrNull(draft.latitude),
      longitude: numberOrNull(draft.longitude),
    }
    if (brigade) await api(`/admin/brigades/${brigade.id}`, { method: 'PUT', body })
    else await api('/admin/brigades', { body })
    onSaved()
    onClose()
  }

  async function remove() {
    if (!brigade || !window.confirm(`Удалить бригаду «${brigade.name}»?`)) return
    await api(`/admin/brigades/${brigade.id}`, { method: 'DELETE' })
    onSaved()
    onClose()
  }

  return (
    <Modal title={brigade ? brigade.name : 'Новая бригада'} onClose={onClose} wide>
      <Form onSubmit={save}>
        <div className="row">
          <Field label="Название">
            <input value={draft.name} onChange={(e) => set('name', e.target.value)} required />
          </Field>
          <Field label="Где работает">
            <select
              value={draft.municipality_id ?? ''}
              onChange={(e) =>
                set('municipality_id', e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">Весь округ</option>
              {municipalities.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Адрес базы">
          <input
            value={draft.base_address}
            onChange={(e) => set('base_address', e.target.value)}
            placeholder="Откуда бригада выезжает"
          />
        </Field>
        <div className="row">
          <Field label="Широта базы">
            <input
              inputMode="decimal"
              value={draft.latitude}
              onChange={(e) => set('latitude', e.target.value)}
            />
          </Field>
          <Field label="Долгота базы">
            <input
              inputMode="decimal"
              value={draft.longitude}
              onChange={(e) => set('longitude', e.target.value)}
            />
          </Field>
        </div>

        <div className="field">
          <span>Какие заявки берёт</span>
          <div className="check-grid">
            {topics.map((t) => (
              <label key={t.code} className="check">
                <input
                  type="checkbox"
                  checked={draft.topics.includes(t.code)}
                  onChange={() => set('topics', toggle(draft.topics, t.code))}
                />
                {t.title}
              </label>
            ))}
          </div>
          <span className="muted">
            {draft.topics.length
              ? 'Только отмеченные темы.'
              : 'Ничего не отмечено — все хозяйственные.'}
          </span>
        </div>

        <div className="field">
          <span>Состав</span>
          {crew.length === 0 ? (
            <span className="muted">
              Участников бригад пока нет — заведите их во вкладке «Пользователи»: роль «Сотрудник»,
              группа «Хозяйственный отдел», «В бригаде управления образования».
            </span>
          ) : (
            <div className="check-grid">
              {crew.map((u) => {
                const elsewhere = u.brigade_id !== null && u.brigade_id !== brigade?.id
                return (
                  <label key={u.id} className="check">
                    <input
                      type="checkbox"
                      checked={draft.member_ids.includes(u.id)}
                      onChange={() => set('member_ids', toggle(draft.member_ids, u.id))}
                    />
                    <span>
                      {u.full_name}
                      {elsewhere && (
                        <small className="muted"> · сейчас в «{brigadeName(u.brigade_id)}»</small>
                      )}
                    </span>
                  </label>
                )
              })}
            </div>
          )}
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(e) => set('is_active', e.target.checked)}
          />
          Бригада работает — ей можно направлять заявки
        </label>
        {brigade && (
          <button type="button" className="danger" onClick={remove}>
            Удалить бригаду
          </button>
        )}
      </Form>
    </Modal>
  )
}

/** Закрепление школ за бригадой с подсказкой по расстоянию от базы. */
function SchoolsEditor({
  brigade,
  onClose,
  onSaved,
}: {
  brigade: Brigade
  onClose: () => void
  onSaved: () => void
}) {
  const state = useApi<BrigadeSuggestions>(`/admin/brigades/${brigade.id}/suggestions`)
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(brigade.organizations.map((o) => o.id)),
  )
  const [radius, setRadius] = useState('15')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const items = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (state.data?.items ?? []).filter((i) => !needle || i.name.toLowerCase().includes(needle))
  }, [state.data, search])

  function toggle(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  // Ближайшие: школы, для которых эта бригада ближе остальных и не дальше радиуса
  function pickNearest() {
    const limit = numberOrNull(radius) ?? Infinity
    const next = new Set(selected)
    for (const i of state.data?.items ?? []) {
      if (i.nearest?.id === brigade.id && i.distance_km !== null && i.distance_km <= limit) {
        next.add(i.id)
      }
    }
    setSelected(next)
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api(`/admin/brigades/${brigade.id}/organizations`, {
        method: 'PUT',
        body: { organization_ids: [...selected] },
      })
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
      setBusy(false)
    }
  }

  return (
    <Modal title={`Школы: ${brigade.name}`} onClose={onClose} wide>
      <Async state={state}>
        {(data) => (
          <div className="form">
            {!data.has_base && (
              <div className="notice">
                <Icon name="pin" />
                <span>
                  У бригады не указаны координаты базы, поэтому расстояние не считается. Укажите их
                  в карточке бригады — или закрепите школы вручную.
                </span>
              </div>
            )}
            <div className="toolbar">
              <input
                type="search"
                placeholder="Поиск учреждения"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {data.has_base && (
                <span className="actions">
                  <label className="inline-field">
                    до
                    <input
                      inputMode="decimal"
                      value={radius}
                      onChange={(e) => setRadius(e.target.value)}
                      aria-label="Радиус, км"
                    />
                    км
                  </label>
                  <button type="button" onClick={pickNearest}>
                    Отметить ближайшие
                  </button>
                </span>
              )}
              <button type="button" className="ghost" onClick={() => setSelected(new Set())}>
                Снять все
              </button>
            </div>
            <p className="muted">
              Отмечено: {selected.size}. «Ближе всего» — для этой школы база этой бригады ближайшая
              среди всех бригад с координатами. Школу можно закрепить и за несколькими бригадами,
              если у них разные специализации.
            </p>
            {items.length === 0 ? (
              <Empty>Учреждений нет.</Empty>
            ) : (
              <ul className="school-list">
                {items.map((i) => (
                  <li key={i.id}>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={selected.has(i.id)}
                        onChange={() => toggle(i.id)}
                      />
                      <span className="school-name">
                        {i.name}
                        <small className="muted">
                          {i.municipality}
                          {i.other_brigades.length > 0 &&
                            ` · уже у: ${i.other_brigades.join(', ')}`}
                        </small>
                      </span>
                    </label>
                    <span className="school-side">
                      <span className="muted">{fmtKm(i.distance_km)}</span>
                      {i.nearest &&
                        (i.nearest.id === brigade.id ? (
                          <Badge tone="green">ближе всего</Badge>
                        ) : (
                          <Badge tone="gray">ближе: {i.nearest.name}</Badge>
                        ))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {error && <div className="notice notice-error">{error}</div>}
            <div className="form-actions">
              <button className="primary" disabled={busy} onClick={save}>
                {busy ? 'Сохраняем…' : `Сохранить (${selected.size})`}
              </button>
            </div>
          </div>
        )}
      </Async>
    </Modal>
  )
}

/** Хозотделы и уборщики учреждений: кто работает на месте, по школам. */
export function OnSiteStaff({
  users,
  directory,
}: {
  users: User[]
  directory: { organizations: { id: number; name: string }[] }
}) {
  const [search, setSearch] = useState('')
  const byOrg = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const map = new Map<number, { executors: User[]; cleaners: User[] }>()
    for (const u of users) {
      if (!u.organization_id || (u.role !== 'executor' && u.role !== 'cleaner')) continue
      const slot = map.get(u.organization_id) ?? { executors: [], cleaners: [] }
      ;(u.role === 'executor' ? slot.executors : slot.cleaners).push(u)
      map.set(u.organization_id, slot)
    }
    const name = (id: number) => directory.organizations.find((o) => o.id === id)?.name ?? '—'
    return [...map.entries()]
      .map(([id, slot]) => ({ id, name: name(id), ...slot }))
      .filter((o) => !needle || o.name.toLowerCase().includes(needle))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [users, directory, search])

  const names = (list: User[]) =>
    list.length ? (
      list.map((u) => (
        <span key={u.id} className={u.is_active ? '' : 'muted'}>
          {u.full_name}
          {u.is_active ? '' : ' (отключён)'}
        </span>
      ))
    ) : (
      <span className="muted">нет</span>
    )

  return (
    <Card title="Хозяйственный отдел и уборщики в учреждениях">
      <p className="muted">
        Сотрудники, которые работают в одном учреждении. Заводятся во вкладке «Пользователи»: роль
        «Сотрудник», группа «Хозяйственный отдел» (в учреждении) или «Уборщик».
      </p>
      <div className="toolbar">
        <input
          type="search"
          placeholder="Поиск учреждения"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {byOrg.length === 0 ? (
        <Empty>Сотрудников хозотдела и уборщиков пока нет.</Empty>
      ) : (
        <table className="stack">
          <thead>
            <tr>
              <th>Учреждение</th>
              <th>Хозяйственный отдел</th>
              <th>Уборщики</th>
            </tr>
          </thead>
          <tbody>
            {byOrg.map((o) => (
              <tr key={o.id}>
                <td data-label="Учреждение">
                  <strong>{o.name}</strong>
                </td>
                <td data-label="Хозяйственный отдел" className="name-list">
                  {names(o.executors)}
                </td>
                <td data-label="Уборщики" className="name-list">
                  {names(o.cleaners)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

export function Brigades({
  municipalities,
  topics,
  users,
  onChanged,
}: {
  municipalities: Municipality[]
  topics: FieldTopic[]
  users: User[]
  onChanged: () => void
}) {
  const state = useApi<Brigade[]>('/admin/brigades')
  const [editing, setEditing] = useState<Brigade | 'new' | null>(null)
  const [schools, setSchools] = useState<Brigade | null>(null)
  const topicTitle = (code: string) => topics.find((t) => t.code === code)?.title ?? code

  function changed() {
    void state.reload()
    onChanged()
  }

  return (
    <Card
      title="Бригады и мастера управления образования"
      aside={
        <button className="primary" onClick={() => setEditing('new')}>
          Добавить
        </button>
      }
    >
      <p className="muted">
        Бригада ездит по закреплённым за ней школам и берёт работу, которая не по силам хозотделу
        учреждения. Если один мастер обслуживает несколько соседних школ, заведите его как бригаду
        из одного человека. Заявку система отдаёт той бригаде, которая быстрее доберётся:
        учитываются очередь в часах и расстояние от базы. Сколько людей в бригаде лишние — во
        вкладке «Хозслужба» раздела «Штатка и нормативы».
      </p>
      <Async state={state}>
        {(brigades) =>
          brigades.length === 0 ? (
            <Empty>Бригад пока нет.</Empty>
          ) : (
            <div className="brigade-grid">
              {brigades.map((b) => (
                <div key={b.id} className={`brigade-card ${b.is_active ? '' : 'inactive'}`}>
                  <div className="card-head">
                    <h3>
                      <Icon name="truck" size={16} /> {b.name}
                    </h3>
                    {!b.is_active && <Badge>не работает</Badge>}
                  </div>
                  <dl className="facts">
                    <dt>Где</dt>
                    <dd>
                      {b.municipality ?? 'Весь округ'}
                      {b.base_address && <div className="muted">База: {b.base_address}</div>}
                    </dd>
                    <dt>Заявки</dt>
                    <dd>
                      {b.topics.length ? b.topics.map(topicTitle).join(', ') : 'все хозяйственные'}
                      <div className="muted">открытых сейчас: {b.active_requests}</div>
                    </dd>
                    <dt>Состав</dt>
                    <dd>
                      {b.members.length ? (
                        b.members.map((m) => m.name).join(', ')
                      ) : (
                        <span className="late">никого — заявки ей не уйдут</span>
                      )}
                    </dd>
                    <dt>Школы</dt>
                    <dd>
                      {b.organizations.length ? (
                        `${b.organizations.length} учр.`
                      ) : (
                        <span className="late">не закреплены</span>
                      )}
                    </dd>
                  </dl>
                  <div className="actions wrap">
                    <button onClick={() => setSchools(b)}>
                      <Icon name="pin" size={16} /> Школы
                    </button>
                    <button onClick={() => setEditing(b)}>Изменить</button>
                  </div>
                </div>
              ))}
            </div>
          )
        }
      </Async>
      {editing && state.data && (
        <BrigadeEditor
          brigade={editing === 'new' ? null : editing}
          municipalities={municipalities}
          topics={topics}
          users={users}
          brigades={state.data}
          onClose={() => setEditing(null)}
          onSaved={changed}
        />
      )}
      {schools && (
        <SchoolsEditor brigade={schools} onClose={() => setSchools(null)} onSaved={changed} />
      )}
    </Card>
  )
}
