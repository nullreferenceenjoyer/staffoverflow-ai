import { useState } from 'react'

import {
  api,
  CleaningRow,
  CleaningSimple,
  ProgramPositions,
  RequestsBoard as Board,
  StaffingMeta,
} from '../../api'
import { Legend, Meter } from '../../components/charts'
import { Icon } from '../../components/icons'
import { FlowChart, RequestKpis } from '../../components/staffing/RequestsBoard'
import { Formula, st, Verdict } from '../../components/staffing/Simple'
import { Async, Card, Empty, Field, Form, Modal, Reveal, Segmented } from '../../components/ui'
import { fmt, fmtInt, plural, useApi } from '../../lib'

const num = (value: string) => {
  const text = value.trim().replace(/\s/g, '').replace(',', '.')
  if (!text) return null
  const parsed = Number(text)
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error(`«${value}» — не число`)
  return parsed
}
const input = (value: number | null) => (value === null ? '' : String(value).replace('.', ','))

/** Как получилось «нужно»: две строки деления и выбор большего. */
function Calc({ row, norm }: { row: CleaningRow; norm: CleaningSimple['norm'] }) {
  const lines = []
  if (row.classes)
    lines.push(
      <>
        {fmtInt(row.classes)} классов ÷ {fmt(norm.classes_per_rate)} ={' '}
        <strong>{fmt(row.by_classes)}</strong>
      </>,
    )
  if (row.area)
    lines.push(
      <>
        {fmtInt(row.area)} м² ÷ {fmtInt(norm.area_per_rate)} = <strong>{fmt(row.by_area)}</strong>
      </>,
    )
  if (!lines.length) return <p className="muted">Внесите число классов и площадь.</p>
  return (
    <Formula
      lines={lines}
      result={
        <>
          Нужно <strong>{st(row.need)}</strong>
          {lines.length > 1 && ' (берём большее, с округлением вверх до 0,25)'}
          {row.have !== null && (
            <>
              {' '}
              · есть <strong>{st(row.have)}</strong> →{' '}
              <Verdict status={row.status} diff={row.diff} />
            </>
          )}
        </>
      }
    />
  )
}

function InputForm({
  row,
  year,
  onClose,
  onSaved,
}: {
  row: CleaningRow
  year: string
  onClose: () => void
  onSaved: () => void
}) {
  const [d, setD] = useState({
    classes: input(row.classes),
    area: input(row.area),
    have: input(row.have),
  })
  async function save() {
    const classes = num(d.classes)
    if (classes !== null && !Number.isInteger(classes)) throw new Error('Классы — целое число')
    await api(`/program/cleaning/${row.organization_id}`, {
      method: 'PUT',
      body: { year, classes_count: classes, total_area_m2: num(d.area), cleaners_fte: num(d.have) },
    })
    onSaved()
    onClose()
  }
  return (
    <Modal title={row.organization} onClose={onClose}>
      <Form onSubmit={save}>
        <div className="row">
          <Field label="Классов">
            <input
              inputMode="numeric"
              value={d.classes}
              onChange={(e) => setD({ ...d, classes: e.target.value })}
            />
          </Field>
          <Field label="Площадь, м²">
            <input
              inputMode="decimal"
              value={d.area}
              onChange={(e) => setD({ ...d, area: e.target.value })}
            />
          </Field>
          <Field label="Ставок уборщиц сейчас">
            <input
              inputMode="decimal"
              value={d.have}
              onChange={(e) => setD({ ...d, have: e.target.value })}
            />
          </Field>
        </div>
        <p className="muted">
          Ставки уборщиц — сколько их в штатке школы сейчас (с гардеробщиками, если они убирают).
        </p>
      </Form>
    </Modal>
  )
}

function NormForm({
  norm,
  onClose,
  onSaved,
}: {
  norm: CleaningSimple['norm']
  onClose: () => void
  onSaved: () => void
}) {
  const [d, setD] = useState({
    classes: input(norm.classes_per_rate),
    area: input(norm.area_per_rate),
  })
  async function save() {
    await api('/program/cleaning-norm', {
      method: 'PUT',
      body: { classes_per_rate: num(d.classes), area_per_rate: num(d.area) },
    })
    onSaved()
    onClose()
  }
  return (
    <Modal title="Норма уборщиц" onClose={onClose}>
      <Form onSubmit={save}>
        <div className="row">
          <Field label="Классов на одну ставку">
            <input
              inputMode="decimal"
              value={d.classes}
              onChange={(e) => setD({ ...d, classes: e.target.value })}
            />
          </Field>
          <Field label="М² на одну ставку">
            <input
              inputMode="decimal"
              value={d.area}
              onChange={(e) => setD({ ...d, area: e.target.value })}
            />
          </Field>
        </div>
      </Form>
    </Modal>
  )
}

const VERDICTS = [
  { key: 'surplus', label: 'лишние ставки', color: 'var(--serious)' },
  { key: 'normal', label: 'в норме', color: 'var(--good)' },
  { key: 'deficit', label: 'не хватает', color: 'var(--critical)' },
  { key: 'no_data', label: 'не внесли цифры', color: 'var(--series-muted)' },
] as const

/** Заявки на уборку — видно, справляются ли уборщицы, которые есть. */
function CleaningRequests() {
  const state = useApi<Board>('/program/requests', { topic: 'cleaning', days: 90 })
  return (
    <Card title="Заявки на уборку за 90 дней">
      <Async state={state}>
        {(b) =>
          b.total === 0 ? (
            <Empty>Заявок на уборку не было.</Empty>
          ) : (
            <>
              <RequestKpis data={b} />
              <FlowChart data={b} height={180} />
            </>
          )
        }
      </Async>
    </Card>
  )
}

function SchoolList({ items }: { items: CleaningRow[] }) {
  if (!items.length) return <p className="muted">Нет.</p>
  return (
    <ul className="cut-list">
      {items.map((i) => (
        <li key={i.organization_id}>
          <span>
            <strong>{i.organization}</strong>
            <span className="muted">
              нужно {fmt(i.need)}, есть {fmt(i.have)}
            </span>
          </span>
          <Verdict status={i.status} diff={i.diff} />
        </li>
      ))}
    </ul>
  )
}

function CleanersBoard({ data }: { data: CleaningSimple }) {
  const t = data.totals
  const count = (key: string) => data.items.filter((i) => i.status === key).length
  const schools = (n: number) => `в ${n} ${plural(n, 'школе', 'школах', 'школах')}`
  // Сколько м² приходится на одну ставку: меньше нормы — уборщиц больше, чем нужно
  const perRate = data.items
    .filter((i) => i.status !== 'no_data' && i.have && i.area)
    .map((i) => ({ ...i, per: (i.area ?? 0) / (i.have ?? 1) }))
    .sort((a, b) => a.per - b.per)
  const peak = Math.max(data.norm.area_per_rate * 1.5, ...perRate.map((i) => i.per))
  const surplus = data.items.filter((i) => i.status === 'surplus').slice(0, 6)
  const deficit = data.items
    .filter((i) => i.status === 'deficit')
    .sort((a, b) => (a.diff ?? 0) - (b.diff ?? 0))
    .slice(0, 6)
  return (
    <>
      <div className="kpis">
        <div className="kpi">
          <span className="kpi-label">Школ с данными</span>
          <strong>
            {t.filled} из {t.schools}
          </strong>
          <span className="kpi-note">остальные ещё не внесли 3 цифры</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Нужно по норме</span>
          <strong>{fmt(t.need)}</strong>
          <span className="kpi-note">есть {st(t.have)}</span>
        </div>
        <div className="kpi tone-warn">
          <span className="kpi-label">Лишние ставки</span>
          <strong>{fmt(t.surplus)}</strong>
          <span className="kpi-note">{schools(count('surplus'))}</span>
        </div>
        <div className="kpi tone-critical">
          <span className="kpi-label">Не хватает</span>
          <strong>{fmt(t.deficit)}</strong>
          <span className="kpi-note">{schools(count('deficit'))}</span>
        </div>
      </div>
      <div className="grid-wide">
        <Card title="Сколько метров убирает одна ставка">
          <p className="card-sub">
            Площадь школы ÷ ставки уборщиц. Черта — норма {fmtInt(data.norm.area_per_rate)} м².
            Левее черты — уборщиц больше, чем нужно по площади.
          </p>
          {perRate.length === 0 ? (
            <Empty>Ни одна школа ещё не внесла площадь и ставки.</Empty>
          ) : (
            perRate
              .slice(0, 14)
              .map((i) => (
                <Meter
                  key={i.organization_id}
                  label={i.organization}
                  value={Math.round(i.per)}
                  max={peak}
                  mark={data.norm.area_per_rate}
                  low={i.status === 'surplus'}
                  suffix=" м²"
                />
              ))
          )}
        </Card>
        <Card title="Школы по итогу">
          <div className="statusbar">
            {VERDICTS.filter((v) => count(v.key)).map((v) => (
              <i
                key={v.key}
                style={{ flex: count(v.key), background: v.color }}
                title={`${v.label}: ${count(v.key)}`}
              />
            ))}
          </div>
          <Legend items={VERDICTS.map((v) => [`${v.label} · ${count(v.key)}`, v.color])} />
          <h3 className="board-sub">Больше всего лишних</h3>
          <SchoolList items={surplus} />
          <h3 className="board-sub">Не хватает</h3>
          <SchoolList items={deficit} />
        </Card>
      </div>
      <CleaningRequests />
    </>
  )
}

export function Cleaners({ meta, year }: { meta: StaffingMeta; year: string }) {
  const state = useApi<CleaningSimple>('/program/cleaning', { year })
  const positions = useApi<ProgramPositions>('/program/positions')
  const [editing, setEditing] = useState<CleaningRow | null>(null)
  const [norm, setNorm] = useState(false)
  const [view, setView] = useState<'board' | 'table'>('board')
  const fact = positions.data?.categories
    .flatMap((c) => c.items)
    .find((i) => i.name === 'Уборщик служебных помещений')
  const reload = () => void state.reload({ silent: true })
  const single = meta.organization !== null

  return (
    <Async state={state}>
      {(data) => (
        <>
          <div className="rule-box">
            <div>
              <strong>Как считаем:</strong> нужно ставок уборщиц = большее из двух чисел —{' '}
              <strong>классы ÷ {fmt(data.norm.classes_per_rate)}</strong> и{' '}
              <strong>площадь ÷ {fmtInt(data.norm.area_per_rate)} м²</strong>. Есть больше, чем
              нужно, — лишние ставки; меньше — не хватает. Разница до {fmt(data.tolerance)} ставки —
              норма.
            </div>
            {data.can_edit_norm && (
              <button className="ghost small" onClick={() => setNorm(true)}>
                <Icon name="edit" size={14} /> Изменить норму
              </button>
            )}
          </div>
          {fact && !single && (
            <p className="muted">
              По расчёту управления уборщиков служебных помещений в округе было {fmt(fact.before)},
              стало {fmt(fact.after)} (−{fmt(fact.cut)}).
            </p>
          )}
          {single ? (
            data.items[0] && (
              <Card
                title={data.items[0].organization}
                aside={
                  data.can_edit && (
                    <button className="primary" onClick={() => setEditing(data.items[0])}>
                      <Icon name="edit" size={16} /> Внести цифры
                    </button>
                  )
                }
              >
                <div className="calc-big">
                  <Verdict status={data.items[0].status} diff={data.items[0].diff} big />
                </div>
                <Calc row={data.items[0]} norm={data.norm} />
                <SchoolFacts row={data.items[0]} />
              </Card>
            )
          ) : (
            <>
              <div className="toolbar">
                <Segmented
                  label="Вид"
                  value={view}
                  onChange={setView}
                  options={[
                    ['board', 'Сводка'],
                    ['table', 'Все школы'],
                  ]}
                />
              </div>
              <Reveal id={view}>
                {view === 'board' && <CleanersBoard data={data} />}
                {view === 'table' && (
                  <Card>
                    <table className="stack staffing-table">
                      <thead>
                        <tr>
                          <th>Школа</th>
                          <th className="num">Классов</th>
                          <th className="num">Площадь, м²</th>
                          <th className="num">Нужно</th>
                          <th className="num">Есть</th>
                          <th>Итог</th>
                          {data.can_edit && <th />}
                        </tr>
                      </thead>
                      <tbody>
                        {data.items.map((r) => (
                          <tr key={r.organization_id}>
                            <td data-label="Школа">
                              <strong>{r.organization}</strong>
                            </td>
                            <td data-label="Классов" className="num">
                              {r.classes ?? <span className="muted">—</span>}
                            </td>
                            <td data-label="Площадь" className="num">
                              {r.area ? fmtInt(r.area) : <span className="muted">—</span>}
                            </td>
                            <td data-label="Нужно" className="num">
                              {fmt(r.need)}
                            </td>
                            <td data-label="Есть" className="num">
                              {fmt(r.have)}
                            </td>
                            <td data-label="Итог">
                              <Verdict status={r.status} diff={r.diff} />
                              {r.missing.length > 0 && (
                                <div className="muted small-text">нет: {r.missing.join(', ')}</div>
                              )}
                            </td>
                            {data.can_edit && (
                              <td className="row-action">
                                <button
                                  className="ghost icon"
                                  aria-label="Внести цифры"
                                  onClick={() => setEditing(r)}
                                >
                                  <Icon name="edit" size={15} />
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                )}
              </Reveal>
            </>
          )}
          {single && <CleaningRequests />}
          {data.items.length === 0 && <Empty>Школ нет.</Empty>}
          {editing && (
            <InputForm
              row={editing}
              year={year}
              onClose={() => setEditing(null)}
              onSaved={reload}
            />
          )}
          {norm && <NormForm norm={data.norm} onClose={() => setNorm(false)} onSaved={reload} />}
        </>
      )}
    </Async>
  )
}

function SchoolFacts({ row }: { row: CleaningRow }) {
  return (
    <dl className="bucket-facts school-facts">
      <dt>Уборщиц в системе</dt>
      <dd>{row.people.length ? row.people.join(', ') : 'не заведены'}</dd>
      {row.missing.length > 0 && (
        <>
          <dt>Не хватает данных</dt>
          <dd>{row.missing.join(', ')}</dd>
        </>
      )}
    </dl>
  )
}
