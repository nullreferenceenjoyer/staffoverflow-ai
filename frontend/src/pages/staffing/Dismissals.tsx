import { useMemo, useState } from 'react'

import { api, DismissalItem, DismissalList, ProgramOverview } from '../../api'
import { Icon } from '../../components/icons'
import { st } from '../../components/staffing/Simple'
import { Async, Badge, Card, Empty, Field, Form, Modal } from '../../components/ui'
import { fmt, fmtDate, plural, useApi } from '../../lib'

type Draft = {
  organization_id: string
  full_name: string
  position: string
  fte: string
  basis: 'own' | 'layoff'
  article: string
  order_number: string
  order_date: string
  dismissed_on: string
  notified_on: string
  note: string
  apply: boolean
}

const EMPTY: Draft = {
  organization_id: '',
  full_name: '',
  position: '',
  fte: '1',
  basis: 'own',
  article: '',
  order_number: '',
  order_date: '',
  dismissed_on: '',
  notified_on: '',
  note: '',
  apply: true,
}

const ARTICLE = {
  own: 'п. 3 ч. 1 ст. 77 ТК РФ (собственное желание)',
  layoff: 'п. 2 ч. 1 ст. 81 ТК РФ (сокращение штата)',
}

function toDraft(item: DismissalItem): Draft {
  return {
    organization_id: String(item.organization_id),
    full_name: item.full_name,
    position: item.position,
    fte: String(item.fte).replace('.', ','),
    basis: item.basis,
    article: item.article ?? '',
    order_number: item.order_number ?? '',
    order_date: item.order_date ?? '',
    dismissed_on: item.dismissed_on ?? '',
    notified_on: item.notified_on ?? '',
    note: item.note ?? '',
    apply: item.applied_fte !== null,
  }
}

function DismissalForm({
  item,
  schools,
  bases,
  onClose,
  onSaved,
}: {
  item: DismissalItem | null
  schools: { id: number; name: string }[]
  bases: Record<string, string>
  onClose: () => void
  onSaved: () => void
}) {
  const [d, setD] = useState<Draft>(item ? toDraft(item) : EMPTY)
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch })

  async function save() {
    const fte = Number(d.fte.replace(',', '.'))
    if (!d.organization_id) throw new Error('Выберите школу')
    if (!Number.isFinite(fte) || fte <= 0) throw new Error('Ставка — число больше нуля')
    const body = {
      organization_id: Number(d.organization_id),
      full_name: d.full_name,
      position: d.position,
      fte,
      basis: d.basis,
      article: d.article || null,
      order_number: d.order_number || null,
      order_date: d.order_date || null,
      dismissed_on: d.dismissed_on || null,
      notified_on: d.basis === 'layoff' ? d.notified_on || null : null,
      note: d.note || null,
      apply_to_schedule: d.apply,
    }
    await api(item ? `/program/dismissals/${item.id}` : '/program/dismissals', {
      method: item ? 'PUT' : 'POST',
      body,
    })
    onSaved()
    onClose()
  }

  return (
    <Modal
      title={item ? 'Запись об увольнении' : 'Новая запись об увольнении'}
      onClose={onClose}
      wide
    >
      <Form onSubmit={save}>
        <div className="row">
          <Field label="Школа">
            <select
              value={d.organization_id}
              onChange={(e) => set({ organization_id: e.target.value })}
            >
              <option value="">—</option>
              {schools.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="ФИО">
            <input value={d.full_name} onChange={(e) => set({ full_name: e.target.value })} />
          </Field>
        </div>
        <div className="row">
          <Field label="Должность">
            <input value={d.position} onChange={(e) => set({ position: e.target.value })} />
          </Field>
          <Field label="Ставка">
            <input
              inputMode="decimal"
              value={d.fte}
              onChange={(e) => set({ fte: e.target.value })}
            />
          </Field>
          <Field label="Основание">
            <select
              value={d.basis}
              onChange={(e) => {
                const basis = e.target.value as Draft['basis']
                // Статью подставляем, только если её ещё не меняли руками
                const typical = !d.article || Object.values(ARTICLE).includes(d.article)
                set({ basis, article: typical ? ARTICLE[basis] : d.article })
              }}
            >
              {Object.entries(bases).map(([key, title]) => (
                <option key={key} value={key}>
                  {title}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Статья">
          <input
            value={d.article}
            placeholder={ARTICLE[d.basis]}
            onChange={(e) => set({ article: e.target.value })}
          />
        </Field>
        <div className="row">
          <Field label="№ приказа">
            <input value={d.order_number} onChange={(e) => set({ order_number: e.target.value })} />
          </Field>
          <Field label="Дата приказа">
            <input
              type="date"
              value={d.order_date}
              onChange={(e) => set({ order_date: e.target.value })}
            />
          </Field>
          <Field label="Дата увольнения">
            <input
              type="date"
              value={d.dismissed_on}
              onChange={(e) => set({ dismissed_on: e.target.value })}
            />
          </Field>
          {d.basis === 'layoff' && (
            <Field label="Уведомление выдано">
              <input
                type="date"
                value={d.notified_on}
                onChange={(e) => set({ notified_on: e.target.value })}
              />
            </Field>
          )}
        </div>
        <Field label="Примечание">
          <input value={d.note} onChange={(e) => set({ note: e.target.value })} />
        </Field>
        <label className="check">
          <input
            type="checkbox"
            checked={d.apply}
            onChange={(e) => set({ apply: e.target.checked })}
          />
          Учесть в штатке школы: «занято» по этой должности уменьшится на ставку, и она станет
          вакантной
        </label>
      </Form>
    </Modal>
  )
}

/** Сверка: сколько ставок «люди» в расчёте управления и сколько подтверждено приказами. */
function Reconcile({ overview }: { overview: ProgramOverview }) {
  const rows = overview.schools.filter((s) => s.dismissed_fte > 0 || s.people > 0)
  if (!rows.length) return null
  return (
    <Card title="Откуда берутся «сократить занятые ставки»">
      <p className="card-sub">
        В расчёте управления часть высвобождения приходится на занятые ставки. По каждой такой школе
        здесь видно, сколько ставок в расчёте и сколько подтверждено приказами ниже.
      </p>
      <table className="stack staffing-table">
        <thead>
          <tr>
            <th>Школа</th>
            <th className="num">В расчёте УО</th>
            <th className="num">По приказам</th>
            <th>Приказы</th>
            <th>Сверка</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const fte = s.dismissals.reduce((sum, d) => sum + d.fte, 0)
            return (
              <tr key={s.organization_id}>
                <td data-label="Школа">
                  <strong>{s.organization}</strong>
                </td>
                <td data-label="В расчёте" className="num">
                  {fmt(s.dismissed_fte)}
                  <div className="muted small-text">{s.staff_units} шт. ед.</div>
                </td>
                <td data-label="По приказам" className="num">
                  {fmt(fte)}
                  <div className="muted small-text">
                    {s.people} {plural(s.people, 'человек', 'человека', 'человек')}
                  </div>
                </td>
                <td data-label="Приказы" className="small-text">
                  {s.orders ?? '—'}
                </td>
                <td data-label="Сверка">
                  {s.matches ? (
                    <Badge tone="green">сходится</Badge>
                  ) : (
                    <Badge tone="amber">разница {fmt(Math.abs(s.dismissed_fte - fte))}</Badge>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}

export function Dismissals() {
  const state = useApi<DismissalList>('/program/dismissals')
  const overview = useApi<ProgramOverview>('/program/overview')
  const [editing, setEditing] = useState<DismissalItem | 'new' | null>(null)
  const [school, setSchool] = useState('')
  const [search, setSearch] = useState('')
  const reload = () => {
    void state.reload({ silent: true })
    void overview.reload({ silent: true })
  }

  const schools = useMemo(
    () =>
      (overview.data?.schools ?? []).map((s) => ({ id: s.organization_id, name: s.organization })),
    [overview.data],
  )

  const [problem, setProblem] = useState<string | null>(null)

  async function toggle(item: DismissalItem) {
    setProblem(null)
    try {
      await api(`/program/dismissals/${item.id}/apply`, {
        method: item.applied_fte === null ? 'POST' : 'DELETE',
      })
      reload()
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Не получилось')
    }
  }

  async function remove(item: DismissalItem) {
    if (!window.confirm(`Удалить запись «${item.full_name}, ${item.organization}»?`)) return
    await api(`/program/dismissals/${item.id}`, { method: 'DELETE' })
    reload()
  }

  return (
    <Async state={state}>
      {(data) => {
        const needle = search.trim().toLowerCase()
        const shown = data.items.filter(
          (i) =>
            (!school || String(i.organization_id) === school) &&
            (!needle ||
              `${i.full_name} ${i.position} ${i.organization} ${i.order_number ?? ''}`
                .toLowerCase()
                .includes(needle)),
        )
        const fte = data.items.reduce((sum, i) => sum + i.fte, 0)
        const own = data.items.filter((i) => i.basis === 'own').reduce((s, i) => s + i.fte, 0)
        const orgs = new Set(data.items.map((i) => i.organization_id)).size
        return (
          <>
            <div className="rule-box">
              <div>
                <strong>Как это работает:</strong> здесь приказы об увольнении — кто, из какой
                школы, на каком основании. Увольнение, учтённое в штатке, освобождает ставку: в
                штатке школы «занято» по должности уменьшается, а на «Итоге» эта ставка переходит из
                «сократить занятые ставки» в «убрать вакансии». Всего «высвободить» не меняется —
                ставку всё равно нужно убрать из штатки. Удалили запись или нажали «Вернуть» —
                ставка снова занята. Записи из расчёта управления загружены «до увольнения» и в
                штатке пока не учтены. На «Итоге» и в разъяснениях фамилий нет.
              </div>
            </div>
            <div className="kpis">
              <div className="kpi">
                <span className="kpi-label">Записей</span>
                <strong>{data.items.length}</strong>
                <span className="kpi-note">
                  из {orgs} {plural(orgs, 'школы', 'школ', 'школ')}
                </span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Ставок по приказам</span>
                <strong>{fmt(fte)}</strong>
                <span className="kpi-note">{st(fte)}</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">По собственному желанию</span>
                <strong>{fmt(own)}</strong>
                <span className="kpi-note">п. 3 ч. 1 ст. 77 ТК РФ</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Сокращение штата</span>
                <strong>{fmt(fte - own)}</strong>
                <span className="kpi-note">с уведомлением за 2 месяца</span>
              </div>
            </div>
            {overview.data && <Reconcile overview={overview.data} />}
            <Card
              title="Приказы"
              aside={
                data.can_edit && (
                  <button className="primary" onClick={() => setEditing('new')}>
                    <Icon name="plus" size={16} /> Добавить
                  </button>
                )
              }
            >
              <div className="toolbar">
                <select
                  value={school}
                  onChange={(e) => setSchool(e.target.value)}
                  aria-label="Школа"
                >
                  <option value="">Все школы</option>
                  {schools.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <input
                  type="search"
                  placeholder="ФИО, должность, № приказа"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              {problem && <div className="notice notice-error">{problem}</div>}
              {shown.length === 0 ? (
                <Empty>Записей нет.</Empty>
              ) : (
                <table className="stack staffing-table">
                  <thead>
                    <tr>
                      <th>Школа</th>
                      <th>Сотрудник</th>
                      <th className="num">Ставка</th>
                      <th>Основание</th>
                      <th>Приказ</th>
                      <th>Уволен</th>
                      <th>В штатке</th>
                      {data.can_edit && <th />}
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((i) => (
                      <tr key={i.id}>
                        <td data-label="Школа">{i.organization}</td>
                        <td data-label="Сотрудник">
                          <strong>{i.full_name}</strong>
                          <div className="muted small-text">{i.position}</div>
                        </td>
                        <td data-label="Ставка" className="num">
                          {fmt(i.fte)}
                        </td>
                        <td data-label="Основание">
                          <Badge tone={i.basis === 'layoff' ? 'orange' : 'gray'}>
                            {i.basis_title}
                          </Badge>
                          {i.notified_on && (
                            <div className="muted small-text">
                              уведомлён {fmtDate(i.notified_on)}
                            </div>
                          )}
                        </td>
                        <td data-label="Приказ" className="small-text">
                          {i.order_number ? `№ ${i.order_number}` : '—'}
                          {i.order_date && ` от ${fmtDate(i.order_date)}`}
                          {i.source && <div className="muted">{i.source}</div>}
                        </td>
                        <td data-label="Уволен">{fmtDate(i.dismissed_on)}</td>
                        <td data-label="В штатке" className="small-text">
                          {i.applied_fte !== null ? (
                            <>
                              <span className="dev-calm">учтено</span>
                              <div className="muted">
                                «{i.applied_position}»: занято −{fmt(i.applied_fte)}
                              </div>
                            </>
                          ) : (
                            <span className="muted">не учтено</span>
                          )}
                          {data.can_edit && (
                            <div>
                              <button className="ghost small" onClick={() => void toggle(i)}>
                                {i.applied_fte !== null ? 'Вернуть' : 'Учесть в штатке'}
                              </button>
                            </div>
                          )}
                        </td>
                        {data.can_edit && (
                          <td className="row-action">
                            <button
                              className="ghost icon"
                              aria-label="Изменить"
                              onClick={() => setEditing(i)}
                            >
                              <Icon name="edit" size={15} />
                            </button>
                            <button
                              className="ghost icon"
                              aria-label="Удалить"
                              onClick={() => void remove(i)}
                            >
                              <Icon name="trash" size={15} />
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            {editing && (
              <DismissalForm
                item={editing === 'new' ? null : editing}
                schools={schools}
                bases={data.bases}
                onClose={() => setEditing(null)}
                onSaved={reload}
              />
            )}
          </>
        )
      }}
    </Async>
  )
}
