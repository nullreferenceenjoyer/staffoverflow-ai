import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  api,
  MaintenanceRow,
  MaintenanceSimple,
  RequestsBoard as Board,
  StaffingMeta,
  WorkloadSettings,
} from '../../api'
import { Meter } from '../../components/charts'
import { Icon } from '../../components/icons'
import { DetailTarget, MaintenanceDetail } from '../../components/staffing/MaintenanceDetail'
import { RequestsBoard } from '../../components/staffing/RequestsBoard'
import { Formula, st, Verdict } from '../../components/staffing/Simple'
import {
  Async,
  Badge,
  Card,
  Empty,
  Field,
  Form,
  Modal,
  Reveal,
  Segmented,
} from '../../components/ui'
import { fmt, fmtInt, plural, useApi } from '../../lib'

function StaffForm({
  row,
  year,
  onClose,
  onSaved,
}: {
  row: MaintenanceRow
  year: string
  onClose: () => void
  onSaved: () => void
}) {
  const [value, setValue] = useState(row.have === null ? '' : String(row.have).replace('.', ','))
  async function save() {
    const text = value.trim().replace(',', '.')
    const parsed = text ? Number(text) : null
    if (parsed !== null && (!Number.isFinite(parsed) || parsed < 0)) throw new Error('Нужно число')
    await api(`/program/maintenance/${row.organization_id}`, {
      method: 'PUT',
      body: { year, maintenance_fte: parsed },
    })
    onSaved()
    onClose()
  }
  return (
    <Modal title={row.organization} onClose={onClose}>
      <Form onSubmit={save}>
        <Field label="Ставок своего хозотдела в школе">
          <input inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
        <p className="muted">
          Рабочие по обслуживанию здания, дворники, электрики — кто работает только в этой школе. 0
          — своего хозотдела нет, школу обслуживает бригада управления.
        </p>
      </Form>
    </Modal>
  )
}

function SchoolCalc({ row, data }: { row: MaintenanceRow; data: MaintenanceSimple }) {
  if (row.status === 'brigade')
    return (
      <p>
        Своего хозотдела нет — школу обслуживает{' '}
        <strong>{row.brigades.join(', ') || 'бригада (не закреплена)'}</strong>. Её считаем в
        расчёте бригады ниже. Заявок бригаде за {data.days} дн.: {row.brigade_requests}.
      </p>
    )
  return (
    <Formula
      lines={[
        <>
          Заявок за {data.days} дн.: <strong>{row.requests}</strong> — это{' '}
          <strong>{fmt(row.hours)} ч</strong> работы
        </>,
        <>
          {fmt(row.hours)} ч ÷ {fmtInt(data.rate_hours)} ч заявок на ставку ={' '}
          {fmt(row.hours / data.rate_hours)} → нужно <strong>{st(row.need)}</strong>
          {row.need === data.settings.min_people && ' (минимум)'}
        </>,
      ]}
      result={
        <>
          есть <strong>{st(row.have)}</strong> → <Verdict status={row.status} diff={row.diff} />
          {row.load_pct !== null && (
            <span className="muted"> · загрузка {fmt(row.load_pct)} %</span>
          )}
        </>
      }
    />
  )
}

function Brigades({
  data,
  onOpen,
}: {
  data: MaintenanceSimple
  onOpen: (target: DetailTarget) => void
}) {
  const navigate = useNavigate()
  return (
    <Card
      title="Бригады управления образования"
      aside={
        data.can_edit_brigades && (
          <button onClick={() => navigate('/admin')}>
            <Icon name="truck" size={16} /> Собрать или изменить бригаду
          </button>
        )
      }
    >
      <p className="card-sub">
        Бригада обслуживает закреплённые за ней школы. Считаем по всем её заявкам: работа + дорога
        от базы. Нужно людей = часы ÷ {fmtInt(data.rate_hours)} ч на человека.
      </p>
      {data.brigades.length === 0 ? (
        <Empty>
          Бригад нет. Их собирает администратор: «Администрирование» → «Хозяйственные работы».
        </Empty>
      ) : (
        <div className="brigade-grid">
          {data.brigades.map((b) => (
            <div key={b.id} className="brigade-card">
              <div className="card-head">
                <h3>
                  <Icon name="truck" size={16} /> {b.name}
                </h3>
                {b.status === 'surplus' ? (
                  <Badge tone="orange">лишние {fmt(b.surplus)}</Badge>
                ) : b.status === 'overload' ? (
                  <Badge tone="red">не успевают</Badge>
                ) : (
                  <Badge tone="green">нужны все</Badge>
                )}
              </div>
              <button className="ghost small" onClick={() => onOpen({ brigade: b.id })}>
                Подробно: люди, школы, заявки <Icon name="arrow" size={14} />
              </button>
              <Meter label="Загрузка" value={b.load_pct} low={(b.load_pct ?? 0) < 50} />
              <dl className="bucket-facts">
                <dt>Людей / нужно</dt>
                <dd>
                  {b.people} / {fmt(b.needed)}
                </dd>
                <dt>Заявок</dt>
                <dd>{b.requests}</dd>
                <dt>Работа + дорога</dt>
                <dd>
                  {fmt(b.work_hours)} + {fmt(b.travel_hours)} ч
                </dd>
                <dt>Школ обслуживает</dt>
                <dd>{b.organizations.length}</dd>
              </dl>
              <details className="action-why">
                <summary>Какие школы и кто в бригаде</summary>
                <p className="small-text">
                  <strong>Состав:</strong>{' '}
                  {b.members.map((m) => `${m.name} (${fmt(m.hours)} ч)`).join(', ') || '—'}
                </p>
                <p className="small-text">
                  <strong>Школы:</strong> {b.organizations.map((o) => o.name).join(', ') || '—'}
                </p>
                {b.candidates.length > 0 && (
                  <p className="small-text dev-surplus">
                    Меньше всех загружены: {b.candidates.join(', ')}
                  </p>
                )}
                {b.distance_unknown && (
                  <p className="muted small-text">
                    У части школ нет координат — дорога до них не посчитана.
                  </p>
                )}
              </details>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

/** Коротко для дашборда: хватает ли людей на эти заявки. */
function StaffPanel({
  data,
  single,
  onOpen,
}: {
  data: MaintenanceSimple
  single: boolean
  onOpen: (target: DetailTarget) => void
}) {
  const own = data.schools.filter((s) => s.status !== 'brigade')
  const filled = own.filter((s) => s.status !== 'no_data')
  const have = filled.reduce((sum, s) => sum + (s.have ?? 0), 0)
  const need = filled.reduce((sum, s) => sum + (s.need ?? 0), 0)
  const surplus = filled.reduce((sum, s) => sum + Math.max(s.diff ?? 0, 0), 0)
  const deficit = filled.reduce((sum, s) => sum + Math.max(-(s.diff ?? 0), 0), 0)
  return (
    <div className="grid-2">
      <Card title={single ? 'Свой хозотдел' : 'Свой хозотдел школ'}>
        {own.length === 0 ? (
          <Empty>
            {single
              ? 'Своего хозотдела нет — школу обслуживает бригада управления.'
              : 'Ни одна школа не внесла ставки своего хозотдела.'}
          </Empty>
        ) : (
          <>
            <dl className="board-facts">
              <div>
                <dt>Есть ставок</dt>
                <dd>{fmt(have)}</dd>
              </div>
              <div>
                <dt>Нужно по заявкам</dt>
                <dd>{fmt(need)}</dd>
              </div>
              <div>
                <dt>Лишние</dt>
                <dd className={surplus ? 'dev-surplus' : ''}>{fmt(surplus)}</dd>
              </div>
              <div>
                <dt>Не хватает</dt>
                <dd className={deficit ? 'dev-deficit' : ''}>{fmt(deficit)}</dd>
              </div>
            </dl>
            <div className="scroll-list">
              {own
                .filter((s) => s.load_pct !== null)
                .map((s) => (
                  <button
                    key={s.organization_id}
                    className="row-button"
                    onClick={() => onOpen({ organization: s.organization_id })}
                  >
                    <Meter
                      label={single ? 'Загрузка' : s.organization}
                      value={s.load_pct}
                      mark={data.settings.target_load_pct}
                      low={(s.load_pct ?? 0) < data.settings.target_load_pct / 2}
                      max={Math.max(100, ...own.map((o) => o.load_pct ?? 0))}
                    />
                  </button>
                ))}
            </div>
            <p className="muted small-text">
              Загрузка — часы заявок от времени ставок на заявки. Черта — нормальная загрузка{' '}
              {fmt(data.settings.target_load_pct)} %. Нажмите на школу — откроется подробно.
            </p>
          </>
        )}
      </Card>
      <Card title="Бригады управления">
        {data.brigades.length === 0 ? (
          <Empty>Бригад нет.</Empty>
        ) : (
          <>
            {data.brigades.map((b) => (
              <button key={b.id} className="row-button" onClick={() => onOpen({ brigade: b.id })}>
                <Meter
                  label={
                    <>
                      {b.name}
                      <div className="muted">
                        {b.people} чел. · {b.requests}{' '}
                        {plural(b.requests, 'заявка', 'заявки', 'заявок')}
                      </div>
                    </>
                  }
                  value={b.load_pct}
                  mark={data.settings.target_load_pct}
                  low={b.status === 'surplus'}
                  max={Math.max(100, ...data.brigades.map((x) => x.load_pct ?? 0))}
                />
              </button>
            ))}
            <p className="muted small-text">
              С учётом дороги до школ. Оранжевым — бригада недогружена, людей в ней больше, чем
              нужно на эти заявки. Нажмите на бригаду — откроется подробно.
            </p>
          </>
        )}
      </Card>
    </div>
  )
}

const SETTING_TITLES: [keyof WorkloadSettings, string, string][] = [
  [
    'requests_share_pct',
    'Доля времени хозотдела школы на заявки, %',
    'остальное — плановые обходы, сезонные и регламентные работы',
  ],
  ['target_load_pct', 'Нормальная загрузка, %', 'ниже — простаивают, выше — не успевают'],
  ['hours_per_day', 'Рабочих часов в день на человека', 'без обеда и оформления'],
  ['default_hours', 'Часов на заявку без оценки', ''],
  ['travel_speed_kmh', 'Скорость бригады в дороге, км/ч', 'для времени на выезды'],
  ['min_people', 'Минимум людей в школе или бригаде', ''],
]

/** Нормы загрузки хозотдела и бригад — их задаёт управление образования. */
function SettingsForm({
  settings,
  onClose,
  onSaved,
}: {
  settings: WorkloadSettings
  onClose: () => void
  onSaved: () => void
}) {
  const [d, setD] = useState<Record<string, string>>(
    Object.fromEntries(
      SETTING_TITLES.map(([key]) => [key, String(settings[key]).replace('.', ',')]),
    ),
  )
  async function save() {
    const body: Record<string, number> = {}
    for (const [key, title] of SETTING_TITLES) {
      const value = Number(d[key].replace(',', '.'))
      if (!Number.isFinite(value)) throw new Error(`«${title}» — нужно число`)
      body[key] = value
    }
    await api('/staffing/workload/settings', { method: 'PUT', body })
    onSaved()
    onClose()
  }
  return (
    <Modal title="Нормы загрузки хозотдела" onClose={onClose}>
      <Form onSubmit={save}>
        {SETTING_TITLES.map(([key, title, hint]) => (
          <Field key={key} label={title}>
            <input
              inputMode="decimal"
              value={d[key]}
              onChange={(e) => setD({ ...d, [key]: e.target.value })}
            />
            {hint && <small className="muted">{hint}</small>}
          </Field>
        ))}
      </Form>
    </Modal>
  )
}

export function Maintenance({ meta, year }: { meta: StaffingMeta; year: string }) {
  const [days, setDays] = useState(90)
  const [view, setView] = useState<'board' | 'calc'>('board')
  const state = useApi<MaintenanceSimple>('/program/maintenance', { year, days })
  const board = useApi<Board>(view === 'board' ? '/program/requests' : null, { days })
  const [editing, setEditing] = useState<MaintenanceRow | null>(null)
  const [norms, setNorms] = useState(false)
  const [detail, setDetail] = useState<DetailTarget | null>(null)
  const reload = () => void state.reload({ silent: true })
  const single = meta.organization !== null

  return (
    <Async state={state}>
      {(data) => {
        const own = data.schools.filter((s) => s.status !== 'brigade')
        const served = data.schools.filter((s) => s.status === 'brigade')
        return (
          <>
            <div className="toolbar">
              <Segmented
                label="Вид"
                value={view}
                onChange={setView}
                options={[
                  ['board', 'Заявки и загрузка'],
                  ['calc', 'Расчёт ставок'],
                ]}
              />
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                aria-label="Период"
              >
                {data.periods.map((d) => (
                  <option key={d} value={d}>
                    Заявки за {d === 365 ? 'год' : `${d} дней`}
                  </option>
                ))}
              </select>
            </div>
            <Reveal id={view}>
              {view === 'board' && (
                <>
                  <Async state={board}>{(b) => <RequestsBoard data={b} />}</Async>
                  <StaffPanel data={data} single={single} onOpen={setDetail} />
                </>
              )}
              {view === 'calc' && (
                <>
                  <div className="rule-box">
                    <div>
                      <strong>Как считаем:</strong> если в школе свой хозотдел — сравниваем его с
                      заявками этой школы. Одна ставка за {data.days} дн. —{' '}
                      {fmtInt(data.full_hours)} ч работы. Заявки — только{' '}
                      {fmt(data.settings.requests_share_pct)} % этого времени, остальное — плановые
                      обходы, сезонные и регламентные работы. При нормальной загрузке{' '}
                      {fmt(data.settings.target_load_pct)} % одна ставка берёт{' '}
                      {fmtInt(data.rate_hours)} ч заявок. Нужно = часы заявок ÷{' '}
                      {fmtInt(data.rate_hours)}, но не меньше {fmt(data.settings.min_people)}. Если
                      своего хозотдела нет — школу обслуживает бригада управления, и считаем бригаду
                      целиком: у неё вся работа — заявки и дорога.
                    </div>
                    {meta.permissions.edit_workload && (
                      <button className="ghost small" onClick={() => setNorms(true)}>
                        <Icon name="edit" size={14} /> Изменить нормы
                      </button>
                    )}
                  </div>
                  {single && data.schools[0] ? (
                    <Card
                      title={data.schools[0].organization}
                      aside={
                        data.can_edit && (
                          <button className="primary" onClick={() => setEditing(data.schools[0])}>
                            <Icon name="edit" size={16} /> Ставки хозотдела
                          </button>
                        )
                      }
                    >
                      <div className="calc-big">
                        <Verdict status={data.schools[0].status} diff={data.schools[0].diff} big />
                      </div>
                      <SchoolCalc row={data.schools[0]} data={data} />
                      {data.schools[0].people.length > 0 && (
                        <p className="muted small-text">
                          В системе: {data.schools[0].people.join(', ')}
                        </p>
                      )}
                    </Card>
                  ) : (
                    <>
                      <Card title={`Школы со своим хозотделом: ${own.length}`}>
                        {own.length === 0 ? (
                          <Empty>Ни одна школа не внесла ставки своего хозотдела.</Empty>
                        ) : (
                          <table className="stack staffing-table">
                            <thead>
                              <tr>
                                <th>Школа</th>
                                <th className="num">Ставок</th>
                                <th className="num">Заявок</th>
                                <th className="num">Часов</th>
                                <th className="num">Нужно</th>
                                <th>Итог</th>
                                {data.can_edit && <th />}
                              </tr>
                            </thead>
                            <tbody>
                              {own.map((r) => (
                                <tr
                                  key={r.organization_id}
                                  className="clickable"
                                  onClick={() => setDetail({ organization: r.organization_id })}
                                >
                                  <td data-label="Школа">
                                    <strong>{r.organization}</strong>
                                    {r.people.length > 0 && (
                                      <div className="muted small-text">{r.people.join(', ')}</div>
                                    )}
                                  </td>
                                  <td data-label="Ставок" className="num">
                                    {fmt(r.have)}
                                  </td>
                                  <td data-label="Заявок" className="num">
                                    {r.requests}
                                  </td>
                                  <td data-label="Часов" className="num">
                                    {fmt(r.hours)}
                                  </td>
                                  <td data-label="Нужно" className="num">
                                    {fmt(r.need)}
                                  </td>
                                  <td data-label="Итог">
                                    <Verdict status={r.status} diff={r.diff} />
                                  </td>
                                  {data.can_edit && (
                                    <td className="row-action">
                                      <button
                                        className="ghost icon"
                                        aria-label="Ставки"
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          setEditing(r)
                                        }}
                                      >
                                        <Icon name="edit" size={15} />
                                      </button>
                                    </td>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </Card>
                      <Card title={`Школы без своего хозотдела: ${served.length}`}>
                        <p className="card-sub">Их обслуживают бригады управления.</p>
                        <ul className="cut-list">
                          {served.map((r) => (
                            <li key={r.organization_id}>
                              <span>
                                <button
                                  className="link-button"
                                  onClick={() => setDetail({ organization: r.organization_id })}
                                >
                                  <strong>{r.organization}</strong>
                                </button>
                                <span className="muted">
                                  {r.brigades.length
                                    ? r.brigades.join(', ')
                                    : 'бригада не закреплена'}
                                </span>
                              </span>
                              <span className="num">
                                <span className="muted">
                                  {r.brigade_requests}{' '}
                                  {plural(r.brigade_requests, 'заявка', 'заявки', 'заявок')}
                                </span>
                                {data.can_edit && (
                                  <button className="ghost small" onClick={() => setEditing(r)}>
                                    есть свой хозотдел
                                  </button>
                                )}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </Card>
                    </>
                  )}
                  {!single && <Brigades data={data} onOpen={setDetail} />}
                </>
              )}
            </Reveal>
            {detail && (
              <MaintenanceDetail
                target={detail}
                days={days}
                year={year}
                onClose={() => setDetail(null)}
              />
            )}
            {norms && (
              <SettingsForm
                settings={data.settings}
                onClose={() => setNorms(false)}
                onSaved={reload}
              />
            )}
            {editing && (
              <StaffForm
                row={editing}
                year={year}
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
