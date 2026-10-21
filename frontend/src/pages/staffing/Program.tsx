import { useMemo, useState } from 'react'

import {
  CleaningSimple,
  MaintenanceSimple,
  StaffingMeta,
  StaffingSummary,
  SummaryBucket,
  SummarySchool,
} from '../../api'
import { Icon } from '../../components/icons'
import { ActionCard, HowItWorks, RulesHelp } from '../../components/staffing/HowItWorks'
import { st, Verdict } from '../../components/staffing/Simple'
import { Async, Badge, Card, Empty } from '../../components/ui'
import { fmt, fmtDate, fmtInt, fmtRubShort, plural, useApi } from '../../lib'

type Go = (tab: 'positions' | 'cleaners' | 'maintenance' | 'schedule') => void

const KIND_TITLE = {
  cut_vacant: 'убрать вакансии',
  reduce_load: 'уменьшить нагрузку',
  cut: 'сократить',
  cut_by_load: 'сократить по загрузке',
  hire: 'не хватает',
  data: 'внести данные',
} as const

type Way = 'cut_vacant' | 'reduce_load' | 'cut'

/** Должности, где этот шаг высвобождает больше всего. */
function topFor(data: StaffingSummary, kind: Way) {
  return data.positions
    .filter((p) => p[kind] > 0)
    .sort((a, b) => b[kind] - a[kind])
    .slice(0, 4)
    .map((p) => `${p.position} — ${fmt(p[kind])}`)
    .join(', ')
}

/**
 * Кого касается и почему. Шаги идут в том порядке, в котором система высвобождает
 * лишние ставки: сначала то, что никого не задевает, людей — только в конце.
 */
function WhoAndWhy({ data }: { data: StaffingSummary }) {
  const h = data.headline
  const required = data.buckets.reduce((sum, b) => sum + b.required, 0)
  const approved = data.buckets.reduce((sum, b) => sum + b.approved, 0)
  const units = h.staff_units
  const steps: { kind: Way; title: string; who: string; why: string }[] = [
    {
      kind: 'cut_vacant',
      title: 'Убираем пустые ставки',
      who: 'Никого. На этих ставках сейчас никто не работает — это вакансии.',
      why: 'Ставки записаны в штатке, но по нормативу они не нужны. Держать их — значит держать под них фонд оплаты труда, поэтому убираем их первыми.',
    },
    {
      kind: 'reduce_load',
      title: 'Снимаем совмещение',
      who: 'Сотрудников, которые работают больше чем на одну ставку: совмещают вторую должность или берут дополнительную нагрузку. С работы они не уходят — остаются на своей основной ставке, уходит только доплата.',
      why: 'Пустых ставок не хватило, а работы по нормативу всё равно меньше, чем занято ставок. Прежде чем сокращать кого-то, снимаем то, что люди берут сверх своей ставки, — так никто не теряет место.',
    },
    {
      kind: 'cut',
      title: 'Сокращаем занятые ставки',
      who: `Сотрудников, которые занимают ставки сверх норматива: ${units} ${plural(units, 'штатная единица', 'штатные единицы', 'штатных единиц')} (${st(h.cut)}). С каждым — по процедуре сокращения: уведомление за 2 месяца и предложение вакансий.`,
      why: 'Даже без вакансий и совмещений людей на ставках больше, чем положено по нормативу. Это остаток, по нему руководитель принимает решение: система только показывает расчёт.',
    },
  ]
  return (
    <div className="who-why">
      <p className="who-why-intro">
        {required > 0 && (
          <>
            По нормативу нужно <strong>{st(Math.round(required * 100) / 100)}</strong>, в штатке —{' '}
            <strong>{fmt(Math.round(approved * 100) / 100)}</strong>.{' '}
          </>
        )}
        Лишние ставки высвобождаем по шагам: сначала то, что никого не задевает, и только в конце —
        людей.
        {h.brigade_cut > 0 &&
          ` Отдельно — ${st(h.brigade_cut)} в бригадах управления: заявок им приходит меньше, чем людей в бригаде.`}
      </p>
      <ol className="who-why-steps">
        {steps.map((s, i) => {
          const value = h[s.kind]
          const top = value ? topFor(data, s.kind) : ''
          return (
            <li key={s.kind} className={value ? '' : 'is-empty'}>
              <span className="who-why-num">{i + 1}</span>
              <div>
                <div className="who-why-head">
                  <strong>{s.title}</strong>
                  <span>{value ? st(value) : 'не нужно'}</span>
                </div>
                {value > 0 && (
                  <dl>
                    <dt>Кого касается</dt>
                    <dd>{s.who}</dd>
                    <dt>Почему</dt>
                    <dd>{s.why}</dd>
                    {top && (
                      <>
                        <dt>Больше всего</dt>
                        <dd>{top}</dd>
                      </>
                    )}
                  </dl>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Hero({ data, title, sub }: { data: StaffingSummary; title: string; sub: string }) {
  const h = data.headline
  const plan = data.plan
  const matches = plan?.total !== undefined && Math.abs(plan.total - h.total) < 0.011
  return (
    <div className="program-hero">
      <div className="program-hero-head">
        <span>{sub}</span>
        {plan?.total !== undefined ? (
          <Badge tone={matches ? 'green' : 'amber'}>
            {matches
              ? `✓ сходится с расчётом УО: ${fmt(plan.total)} ставки`
              : `в расчёте УО ${fmt(plan.total)} ставки`}
          </Badge>
        ) : null}
      </div>
      <div className="program-figures">
        <div>
          <strong>{fmt(h.total)}</strong>
          <span>{title}</span>
          <small>в {h.schools_with_cut} школах</small>
        </div>
        <div>
          <strong>{h.staff_units}</strong>
          <span>сокращений (шт. ед.)</span>
          <small>{st(h.cut)} — это люди, остальное без увольнений</small>
        </div>
        <div>
          <strong>{fmtRubShort(h.cost)}</strong>
          <span>экономии ФОТ в год</span>
          <small>
            {h.saving_pct !== null && `${fmt(h.saving_pct)} % ФОТ`}
            {plan?.target_pct ? ` при цели ${plan.target_pct} %` : ''}
            {h.taxes_pct ? ` · с налогами ${fmt(h.taxes_pct)} %` : ''}
          </small>
        </div>
        <div>
          <strong>{fmtInt(h.hours)}</strong>
          <span>часов в год</span>
          <small>
            {fmt(h.total)} × {fmtInt(h.hours_per_rate)} ч на ставку
          </small>
        </div>
      </div>
      <WhoAndWhy data={data} />
    </div>
  )
}

function BucketCard({ bucket, onOpen }: { bucket: SummaryBucket; onOpen?: () => void }) {
  return (
    <button className="bucket-card bucket-button" onClick={onOpen} disabled={!onOpen}>
      <div className="bucket-head">
        <strong>{bucket.title}</strong>
        {onOpen && <Icon name="arrow" size={14} />}
      </div>
      <div className="bucket-value">
        {bucket.total ? (
          <span className="dev-surplus">высвободить {st(bucket.total)}</span>
        ) : (
          <span className="dev-calm">лишних нет</span>
        )}
        <small>{fmtRubShort(bucket.total_cost)} в год</small>
      </div>
      <dl className="bucket-facts">
        <dt>Было по штатке</dt>
        <dd>{fmt(bucket.approved)}</dd>
        <dt>По нормативу</dt>
        <dd>{fmt(bucket.required)}</dd>
        <dt>Вакансии / нагрузка / люди</dt>
        <dd>
          {fmt(bucket.cut_vacant)} / {fmt(bucket.reduce_load)} / {fmt(bucket.cut)}
        </dd>
      </dl>
    </button>
  )
}

function SchoolsTable({
  schools,
  onOpen,
}: {
  schools: SummarySchool[]
  onOpen: (id: number) => void
}) {
  const [search, setSearch] = useState('')
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return schools.filter((s) => !needle || s.organization.toLowerCase().includes(needle))
  }, [schools, search])
  const cell = (v: number) => (v ? fmt(v) : <span className="muted">—</span>)
  return (
    <Card title="Где высвобождать">
      <div className="toolbar">
        <input
          type="search"
          placeholder="Поиск школы"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="muted">Нажмите на школу — откроется её штатка по должностям.</span>
      </div>
      <table className="stack staffing-table">
        <thead>
          <tr>
            <th>Школа</th>
            <th className="num">Всего</th>
            <th className="num">Вакансии</th>
            <th className="num">Нагрузка</th>
            <th className="num">Люди</th>
            <th className="num">Экономия в год</th>
            <th>Главное</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((s) => (
            <tr
              key={s.organization_id}
              className="clickable"
              onClick={() => onOpen(s.organization_id)}
            >
              <td data-label="Школа">
                <strong>{s.organization}</strong>
              </td>
              <td data-label="Всего" className="num">
                {s.total ? <strong>{fmt(s.total)}</strong> : <span className="muted">—</span>}
              </td>
              <td data-label="Вакансии" className="num">
                {cell(s.cut_vacant)}
              </td>
              <td data-label="Нагрузка" className="num">
                {cell(s.reduce_load)}
              </td>
              <td data-label="Люди" className="num">
                {cell(s.cut)}
              </td>
              <td data-label="Экономия" className="num">
                {s.cost ? fmtRubShort(s.cost) : <span className="muted">—</span>}
              </td>
              <td data-label="Главное" className="small-text">
                {s.total ? (
                  s.main.map((m) => `${KIND_TITLE[m.kind]}: ${m.group} ${fmt(m.fte)}`).join('; ')
                ) : (
                  <span className="dev-calm">в норме — высвобождать нечего</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

function TopPositions({ data, onMore }: { data: StaffingSummary; onMore: () => void }) {
  return (
    <Card
      title="Какие должности"
      aside={
        <button className="ghost" onClick={onMore}>
          Все должности <Icon name="arrow" size={14} />
        </button>
      }
    >
      <ul className="cut-list">
        {data.positions.slice(0, 10).map((p) => (
          <li key={p.position}>
            <span>
              <strong>{p.position}</strong>
              <span className="muted">
                {[
                  p.cut_vacant ? `вакансии ${fmt(p.cut_vacant)}` : null,
                  p.reduce_load ? `нагрузка ${fmt(p.reduce_load)}` : null,
                  p.cut ? `люди ${fmt(p.cut)}` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </span>
            <span className="num">
              <span className="dev-surplus">−{fmt(p.total)}</span>
              <span className="muted">
                {fmt(p.approved)} → {fmt(p.after)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** Директору: своя школа — что сделать, по порядку экономии. */
function OwnSchool({ data, meta, onGo }: { data: StaffingSummary; meta: StaffingMeta; onGo: Go }) {
  const cleaning = useApi<CleaningSimple>('/program/cleaning')
  const maintenance = useApi<MaintenanceSimple>('/program/maintenance')
  const c = cleaning.data?.items[0]
  const m = maintenance.data?.schools[0]
  const actions = data.actions.filter((a) => a.kind !== 'data')
  return (
    <>
      <Hero
        data={data}
        title="ставки можно высвободить"
        sub={`${meta.organization?.name ?? 'Школа'} · анализ штатки по нормативу`}
      />
      <div className="grid-wide">
        <Card
          title="Что сделать"
          aside={
            <button className="ghost" onClick={() => onGo('schedule')}>
              Штатка школы <Icon name="arrow" size={14} />
            </button>
          }
        >
          {actions.length === 0 ? (
            <Empty>Всё в норме — делать ничего не нужно.</Empty>
          ) : (
            <ol className="action-list">
              {actions.map((a, i) => (
                <ActionCard key={`${a.kind}-${a.group}-${i}`} action={a} />
              ))}
            </ol>
          )}
        </Card>
        <div className="stack-cards">
          <button className="next-card" onClick={() => onGo('cleaners')}>
            <span className="kpi-icon">
              <Icon name="users" size={16} />
            </span>
            <span>
              <strong>Уборщицы</strong>
              <span className="muted">
                {c && c.status !== 'no_data'
                  ? `нужно ${st(c.need)}, есть ${st(c.have)}`
                  : 'внесите классы, площадь и ставки'}
              </span>
            </span>
            {c && <Verdict status={c.status} diff={c.diff} />}
          </button>
          <button className="next-card" onClick={() => onGo('maintenance')}>
            <span className="kpi-icon">
              <Icon name="wrench" size={16} />
            </span>
            <span>
              <strong>Хозотдел</strong>
              <span className="muted">
                {m
                  ? m.status === 'brigade'
                    ? `своего нет — обслуживает ${m.brigades.join(', ') || 'бригада'}`
                    : `${m.requests} заявок за ${maintenance.data?.days} дн., нужно ${st(m.need)}`
                  : '…'}
              </span>
            </span>
            {m && <Verdict status={m.status} diff={m.diff} />}
          </button>
          {data.buckets
            .filter((b) => b.key === 'other' && b.total)
            .map((b) => (
              <div key={b.key} className="next-card">
                <span className="kpi-icon">
                  <Icon name="building" size={16} />
                </span>
                <span>
                  <strong>Остальной персонал</strong>
                  <span className="muted">
                    вакансии {fmt(b.cut_vacant)} · нагрузка {fmt(b.reduce_load)} · люди {fmt(b.cut)}
                  </span>
                </span>
                <span className="dev-surplus">{st(b.total)}</span>
              </div>
            ))}
        </div>
      </div>
    </>
  )
}

export function Program({
  meta,
  onGo,
  onOpenSchool,
}: {
  meta: StaffingMeta
  onGo: Go
  onOpenSchool: (id: number) => void
}) {
  const state = useApi<StaffingSummary>('/staffing/summary')
  return (
    <Async state={state}>
      {(data) => (
        <>
          {data.organization ? (
            <OwnSchool data={data} meta={meta} onGo={onGo} />
          ) : (
            <>
              <Hero
                data={data}
                title="ставки можно высвободить"
                sub={`${meta.okrug ?? 'Округ'} · анализ штатки ${data.organizations} школ по нормативу${data.plan?.state_date ? ` · штатка на ${fmtDate(data.plan.state_date)}` : ''}`}
              />
              <div className="bucket-grid">
                {data.buckets.map((b) => (
                  <BucketCard
                    key={b.key}
                    bucket={b}
                    onOpen={
                      b.key === 'cleaning'
                        ? () => onGo('cleaners')
                        : b.key === 'maintenance'
                          ? () => onGo('maintenance')
                          : () => onGo('positions')
                    }
                  />
                ))}
              </div>
              <SchoolsTable schools={data.schools} onOpen={onOpenSchool} />
              <TopPositions data={data} onMore={() => onGo('positions')} />
            </>
          )}
          <HowItWorks title="Как система решает: вакансии, нагрузка или люди">
            <ul className="how-list">
              <li>
                Для каждой должности школы берётся норматив — сколько ставок нужно (целевая штатка).
                Всё, что в штатке сверх норматива, — лишнее.
              </li>
              <li>
                Лишнее высвобождается по порядку: сначала <strong>вакансии</strong> (ставки никто не
                занимает), потом <strong>совмещение и доп. нагрузка</strong> (люди остаются на своей
                ставке), и только остаток — <strong>люди</strong>.
              </li>
              <li>
                Экономия = высвобожденные ставки × оклад должности × 12
                {data.headline.taxes_pct
                  ? ` × ${fmt(1 + data.headline.taxes_pct / 100)} (налоги)`
                  : ''}
                . Часы = ставки × {fmtInt(data.headline.hours_per_rate)} ч в год.
              </li>
            </ul>
            <RulesHelp rules={data.rules} />
          </HowItWorks>
        </>
      )}
    </Async>
  )
}
