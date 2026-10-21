import { MaintenanceDetail as Detail, RequestSummary } from '../../api'
import { fmt, fmtDateTime, fmtInt, plural, REQUEST_STATUS, useApi } from '../../lib'
import { Meter } from '../charts'
import { Async, Badge, Drawer, Empty } from '../ui'
import { Formula, st, Verdict } from './Simple'

export type DetailTarget = { brigade: number } | { organization: number }

const word = (n: number) => plural(n, 'заявка', 'заявки', 'заявок')

function Topics({ requests }: { requests: RequestSummary }) {
  if (!requests.by_topic.length) return null
  const peak = Math.max(...requests.by_topic.map((t) => t.hours), 1)
  return (
    <>
      <h3 className="board-sub">Что чинили</h3>
      {requests.by_topic.map((t) => (
        <Meter
          key={t.topic}
          label={
            <>
              {t.title}
              <div className="muted">
                {t.count} {word(t.count)}
              </div>
            </>
          }
          value={t.hours}
          max={peak}
          suffix=" ч"
        />
      ))}
    </>
  )
}

function Recent({ requests, title }: { requests: RequestSummary; title: string }) {
  if (!requests.recent.length) return null
  return (
    <>
      <h3 className="board-sub">{title}</h3>
      <ul className="detail-requests">
        {requests.recent.map((r) => (
          <li key={r.id}>
            <span>
              <strong>{r.title}</strong>
              <span className="muted">
                № {r.id} · {r.organization} · {fmtDateTime(r.created_at)}
                {r.assignee && ` · ${r.assignee}`}
              </span>
            </span>
            <span className="detail-requests-side">
              <Badge tone={REQUEST_STATUS[r.status]?.tone ?? 'gray'}>{r.status_title}</Badge>
              <span className={r.overdue ? 'delta-minus' : 'muted'}>
                {r.overdue ? 'просрочена' : `${fmt(r.hours)} ч`}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}

function Counts({ requests, days }: { requests: RequestSummary; days: number }) {
  return (
    <dl className="board-facts">
      <div>
        <dt>Заявок за {days} дн.</dt>
        <dd>{fmtInt(requests.count)}</dd>
      </div>
      <div>
        <dt>Часов работы</dt>
        <dd>{fmt(requests.hours)}</dd>
      </div>
      <div>
        <dt>В работе</dt>
        <dd>{requests.active}</dd>
      </div>
      <div>
        <dt>Просрочено</dt>
        <dd className={requests.overdue ? 'dev-deficit' : ''}>{requests.overdue}</dd>
      </div>
      <div>
        <dt>В срок</dt>
        <dd>{requests.in_time_pct === null ? '—' : `${requests.in_time_pct} %`}</dd>
      </div>
    </dl>
  )
}

function BrigadeView({ d }: { d: Detail }) {
  const u = d.unit!
  const w = d.workdays ?? 0
  const s = d.settings
  const personHours = w * s.hours_per_day
  return (
    <>
      <p className="muted">
        {d.base_address ? `База: ${d.base_address}. ` : ''}Обслуживает {u.organizations.length}{' '}
        {plural(u.organizations.length, 'школу', 'школы', 'школ')}, в бригаде {u.people}{' '}
        {plural(u.people, 'человек', 'человека', 'человек')}.
      </p>
      <div className="calc-big">
        {u.status === 'surplus' ? (
          <span className="verdict verdict-big dev-surplus">лишние {fmt(u.surplus)} чел.</span>
        ) : u.status === 'overload' ? (
          <span className="verdict verdict-big dev-deficit">не успевают</span>
        ) : (
          <span className="verdict verdict-big dev-calm">загрузка в норме</span>
        )}
      </div>
      <Formula
        lines={[
          <>
            Сколько бригада может отработать: {u.people} чел. × {fmt(w)} рабочих дня ×{' '}
            {fmt(s.hours_per_day)} ч = <strong>{fmtInt(u.capacity_hours)} ч</strong>
          </>,
          <>
            Сколько работы пришло: {u.requests} {word(u.requests)} — {fmt(u.work_hours)} ч + дорога{' '}
            {fmt(u.travel_hours)} ч = <strong>{fmt(u.total_hours)} ч</strong>
          </>,
          <>
            Загрузка: {fmt(u.total_hours)} ÷ {fmtInt(u.capacity_hours)} ={' '}
            <strong>{fmt(u.load_pct)} %</strong> (норма {fmt(s.target_load_pct)} %)
          </>,
          <>
            Нужно людей: {fmt(u.total_hours)} ÷ ({fmt(w)} × {fmt(s.hours_per_day)} ×{' '}
            {fmt(s.target_load_pct)} %) → вверх до 0,5 = <strong>{fmt(u.needed)}</strong>
          </>,
        ]}
        result={
          <>
            есть {u.people}, нужно {fmt(u.needed)}
            {u.candidates.length > 0 && ` · меньше всех загружены: ${u.candidates.join(', ')}`}
          </>
        }
      />
      <Counts requests={d.requests} days={d.days} />

      <h3 className="board-sub">Кто в бригаде</h3>
      {u.members.length === 0 ? (
        <Empty>В бригаде никого нет.</Empty>
      ) : (
        u.members.map((m) => (
          <Meter
            key={m.id}
            label={
              <>
                {m.name}
                <div className="muted">
                  {m.requests} {word(m.requests)} · {fmt(m.hours)} ч
                </div>
              </>
            }
            value={personHours ? Math.round((m.hours / personHours) * 1000) / 10 : null}
            mark={s.target_load_pct}
            max={Math.max(100, ...u.members.map((x) => (x.hours / (personHours || 1)) * 100))}
          />
        ))
      )}
      <p className="muted small-text">
        Загрузка человека — его часы заявок от {fmtInt(personHours)} ч рабочего времени за период,
        без дороги.
      </p>

      <h3 className="board-sub">Школы</h3>
      <table className="stack staffing-table">
        <thead>
          <tr>
            <th>Школа</th>
            <th className="num">Заявок</th>
            <th className="num">Выездов</th>
            <th className="num">От базы, км</th>
            <th className="num">Часов</th>
          </tr>
        </thead>
        <tbody>
          {u.organizations.map((o) => (
            <tr key={o.id}>
              <td data-label="Школа">{o.name}</td>
              <td data-label="Заявок" className="num">
                {o.requests || <span className="muted">—</span>}
              </td>
              <td data-label="Выездов" className="num">
                {o.trips || <span className="muted">—</span>}
              </td>
              <td data-label="От базы" className="num">
                {o.distance_km === null ? '?' : fmt(o.distance_km)}
              </td>
              <td data-label="Часов" className="num">
                {o.hours ? fmt(o.hours) : <span className="muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {u.distance_unknown && (
        <p className="muted small-text">У части школ нет координат — дорога до них не посчитана.</p>
      )}
      <Topics requests={d.requests} />
      <Recent requests={d.requests} title="Последние заявки бригады" />
    </>
  )
}

function SchoolView({ d }: { d: Detail }) {
  const r = d.row!
  const s = d.settings
  const own = r.status !== 'brigade'
  return (
    <>
      <div className="calc-big">
        <Verdict status={r.status} diff={r.diff} big />
      </div>
      {own ? (
        <Formula
          lines={[
            <>
              Одна ставка за {d.days} дн. — {fmtInt(d.full_hours ?? 0)} ч работы. На заявки из них{' '}
              {fmt(s.requests_share_pct)} %, остальное — плановые обходы и сезонные работы
            </>,
            <>
              При нормальной загрузке {fmt(s.target_load_pct)} % одна ставка берёт{' '}
              <strong>{fmtInt(d.rate_hours ?? 0)} ч заявок</strong>
            </>,
            <>
              Заявок своему хозотделу: {r.requests} {word(r.requests)} ={' '}
              <strong>{fmt(r.hours)} ч</strong>
            </>,
            <>
              {fmt(r.hours)} ÷ {fmtInt(d.rate_hours ?? 0)} → нужно <strong>{st(r.need)}</strong>
              {r.need === s.min_people && ' (минимум)'}
            </>,
          ]}
          result={
            <>
              есть <strong>{st(r.have)}</strong> → <Verdict status={r.status} diff={r.diff} />
              {r.load_pct !== null && (
                <span className="muted"> · загрузка {fmt(r.load_pct)} %</span>
              )}
            </>
          }
        />
      ) : (
        <p>
          Своего хозотдела нет — школу обслуживает{' '}
          <strong>{r.brigades.join(', ') || 'бригада (не закреплена)'}</strong>.
        </p>
      )}
      <Counts requests={d.requests} days={d.days} />

      {own && (
        <>
          <h3 className="board-sub">Кто работает</h3>
          {r.have !== null && r.people.length > 0 && r.people.length + 0.25 < r.have && (
            <p className="muted small-text">
              Сотрудников в системе — {r.people.length}, а ставок {fmt(r.have)}: заявки остальных
              рабочих записаны на тех, кто заведён. Загрузку по людям здесь не сравнить, и сокращать
              «по загрузке» система не предлагает.
            </p>
          )}
          {(d.people ?? []).length === 0 ? (
            <Empty>Сотрудники хозотдела в системе не заведены.</Empty>
          ) : (
            <table className="stack staffing-table">
              <thead>
                <tr>
                  <th>Сотрудник</th>
                  <th className="num">Заявок</th>
                  <th className="num">Часов</th>
                </tr>
              </thead>
              <tbody>
                {(d.people ?? []).map((p) => (
                  <tr key={p.name}>
                    <td data-label="Сотрудник">{p.name}</td>
                    <td data-label="Заявок" className="num">
                      {p.requests}
                    </td>
                    <td data-label="Часов" className="num">
                      {fmt(p.hours)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      <Topics requests={d.requests} />
      <Recent requests={d.requests} title="Последние заявки" />
      {d.brigade_requests && d.brigade_requests.count > 0 && (
        <>
          <h3 className="board-sub">Сложные работы — бригада управления</h3>
          <p className="muted">
            {r.brigades.join(', ') || 'Бригада'}: {d.brigade_requests.count}{' '}
            {word(d.brigade_requests.count)} за {d.days} дн., {fmt(d.brigade_requests.hours)} ч. Эти
            часы считаются в загрузке бригады, а не школы.
          </p>
        </>
      )}
    </>
  )
}

/** Подробно про бригаду управления или свой хозотдел школы. */
export function MaintenanceDetail({
  target,
  days,
  year,
  onClose,
}: {
  target: DetailTarget
  days: number
  year: string
  onClose: () => void
}) {
  const query: Record<string, string | number | null> =
    'brigade' in target
      ? { brigade_id: target.brigade, days }
      : { organization_id: target.organization, days, year }
  const state = useApi<Detail>('/program/maintenance/detail', query)
  return (
    <Drawer
      title={
        <>
          <strong>{state.data?.name ?? '…'}</strong>
          <div className="muted small-text">
            {'brigade' in target ? 'Бригада управления' : 'Хозотдел школы'} · заявки за {days} дн.
          </div>
        </>
      }
      onClose={onClose}
      wide
    >
      <Async state={state}>
        {(d) => (d.kind === 'brigade' ? <BrigadeView d={d} /> : <SchoolView d={d} />)}
      </Async>
    </Drawer>
  )
}
