import { useMemo, useState } from 'react'

import { api, Building, Municipality, OrgRecord } from '../../api'
import { ImportDialog } from '../../components/ImportDialog'
import { Icon } from '../../components/icons'
import { Async, Badge, Card, Empty, Field, Form, Modal } from '../../components/ui'
import { useApi } from '../../lib'

const ORG_TYPES = {
  school: 'Школа',
  preschool: 'Детский сад',
  complex: 'Образовательный комплекс',
} as const

const PAGE = 100

const numberOrNull = (value: string) => {
  const parsed = Number(value.replace(',', '.'))
  return value.trim() && Number.isFinite(parsed) ? parsed : null
}

function OrganizationEditor({
  org,
  municipalities,
  onClose,
  onSaved,
}: {
  org: OrgRecord | null
  municipalities: Municipality[]
  onClose: () => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState({
    name: org?.name ?? '',
    municipality: org?.municipality ?? municipalities[0]?.name ?? '',
    org_type: org?.org_type ?? 'school',
    address: org?.address ?? '',
    external_id: org?.external_id ?? '',
    latitude: org?.latitude?.toString() ?? '',
    longitude: org?.longitude?.toString() ?? '',
  })
  const [buildings, setBuildings] = useState<Building[]>(
    org?.buildings ?? [{ id: null, name: 'Основное здание', address: null }],
  )
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })
  const removable = org !== null && org.users === 0 && org.requests === 0

  async function save() {
    const body = {
      ...draft,
      address: draft.address || null,
      external_id: draft.external_id || null,
      latitude: numberOrNull(draft.latitude),
      longitude: numberOrNull(draft.longitude),
      buildings: buildings.filter((b) => b.name.trim()),
    }
    if (org) await api(`/admin/organizations/${org.id}`, { method: 'PUT', body })
    else await api('/admin/organizations', { body })
    onSaved()
    onClose()
  }

  async function remove() {
    if (!org || !window.confirm(`Удалить «${org.name}»?`)) return
    await api(`/admin/organizations/${org.id}`, { method: 'DELETE' })
    onSaved()
    onClose()
  }

  return (
    <Modal title={org ? org.name : 'Новое учреждение'} onClose={onClose} wide>
      <Form onSubmit={save}>
        <Field label="Название">
          <input value={draft.name} onChange={(e) => set('name', e.target.value)} required />
        </Field>
        <div className="row">
          <Field label="Муниципалитет">
            <input
              list="municipality-names"
              value={draft.municipality}
              onChange={(e) => set('municipality', e.target.value)}
              placeholder="Выберите или впишите новый"
              required
            />
            <datalist id="municipality-names">
              {municipalities.map((m) => (
                <option key={m.id} value={m.name} />
              ))}
            </datalist>
          </Field>
          <Field label="Тип">
            <select
              value={draft.org_type}
              onChange={(e) => set('org_type', e.target.value as OrgRecord['org_type'])}
            >
              {Object.entries(ORG_TYPES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Адрес">
          <input value={draft.address} onChange={(e) => set('address', e.target.value)} />
        </Field>
        <div className="row">
          <Field label="Широта">
            <input
              inputMode="decimal"
              placeholder="55,7512"
              value={draft.latitude}
              onChange={(e) => set('latitude', e.target.value)}
            />
          </Field>
          <Field label="Долгота">
            <input
              inputMode="decimal"
              placeholder="37,6184"
              value={draft.longitude}
              onChange={(e) => set('longitude', e.target.value)}
            />
          </Field>
          <Field label="Код во внешней системе">
            <input value={draft.external_id} onChange={(e) => set('external_id', e.target.value)} />
          </Field>
        </div>
        <p className="muted">
          По координатам система подсказывает, какой бригаде учреждение ближе. Их можно взять на
          любой карте: правый клик по зданию → «Что здесь?».
        </p>

        <div className="field">
          <span>Корпуса</span>
          {buildings.map((b, i) => (
            <div key={b.id ?? `new-${i}`} className="row building-row">
              <input
                value={b.name}
                placeholder="Название корпуса"
                aria-label="Название корпуса"
                onChange={(e) =>
                  setBuildings(
                    buildings.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                  )
                }
              />
              <input
                value={b.address ?? ''}
                placeholder="Адрес, если отличается"
                aria-label="Адрес корпуса"
                onChange={(e) =>
                  setBuildings(
                    buildings.map((x, j) => (j === i ? { ...x, address: e.target.value } : x)),
                  )
                }
              />
              <button
                type="button"
                className="ghost icon"
                aria-label="Убрать корпус"
                title="Убрать корпус"
                onClick={() => setBuildings(buildings.filter((_, j) => j !== i))}
              >
                <Icon name="x" />
              </button>
            </div>
          ))}
          <button
            type="button"
            className="ghost small"
            onClick={() => setBuildings([...buildings, { id: null, name: '', address: null }])}
          >
            <Icon name="plus" size={14} /> Добавить корпус
          </button>
        </div>
        {org && (
          <p className="muted">
            Пользователей: {org.users}, заявок: {org.requests}.{' '}
            {removable
              ? 'Учреждение можно удалить.'
              : 'Удалить нельзя, пока есть пользователи или заявки.'}
          </p>
        )}
        {removable && (
          <button type="button" className="danger" onClick={remove}>
            Удалить учреждение
          </button>
        )}
      </Form>
    </Modal>
  )
}

export function Organizations({
  municipalities,
  onChanged,
}: {
  municipalities: Municipality[]
  onChanged: () => void
}) {
  const state = useApi<OrgRecord[]>('/admin/organizations')
  const [editing, setEditing] = useState<OrgRecord | 'new' | null>(null)
  const [importing, setImporting] = useState(false)
  const [defaultMunicipality, setDefaultMunicipality] = useState('')
  const [search, setSearch] = useState('')
  const [municipality, setMunicipality] = useState('')
  const [limit, setLimit] = useState(PAGE)

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (state.data ?? []).filter(
      (o) =>
        (!municipality || String(o.municipality_id) === municipality) &&
        (!needle ||
          `${o.name} ${o.address ?? ''} ${o.external_id ?? ''}`.toLowerCase().includes(needle)),
    )
  }, [state.data, search, municipality])

  function changed() {
    void state.reload()
    onChanged()
  }

  return (
    <Card
      title="Учреждения"
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
          placeholder="Поиск: название, адрес, код"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setLimit(PAGE)
          }}
        />
        <select
          value={municipality}
          onChange={(e) => setMunicipality(e.target.value)}
          aria-label="Муниципалитет"
        >
          <option value="">Все муниципалитеты</option>
          {municipalities.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        <span className="spacer" />
        <span className="muted">Найдено: {shown.length}</span>
      </div>
      <Async state={state}>
        {() =>
          shown.length === 0 ? (
            <Empty>
              {state.data?.length
                ? 'Под условия поиска учреждений нет.'
                : 'Учреждений пока нет. Добавьте их по одному или загрузите из Excel.'}
            </Empty>
          ) : (
            <>
              <table className="stack">
                <thead>
                  <tr>
                    <th>Название</th>
                    <th>Муниципалитет</th>
                    <th>Адрес</th>
                    <th className="num">Корпусов</th>
                    <th className="num">Людей</th>
                    <th>Бригады</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {shown.slice(0, limit).map((o) => (
                    <tr key={o.id}>
                      <td data-label="Название">
                        <strong>{o.name}</strong>
                        <div className="muted">
                          {ORG_TYPES[o.org_type]}
                          {o.latitude === null && ' · нет координат'}
                        </div>
                      </td>
                      <td data-label="Муниципалитет">{o.municipality}</td>
                      <td data-label="Адрес">{o.address ?? '—'}</td>
                      <td data-label="Корпусов" className="num">
                        {o.buildings.length}
                      </td>
                      <td data-label="Людей" className="num">
                        {o.users}
                      </td>
                      <td data-label="Бригады">
                        {o.brigades.length ? (
                          <span className="chips">
                            {o.brigades.map((b) => (
                              <Badge key={b.id} tone="blue">
                                {b.name}
                              </Badge>
                            ))}
                          </span>
                        ) : (
                          <span className="muted">не закреплено</span>
                        )}
                      </td>
                      <td className="row-action">
                        <button onClick={() => setEditing(o)}>Изменить</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {shown.length > limit && (
                <button className="ghost" onClick={() => setLimit(limit + PAGE)}>
                  Показать ещё {Math.min(PAGE, shown.length - limit)}
                </button>
              )}
            </>
          )
        }
      </Async>
      {editing && (
        <OrganizationEditor
          org={editing === 'new' ? null : editing}
          municipalities={municipalities}
          onClose={() => setEditing(null)}
          onSaved={changed}
        />
      )}
      {importing && (
        <ImportDialog
          kind="organizations"
          onClose={() => setImporting(false)}
          onDone={changed}
          extra={{ municipality: defaultMunicipality }}
        >
          <Field label="Муниципалитет для строк, где он не указан (необязательно)">
            <input
              list="import-municipalities"
              value={defaultMunicipality}
              onChange={(e) => setDefaultMunicipality(e.target.value)}
              placeholder="Например, Северный м.о."
            />
            <datalist id="import-municipalities">
              {municipalities.map((m) => (
                <option key={m.id} value={m.name} />
              ))}
            </datalist>
          </Field>
        </ImportDialog>
      )}
    </Card>
  )
}
