import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, download, Project, Site, Verdict, WorkloadReport } from '../api'
import { useUser } from '../App'
import { FindingRow, VERDICT } from '../components/blocks'
import { Meter } from '../components/charts'
import { Icon } from '../components/icons'
import {
  ActionButton,
  Async,
  Badge,
  Card,
  Counter,
  Empty,
  Kpi,
  MunicipalitySelect,
  Page,
  Tabs,
} from '../components/ui'
import { canPlan, CATEGORY_SHORT, fmt, fmtInt, fmtMoney, useApi } from '../lib'

const RADIUS_OPTIONS = [
  [0, 'каждый корпус отдельно'],
  [150, 'до 150 м'],
  [300, 'до 300 м'],
  [500, 'до 500 м'],
  [1000, 'до 1 км'],
] as const

const PAGE = 30
type Tab = 'findings' | 'sites' | 'overload'

/** Схема расположения корпусов: площадки обведены, недозагруженные выделены цветом. */
function SiteMap({
  sites,
  selected,
  onSelect,
}: {
  sites: Site[]
  selected: number | null
  onSelect: (id: number) => void
}) {
  const [hover, setHover] = useState<{ site: Site; x: number; y: number } | null>(null)
  const W = 640
  const H = 380

  const points = useMemo(() => {
    const located = sites.flatMap((site) =>
      site.buildings
        .filter((b) => b.lat !== null && b.lon !== null)
        .map((b) => ({ site, building: b, lat: b.lat as number, lon: b.lon as number })),
    )
    if (!located.length) return []
    const lats = located.map((p) => p.lat)
    const lons = located.map((p) => p.lon)
    const latMin = Math.min(...lats)
    const latMax = Math.max(...lats)
    const lonMin = Math.min(...lons)
    const lonMax = Math.max(...lons)
    // Градус долготы короче градуса широты — без поправки схема вышла бы сплюснутой
    const squeeze = Math.cos(((latMin + latMax) / 2) * (Math.PI / 180))
    const width = Math.max((lonMax - lonMin) * squeeze, 1e-4)
    const height = Math.max(latMax - latMin, 1e-4)
    const scale = Math.min((W - 80) / width, (H - 80) / height)
    const dx = (W - width * scale) / 2
    const dy = (H - height * scale) / 2
    return located.map((p) => ({
      ...p,
      x: dx + (p.lon - lonMin) * squeeze * scale,
      y: dy + (latMax - p.lat) * scale,
      r: Math.max(5, Math.min(4 + Math.sqrt(p.building.capacity ?? 150) / 5, 12)),
    }))
  }, [sites])

  if (!points.length) {
    return <Empty>У зданий нет координат. Загрузите реестр из РГИС в разделе «Учреждения».</Empty>
  }

  const bySite = new Map<number, typeof points>()
  for (const point of points) {
    bySite.set(point.site.id, [...(bySite.get(point.site.id) ?? []), point])
  }

  return (
    <div className="sitemap" style={{ aspectRatio: `${W} / ${H}` }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Схема площадок">
        {[...bySite.entries()].map(([id, group], index) => {
          const site = group[0].site
          const cx = group.reduce((sum, p) => sum + p.x, 0) / group.length
          const cy = group.reduce((sum, p) => sum + p.y, 0) / group.length
          const reach = Math.max(...group.map((p) => Math.hypot(p.x - cx, p.y - cy) + p.r)) + 7
          const flagged = site.excess > 0
          const color = flagged ? 'var(--series-2)' : 'var(--series-1)'
          const dim = selected !== null && selected !== id
          return (
            <g
              key={id}
              className={`site ${dim ? 'dim' : ''}`}
              style={{ animationDelay: `${Math.min(index * 0.015, 0.6)}s` }}
              onMouseMove={(e) => setHover({ site, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect(id)}
            >
              {group.length > 1 && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={reach}
                  fill={color}
                  fillOpacity={0.1}
                  stroke={color}
                  strokeOpacity={0.5}
                  strokeDasharray="4 4"
                />
              )}
              {group.map((p) => (
                <circle
                  key={p.building.id}
                  cx={p.x}
                  cy={p.y}
                  r={selected === id ? p.r + 2 : p.r}
                  fill={color}
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ))}
            </g>
          )
        })}
      </svg>
      {hover && (
        <div
          className="gantt-tip"
          style={{ left: Math.min(hover.x + 14, window.innerWidth - 340), top: hover.y + 16 }}
        >
          <b>{hover.site.name}</b>
          Корпусов: {hover.site.buildings.length}, загрузка {hover.site.load_pct ?? '—'} %
          {hover.site.excess > 0 && <div>Можно сократить {fmt(hover.site.excess)} ст.</div>}
        </div>
      )}
    </div>
  )
}

function SiteCard({ site, open, onToggle }: { site: Site; open: boolean; onToggle: () => void }) {
  const staffed = site.functions.filter((f) => f.actual > 0 || f.volume > 0)
  return (
    <div
      id={`site-${site.id}`}
      className={`site-card ${open ? 'open' : ''}`}
      onClick={open ? undefined : onToggle}
    >
      <div className="site-head">
        <div>
          <h2>{site.name}</h2>
          <div className="site-facts">
            <span>
              <Icon name="building" size={14} /> корпусов: {site.buildings.length}
              {site.span_m !== null && `, до ${site.span_m} м друг от друга`}
            </span>
            <span>
              <Icon name="users" size={14} /> {fmt(site.actual)} ст. на {fmt(site.volume)} ст.
              работы
            </span>
            {site.occupancy_pct !== null && (
              <span>
                <Icon name="gauge" size={14} /> заполнено на {site.occupancy_pct} %
              </span>
            )}
          </div>
        </div>
        <div className="finding-side">
          {site.excess > 0 ? (
            <>
              <strong>−{fmt(site.excess)} ст.</strong>
              <span className="muted">{fmtMoney(site.saving_year)} в год</span>
            </>
          ) : (
            <Badge tone="green">замечаний нет</Badge>
          )}
          {open && (
            <div>
              <button className="ghost small" onClick={onToggle}>
                Свернуть
              </button>
            </div>
          )}
        </div>
      </div>

      {open && (
        <div className="site-details">
          <table>
            <thead>
              <tr>
                <th>Корпус</th>
                <th>Адрес по РГИС</th>
                <th className="num">Площадь, м²</th>
                <th className="num">Мощность</th>
                <th className="num">Обучается</th>
                <th className="num">Заполнено</th>
              </tr>
            </thead>
            <tbody>
              {site.buildings.map((b) => (
                <tr key={b.id}>
                  <td>
                    {b.name}
                    <div className="muted">
                      <Link to={`/organizations/${b.organization_id}`}>{b.organization}</Link>
                    </div>
                  </td>
                  <td>{b.address ?? '—'}</td>
                  <td className="num">{fmtInt(b.area)}</td>
                  <td className="num">{b.capacity ?? '—'}</td>
                  <td className="num">{fmtInt(b.students)}</td>
                  <td className="num">{b.occupancy_pct === null ? '—' : `${b.occupancy_pct} %`}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ marginTop: 18 }}>Функции АУП и вспомогательного персонала</h3>
          <table>
            <thead>
              <tr>
                <th>Функция</th>
                <th className="num">Занято, ст.</th>
                <th className="num">Человек</th>
                <th className="num">Работы, ст.</th>
                <th style={{ minWidth: 150 }}>Загрузка</th>
                <th className="num">Достаточно</th>
                <th className="num" title="Заявок за 90 дней по этой функции">
                  Заявок
                </th>
                <th>Вывод</th>
              </tr>
            </thead>
            <tbody>
              {staffed.map((f) => (
                <tr key={f.function_code + (f.organization ?? '')}>
                  <td>
                    {f.title}
                    {f.organization && <span className="muted"> · {f.organization}</span>}
                    <div className="muted">
                      {CATEGORY_SHORT[f.category]}
                      {site.buildings.length > 1 &&
                        ' · по корпусам: ' + f.by_building.map((b) => fmt(b.actual)).join(' + ')}
                    </div>
                    {f.recommendation && <div className="reason">{f.recommendation}</div>}
                  </td>
                  <td className="num">{fmt(f.actual)}</td>
                  <td className="num">{f.people || '—'}</td>
                  <td className="num">{fmt(f.volume)}</td>
                  <td>
                    <div className="meter" style={{ marginTop: 6 }}>
                      <i
                        className={(f.load_pct ?? 100) < 80 ? 'low' : ''}
                        style={{ width: `${Math.min((f.load_pct ?? 0) / 1.25, 100)}%` }}
                      />
                      <u style={{ left: '80%' }} />
                    </div>
                    <span className="muted">{f.load_pct === null ? '—' : `${f.load_pct} %`}</span>
                  </td>
                  <td className="num">{fmt(f.required)}</td>
                  <td className="num">{f.requests || '—'}</td>
                  <td>
                    <Badge tone={VERDICT[f.verdict].tone}>{VERDICT[f.verdict].label}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function Workload() {
  const user = useUser()
  const navigate = useNavigate()
  const [municipality, setMunicipality] = useState<number | null>(null)
  const [radius, setRadius] = useState(300)
  const [tab, setTab] = useState<Tab>('findings')
  const [verdict, setVerdict] = useState<Verdict | ''>('')
  const [selected, setSelected] = useState<number | null>(null)
  const [limit, setLimit] = useState(PAGE)
  const state = useApi<WorkloadReport>('/analytics/workload', {
    municipality_id: municipality,
    radius,
  })

  async function createProject() {
    const project = await api<Project>('/projects/generate', {
      body: { kind: 'workload', municipality_id: municipality },
    })
    navigate(`/projects/${project.id}`)
  }

  function openSite(id: number) {
    setSelected(id)
    setTab('sites')
    // Карточка может быть далеко внизу списка — прокручиваем к ней после отрисовки
    setTimeout(() => {
      document.getElementById(`site-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 60)
  }

  return (
    <Page
      title="Загрузка персонала"
      hint="Сколько работы у АУП и вспомогательного персонала на каждой площадке — группе корпусов, стоящих рядом. Объём считается по нормативам, расположение и мощность зданий берутся из РГИС."
      actions={
        <>
          <MunicipalitySelect
            value={municipality}
            onChange={(id) => {
              setMunicipality(id)
              setSelected(null)
            }}
          />
          <select
            value={radius}
            onChange={(e) => setRadius(Number(e.target.value))}
            aria-label="Какие корпуса считать соседними"
            title="Какие корпуса считать соседними"
          >
            {RADIUS_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                Рядом: {label}
              </option>
            ))}
          </select>
          <button
            onClick={() =>
              download('/analytics/workload.csv', 'workload.csv', {
                municipality_id: municipality,
                radius,
              })
            }
          >
            <Icon name="download" size={16} /> CSV
          </button>
          {canPlan(user) && municipality !== null && (
            <ActionButton className="primary" onClick={createProject}>
              Сформировать проект
            </ActionButton>
          )}
        </>
      }
    >
      <Async state={state}>
        {(report) => {
          const t = report.totals
          const savings = report.findings.filter((f) => f.verdict !== 'overload')
          const overload = report.findings.filter((f) => f.verdict === 'overload')
          const shown = savings.filter((f) => !verdict || f.verdict === verdict)
          // Схема имеет смысл в границах одного муниципалитета: иначе корпуса сольются в точки
          const anchor =
            report.sites.find((s) => s.id === selected) ?? report.sites.find((s) => s.excess > 0)
          const mapMunicipality = municipality ?? anchor?.municipality_id ?? null
          const mapSites = report.sites.filter((s) => s.municipality_id === mapMunicipality)

          return (
            <>
              {t.unassigned_rate > 0 && (
                <div className="notice">
                  <Icon name="alert" />
                  <span>
                    {fmt(t.unassigned_rate)} ст. не привязаны к корпусам и отнесены к главному
                    зданию учреждения. Укажите корпус в штатном расписании или колонку «Корпус» при
                    импорте — тогда расчёт по площадкам будет точным.
                  </span>
                </div>
              )}
              {t.without_location > 0 && (
                <div className="notice">
                  <Icon name="pin" />
                  <span>
                    У {t.without_location} зданий нет ни адреса, ни координат — они считаются
                    отдельными площадками. Загрузите реестр зданий из РГИС в разделе «Учреждения».
                  </span>
                </div>
              )}

              <div className="kpis">
                <Kpi
                  icon="pin"
                  label="Площадок"
                  value={<Counter value={t.sites} format={fmtInt} />}
                  note={`${t.buildings} корпусов; из нескольких корпусов — ${t.shared_sites}`}
                />
                <Kpi
                  icon="gauge"
                  tone={(t.load_pct ?? 100) < 85 ? 'warn' : 'good'}
                  label="Средняя загрузка"
                  value={<Counter value={t.load_pct ?? 0} format={(v) => `${fmtInt(v)} %`} />}
                  note={`${fmt(t.volume)} ст. работы на ${fmt(t.actual)} занятых`}
                />
                <Kpi
                  icon="users"
                  label="Можно сократить"
                  value={
                    <Counter value={t.excess} format={(v) => `${fmt(Math.round(v * 4) / 4)} ст.`} />
                  }
                  note={`вакансии — ${fmt(t.vacant_in_excess)} ст., площадок с замечаниями: ${t.flagged_sites}`}
                />
                <Kpi
                  icon="wallet"
                  tone="good"
                  label="Экономия ФОТ в год"
                  value={<Counter value={t.saving_year} format={fmtMoney} />}
                  note="с начислениями"
                />
              </div>

              <div className="grid-wide">
                <Card title="Схема площадок">
                  <p className="card-sub">
                    {mapSites[0]?.municipality ?? 'Нет данных'}. Точка — корпус, пунктир — площадка
                    из нескольких корпусов. Нажмите, чтобы открыть расчёт.
                  </p>
                  <SiteMap sites={mapSites} selected={selected} onSelect={openSite} />
                  <div className="legend">
                    <span>
                      <i className="swatch" style={{ background: 'var(--series-2)' }} />
                      есть недозагруженный персонал
                    </span>
                    <span>
                      <i className="swatch" style={{ background: 'var(--series-1)' }} />
                      замечаний нет
                    </span>
                  </div>
                </Card>

                <Card title="Загрузка по функциям">
                  <p className="card-sub">Объём работы к занятым ставкам. Черта — 100 %.</p>
                  {report.by_function.map((f) => (
                    <Meter
                      key={f.function_code}
                      label={f.title}
                      value={f.load_pct}
                      max={125}
                      mark={100}
                      low={(f.load_pct ?? 100) < 85}
                      title={`Занято ${fmt(f.actual)} ст., работы на ${fmt(f.volume)} ст., можно сократить ${fmt(f.excess)} ст.`}
                    />
                  ))}
                </Card>
              </div>

              <Tabs
                value={tab}
                onChange={setTab}
                tabs={[
                  ['findings', `Рекомендации · ${savings.length}`],
                  ['sites', `Площадки · ${report.sites.length}`],
                  ['overload', `Перегрузка · ${overload.length}`],
                ]}
              />

              {tab === 'findings' && (
                <Card
                  title="Где персонала больше, чем работы"
                  aside={
                    <select
                      value={verdict}
                      onChange={(e) => setVerdict(e.target.value as Verdict | '')}
                    >
                      <option value="">Все замечания</option>
                      <option value="duplicate">{VERDICT.duplicate.label}</option>
                      <option value="idle">{VERDICT.idle.label}</option>
                      <option value="underused">{VERDICT.underused.label}</option>
                    </select>
                  }
                >
                  {shown.length === 0 && <Empty>Замечаний нет.</Empty>}
                  {shown.slice(0, limit).map((f) => (
                    <div
                      key={`${f.site_id}-${f.function_code}-${f.organization}`}
                      className="clickable"
                      onClick={() => openSite(f.site_id)}
                    >
                      <FindingRow finding={f} />
                    </div>
                  ))}
                  {shown.length > limit && (
                    <button onClick={() => setLimit(limit + PAGE)}>Показать ещё</button>
                  )}
                  <p className="muted">
                    Расчёт показывает, где стоит разобраться, а не готовое решение: режим работы
                    зданий, сменность и особенности конкретных должностей он не учитывает.
                  </p>
                </Card>
              )}

              {tab === 'sites' && (
                <div className="site-list stagger">
                  {report.sites
                    // Выбранная на схеме площадка показывается, даже если она далеко в списке
                    .filter((site, index) => index < limit || site.id === selected)
                    .map((site) => (
                      <SiteCard
                        key={site.id}
                        site={site}
                        open={selected === site.id}
                        onToggle={() => setSelected(selected === site.id ? null : site.id)}
                      />
                    ))}
                  {report.sites.length > limit && (
                    <button onClick={() => setLimit(limit + PAGE)}>Показать ещё</button>
                  )}
                </div>
              )}

              {tab === 'overload' && (
                <Card title="Где работы больше, чем людей">
                  <p className="card-sub">
                    Сюда стоит переводить ставки с недозагруженных площадок, прежде чем их
                    сокращать.
                  </p>
                  {overload.length === 0 && <Empty>Перегруженных функций нет.</Empty>}
                  {overload.slice(0, limit).map((f) => (
                    <div
                      key={`${f.site_id}-${f.function_code}-${f.organization}`}
                      className="clickable"
                      onClick={() => openSite(f.site_id)}
                    >
                      <FindingRow finding={f} />
                    </div>
                  ))}
                  {overload.length > limit && (
                    <button onClick={() => setLimit(limit + PAGE)}>Показать ещё</button>
                  )}
                </Card>
              )}
            </>
          )
        }}
      </Async>
    </Page>
  )
}
