import { CSSProperties, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  api,
  StaffBasis,
  StaffCategory,
  StaffingAnalysis,
  StaffingInstitution,
  StaffingMeta,
  StaffingResult,
  StaffingStatus,
} from '../api'
import { useUser } from '../App'
import { Icon } from '../components/icons'
import { DataEditor } from '../components/staffing/DataEditor'
import { InstitutionDrawer, MetricsLine } from '../components/staffing/InstitutionDrawer'
import { Deviation, ProblemList, StatusBadge } from '../components/staffing/parts'
import { RequestDialog } from '../components/staffing/RequestDialog'
import { ScheduleDrawer } from '../components/staffing/Schedule'
import { Async, Card, Empty, Page, Segmented, Tabs } from '../components/ui'
import { fmtDate, fmtDateTime, fmtFte, ORG_TYPE_LABELS, STAFFING_STATUS, useApi } from '../lib'
import { Assistant } from './staffing/Assistant'
import { Dashboard } from './staffing/Dashboard'
import { Imports } from './staffing/Imports'
import { Norms } from './staffing/Norms'
import { Schedules } from './staffing/Schedules'

type Tab = 'dashboard' | 'analysis' | 'schedule' | 'fact' | 'norms' | 'import' | 'assistant'

const CATEGORIES: [StaffCategory, string][] = [
  ['aup', 'АУП'],
  ['support', 'Вспомогательный'],
]
const BASES: [StaffBasis, string][] = [
  ['occupied', 'По занятости'],
  ['approved', 'По штатке'],
]
// Карточки статусов: сначала то, что требует действий
const CARDS: [StaffingStatus, string][] = [
  ['deficit', 'не хватает ставок'],
  ['surplus', 'больше норматива'],
  ['warning', 'отклонения в группах'],
  ['no_data', 'не хватает данных'],
  ['normal', 'в пределах допуска'],
]
const PAGE = 100

type Sort = 'deviation' | 'problem' | 'name'

function AnalysisView({
  meta,
  year,
  category,
  basis,
  version,
  onOpen,
}: {
  meta: StaffingMeta
  year: string
  category: StaffCategory
  basis: StaffBasis
  version: number
  onOpen: (id: number) => void
}) {
  const [municipality, setMunicipality] = useState('')
  const state = useApi<StaffingAnalysis>('/staffing/analysis', {
    year,
    category,
    basis,
    municipality_id: municipality || null,
  })
  const [status, setStatus] = useState<StaffingStatus | null>(null)
  const [onlyProblems, setOnlyProblems] = useState(false)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<Sort>('deviation')
  const [limit, setLimit] = useState(PAGE)
  const [busy, setBusy] = useState(false)
  const { reload } = state
  const first = useRef(true)

  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    void reload({ silent: true })
  }, [version, reload])

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const items = (state.data?.items ?? []).filter(
      (i) =>
        (!status || i.status === status) &&
        (!onlyProblems || i.status !== 'normal') &&
        (!needle || `${i.organization} ${i.municipality}`.toLowerCase().includes(needle)),
    )
    if (sort === 'name')
      return [...items].sort((a, b) => a.organization.localeCompare(b.organization))
    if (sort === 'problem') {
      const order = CARDS.map(([s]) => s)
      return [...items].sort(
        (a, b) =>
          order.indexOf(a.status) - order.indexOf(b.status) ||
          Math.abs(b.deviation ?? 0) - Math.abs(a.deviation ?? 0),
      )
    }
    return items // сервер уже отсортировал по размеру отклонения
  }, [state.data, status, onlyProblems, search, sort])

  async function recalculateAll() {
    setBusy(true)
    try {
      await api('/staffing/analysis/recalculate', { body: { year } })
      await reload({ silent: true })
    } finally {
      setBusy(false)
    }
  }

  const summary = state.data?.summary

  return (
    <>
      <div className="pipeline" role="group" aria-label="Статусы">
        {CARDS.map(([code, note]) => (
          <button
            key={code}
            className={`pipeline-step ${status === code ? 'active' : ''}`}
            style={{ '--step': STAFFING_STATUS[code].color } as CSSProperties}
            aria-pressed={status === code}
            onClick={() => {
              setStatus(status === code ? null : code)
              setLimit(PAGE)
            }}
          >
            <strong>{summary ? summary[code] : '…'}</strong>
            <span>{STAFFING_STATUS[code].label}</span>
            <small>{note}</small>
          </button>
        ))}
      </div>

      <div className="toolbar">
        {meta.municipalities.length > 1 && (
          <select
            value={municipality}
            onChange={(e) => setMunicipality(e.target.value)}
            aria-label="Территория"
          >
            <option value="">Весь регион</option>
            {meta.municipalities.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        )}
        <button
          className={`chip ${onlyProblems ? 'chip-on' : ''}`}
          aria-pressed={onlyProblems}
          onClick={() => setOnlyProblems(!onlyProblems)}
        >
          Только проблемы
        </button>
        <input
          type="search"
          placeholder="Поиск учреждения"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          aria-label="Сортировка"
        >
          <option value="deviation">По размеру отклонения</option>
          <option value="problem">По типу проблемы</option>
          <option value="name">По учреждению</option>
        </select>
        <span className="spacer" />
        {state.data?.calculated_at && (
          <span className="muted">Расчёт на {fmtDateTime(state.data.calculated_at)}</span>
        )}
        {meta.permissions.edit_data && (
          <button className="ghost" disabled={busy} onClick={recalculateAll}>
            <Icon name="refresh" size={16} /> {busy ? 'Считаем…' : 'Пересчитать'}
          </button>
        )}
      </div>

      <Async state={state}>
        {() =>
          shown.length === 0 ? (
            <Empty>
              {state.data?.items.length
                ? 'Под выбранные условия учреждений нет. Снимите фильтр.'
                : 'Учреждений пока нет.'}
            </Empty>
          ) : (
            <Card>
              <table className="stack staffing-table">
                <thead>
                  <tr>
                    <th>Учреждение</th>
                    <th className="num">Норматив</th>
                    <th className="num">Факт</th>
                    <th className="num">Отклонение</th>
                    <th>Статус</th>
                    <th>Что не так</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.slice(0, limit).map((i) => (
                    <tr
                      key={i.organization_id}
                      className={meta.permissions.details ? 'clickable' : ''}
                      onClick={() => meta.permissions.details && onOpen(i.organization_id)}
                    >
                      <td data-label="Учреждение">
                        <strong>{i.organization}</strong>
                        <div className="muted">
                          {i.municipality} · {ORG_TYPE_LABELS[i.org_type]}
                        </div>
                      </td>
                      <td data-label="Норматив" className="num">
                        {fmtFte(i.required)}
                      </td>
                      <td
                        data-label={basis === 'occupied' ? 'Занято' : 'По штатке'}
                        className="num"
                      >
                        {fmtFte(i.fact)}
                      </td>
                      <td data-label="Отклонение" className="num">
                        <Deviation value={i.deviation} status={i.status} />
                      </td>
                      <td data-label="Статус">
                        <StatusBadge status={i.status} />
                      </td>
                      <td data-label="Что не так" className="reason">
                        <ProblemList row={i} problems={i.problems} />
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
            </Card>
          )
        }
      </Async>
    </>
  )
}

function groupLine(g: StaffingResult) {
  if (g.status === 'no_data' || g.status === 'warning') return `${g.group}: ${g.reasons.join('; ')}`
  const what = g.status === 'deficit' ? 'дефицит' : 'сверх норматива на'
  return `${g.group}: ${what} ${fmtFte(Math.abs(g.deviation ?? 0))} ставки`
}

/** Директору — не таблица, а ответ на вопрос «что не так в моём учреждении». */
function DirectorView({
  meta,
  year,
  basis,
  version,
  onOpen,
}: {
  meta: StaffingMeta
  year: string
  basis: StaffBasis
  version: number
  onOpen: (id: number, category: StaffCategory) => void
}) {
  const org = meta.organization
  const navigate = useNavigate()
  const state = useApi<StaffingInstitution>(
    org ? `/staffing/institutions/${org.id}/analysis` : null,
    { year },
  )
  const [editing, setEditing] = useState(false)
  const [requesting, setRequesting] = useState<StaffCategory | null>(null)
  const { reload } = state
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    void reload({ silent: true })
  }, [version, reload])

  if (!org)
    return <Empty>Учётная запись не привязана к учреждению — обратитесь к администратору.</Empty>

  return (
    <Async state={state}>
      {(data) => (
        <>
          <div className="grid-2">
            {CATEGORIES.map(([category]) => {
              const slot = data.analysis[category][basis]
              const total = slot.total
              const off = slot.groups.filter((g) => g.status !== 'normal')
              const title = category === 'aup' ? 'АУП' : 'Вспомогательный персонал'
              return (
                <Card
                  key={category}
                  title={title}
                  aside={
                    total && (
                      <span className="chips">
                        <StatusBadge status={total.status} />
                        {total.deviation !== null && total.status !== 'normal' && (
                          <Deviation value={total.deviation} status={total.status} />
                        )}
                      </span>
                    )
                  }
                >
                  {!total ? (
                    <p className="muted">Расчёта нет.</p>
                  ) : total.status === 'normal' && off.length === 0 ? (
                    <p>Отклонений не выявлено.</p>
                  ) : total.status === 'no_data' ? (
                    <>
                      <p>Не хватает данных для расчёта:</p>
                      <ul className="why">
                        {total.reasons.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <ul className="why">
                      {off.map((g) => (
                        <li key={g.id}>{groupLine(g)}</li>
                      ))}
                      {off.length === 0 && total.reasons.map((r) => <li key={r}>{r}</li>)}
                    </ul>
                  )}
                  {total && (
                    <p className="muted">
                      Норматив {fmtFte(total.required)} ·{' '}
                      {basis === 'occupied' ? 'занято' : 'по штатке'} {fmtFte(total.fact)}
                    </p>
                  )}
                  <div className="actions wrap">
                    {total && total.status === 'no_data' ? (
                      <button className="primary" onClick={() => setEditing(true)}>
                        Внести данные
                      </button>
                    ) : (
                      total &&
                      total.status !== 'normal' && (
                        <button className="primary" onClick={() => setRequesting(category)}>
                          Создать заявку по{' '}
                          {category === 'aup' ? 'АУП' : 'вспомогательному персоналу'}
                        </button>
                      )
                    )}
                    <button onClick={() => onOpen(org.id, category)}>Подробнее</button>
                  </div>
                </Card>
              )
            })}
          </div>
          <div className="toolbar">
            <span className="muted">
              Данные актуальны на {fmtDate(data.calculated_at)}.{' '}
              <MetricsLine metrics={data.metrics} />
            </span>
            <span className="spacer" />
            <button onClick={() => setEditing(true)}>
              <Icon name="edit" size={16} /> Проверить данные
            </button>
          </div>
          {editing && (
            <DataEditor
              organizationId={org.id}
              year={year}
              onClose={() => setEditing(false)}
              onSaved={() => void reload({ silent: true })}
            />
          )}
          {requesting && (
            <RequestDialog
              organizationId={org.id}
              organization={org.name}
              year={year}
              category={requesting}
              basis={basis}
              groups={data.analysis[requesting][basis].groups}
              groupId={null}
              onClose={() => setRequesting(null)}
              onCreated={(id) => navigate(`/requests?open=${id}`)}
            />
          )}
        </>
      )}
    </Async>
  )
}

export function Staffing() {
  const user = useUser()
  const meta = useApi<StaffingMeta>('/staffing/meta')
  const [params, setParams] = useSearchParams()
  const [version, setVersion] = useState(0)
  const director = user.role === 'director'

  function update(patch: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  const tab = (params.get('tab') as Tab | null) ?? 'dashboard'
  const category = (params.get('category') as StaffCategory | null) ?? 'aup'
  const basis = (params.get('basis') as StaffBasis | null) ?? 'occupied'
  const opened = Number(params.get('org')) || null
  const schedule = Number(params.get('sched')) || null

  return (
    <Page
      title={director ? 'Моя нормативная численность' : 'Нормативная численность'}
      hint="Где не хватает ставок АУП и вспомогательного персонала, где их больше норматива, сколько это стоит и как меняется ФОТ. Только итоги по группам должностей — без ФИО."
    >
      <Async state={meta}>
        {(m) => {
          const year = params.get('year') ?? m.current_year
          const tabs: [Tab, string][] = [
            ['dashboard', 'Сводка'],
            ['analysis', 'Анализ'],
            ['schedule', 'Штатка'],
            ['fact', 'Факт'],
            ['norms', 'Нормативы'],
          ]
          if (m.permissions.import) tabs.push(['import', 'Загрузка данных'])
          tabs.push(['assistant', 'Помощник'])
          return (
            <>
              <Tabs
                value={tab}
                onChange={(t) => update({ tab: t === 'dashboard' ? null : t })}
                tabs={tabs}
              />
              {(tab === 'dashboard' || tab === 'schedule' || tab === 'fact') && (
                <div className="toolbar">
                  <select
                    value={year}
                    onChange={(e) => update({ year: e.target.value })}
                    aria-label="Учебный год"
                  >
                    {m.years.map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                  {tab === 'dashboard' && (
                    <Segmented
                      label="Основа"
                      options={BASES}
                      value={basis}
                      onChange={(b) => update({ basis: b })}
                    />
                  )}
                  <span className="muted">
                    {tab === 'schedule'
                      ? 'Сколько ставок утверждено, оклады и ФОТ. Изменения штатки сохраняются в истории.'
                      : tab === 'fact'
                        ? 'Сколько ставок реально занято, вакансии и сколько на них приходится ФОТ.'
                        : basis === 'occupied'
                          ? 'Норматив сравнивается с занятыми ставками.'
                          : 'Норматив сравнивается с утверждённой штаткой.'}
                  </span>
                </div>
              )}
              {tab === 'dashboard' && (
                <Dashboard
                  meta={m}
                  year={year}
                  basis={basis}
                  version={version}
                  onOpenAnalysis={(id) => update({ org: String(id) })}
                  onOpenSchedule={(id) => update({ sched: String(id) })}
                />
              )}
              {(tab === 'schedule' || tab === 'fact') && (
                <Schedules
                  meta={m}
                  year={year}
                  mode={tab}
                  version={version}
                  onOpen={(id) => update({ sched: String(id) })}
                />
              )}
              {tab === 'analysis' && (
                <>
                  <div className="toolbar">
                    <select
                      value={year}
                      onChange={(e) => update({ year: e.target.value })}
                      aria-label="Учебный год"
                    >
                      {m.years.map((y) => (
                        <option key={y} value={y}>
                          {y}
                        </option>
                      ))}
                    </select>
                    {!director && (
                      <Segmented
                        label="Категория"
                        options={CATEGORIES}
                        value={category}
                        onChange={(c) => update({ category: c })}
                      />
                    )}
                    <Segmented
                      label="Основа"
                      options={BASES}
                      value={basis}
                      onChange={(b) => update({ basis: b })}
                    />
                  </div>
                  {basis === 'occupied' && (
                    <p className="muted basis-note">
                      По занятости — сколько ставок фактически занято. Чтобы сравнить утверждённое
                      штатное расписание с нормативом, выберите «По штатке».
                    </p>
                  )}
                  {director ? (
                    <DirectorView
                      meta={m}
                      year={year}
                      basis={basis}
                      version={version}
                      onOpen={(id, c) => update({ org: String(id), category: c })}
                    />
                  ) : (
                    <AnalysisView
                      meta={m}
                      year={year}
                      category={category}
                      basis={basis}
                      version={version}
                      onOpen={(id) => update({ org: String(id) })}
                    />
                  )}
                </>
              )}
              {tab === 'norms' && <Norms meta={m} />}
              {tab === 'assistant' && (
                <Assistant
                  meta={m}
                  year={year}
                  about={Number(params.get('about')) || null}
                  onAboutDone={() => params.get('about') && update({ about: null })}
                />
              )}
              {tab === 'import' && m.permissions.import && (
                <Imports meta={m} onDone={() => setVersion((v) => v + 1)} />
              )}
              {schedule && m.permissions.details && (
                <ScheduleDrawer
                  key={`${schedule}-${year}`}
                  organizationId={schedule}
                  year={year}
                  initialMode={tab === 'fact' ? 'fact' : 'schedule'}
                  onClose={() => update({ sched: null })}
                  onChanged={() => setVersion((v) => v + 1)}
                />
              )}
              {opened && m.permissions.details && (
                <InstitutionDrawer
                  key={`${opened}-${year}`}
                  organizationId={opened}
                  year={year}
                  category={category}
                  basis={basis}
                  meta={m}
                  onClose={() => update({ org: null })}
                  onChanged={() => setVersion((v) => v + 1)}
                />
              )}
            </>
          )
        }}
      </Async>
    </Page>
  )
}
