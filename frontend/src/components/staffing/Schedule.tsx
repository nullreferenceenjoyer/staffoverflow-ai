import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  api,
  InstitutionSchedule,
  Position,
  ScheduleLine,
  ScheduleVersion,
  StaffBasis,
} from '../../api'
import {
  fmtDate,
  fmtDateTime,
  fmtDeviation,
  fmtFte,
  fmtRub,
  fmtRubDelta,
  fmtRubShort,
  useApi,
} from '../../lib'
import { Icon } from '../icons'
import { Drawer, Field, Form, Modal } from '../ui'
import { DataEditor } from './DataEditor'
import { AdviceLine, HowItWorks, RulesHelp, WhyList } from './HowItWorks'

const CATEGORY_TITLE = { aup: 'АУП', support: 'Вспомогательный персонал' }

/** «−270 000 ₽» зелёным, если ФОТ уменьшился, оранжевым — если вырос. */
export function MoneyDelta({ value }: { value: number | null }) {
  if (value === null || value === 0) return <span className="muted">без изменений ФОТ</span>
  return <span className={value < 0 ? 'dev-calm' : 'dev-surplus'}>{fmtRubDelta(value)}/год</span>
}

function changeLine(c: ScheduleVersion['changes'][number]) {
  const parts = []
  if (c.approved_delta) parts.push(`${fmtFte(c.approved_before)} → ${fmtFte(c.approved_after)} ст.`)
  if (c.salary_before !== c.salary_after)
    parts.push(`оклад ${fmtRub(c.salary_before)} → ${fmtRub(c.salary_after)}`)
  return parts.join(', ')
}

/** История штатки: что поменялось и как это сдвинуло ФОТ. */
export function History({ versions }: { versions: ScheduleVersion[] }) {
  if (!versions.length) return <p className="muted">Изменений пока не было.</p>
  return (
    <ol className="timeline">
      {versions.map((v) => (
        <li key={v.id}>
          <div className="timeline-head">
            <strong>{fmtDate(v.created_at)}</strong>
            <span className="muted">
              {v.author ?? v.source_title} · {v.status_title}
            </span>
          </div>
          {v.comment && <div>{v.comment}</div>}
          {v.first ? (
            <div className="muted">
              Исходная штатка: {fmtFte(v.approved)} ставок, ФОТ {fmtRub(v.payroll_approved)}/год
            </div>
          ) : (
            <>
              <ul className="why">
                {v.changes.map((c) => (
                  <li key={c.group_id}>
                    <strong>{c.group}:</strong> {changeLine(c)}{' '}
                    {c.payroll_delta !== null && <MoneyDelta value={c.payroll_delta} />}
                  </li>
                ))}
                {v.changes.length === 0 && (
                  <li className="muted">ставки по группам не изменились</li>
                )}
              </ul>
              <div className="timeline-total">
                Итого: {fmtDeviation(v.approved_delta)} ст., ФОТ{' '}
                <MoneyDelta value={v.payroll_delta} /> → {fmtRub(v.payroll_approved)}/год
              </div>
            </>
          )}
        </li>
      ))}
    </ol>
  )
}

const toInput = (value: number | null | undefined) =>
  value === null || value === undefined ? '' : String(value).replace('.', ',')

function parse(value: string, label: string, required = false): number | null {
  const text = value.trim().replace(/\s/g, '').replace(',', '.')
  if (!text) {
    if (required) throw new Error(`${label}: укажите число`)
    return null
  }
  const parsed = Number(text)
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error(`${label}: «${value}» — не число`)
  return parsed
}

/** Добавить или изменить должность. */
export function PositionEditor({
  data,
  groupId,
  position,
  onClose,
  onSaved,
}: {
  data: InstitutionSchedule
  groupId: number | null
  position: Position | null
  onClose: () => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState({
    group_id: String(groupId ?? data.groups[0]?.id ?? ''),
    position: position?.position ?? '',
    approved: toInput(position?.approved ?? 1),
    occupied: toInput(position ? position.occupied : 1),
    salary: toInput(position?.salary),
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })
  const group = data.groups.find((g) => String(g.id) === draft.group_id)
  const base = `/staffing/institutions/${data.organization_id}/positions`

  async function save() {
    const body = {
      year: data.year,
      group_id: Number(draft.group_id),
      position: draft.position,
      approved_fte: parse(draft.approved, 'Ставок по штатке', true),
      occupied_fte: parse(draft.occupied, 'Занято'),
      salary_rub: parse(draft.salary, 'Оклад') || null,
    }
    if (position) await api(`${base}/${position.line_id}`, { method: 'PUT', body })
    else await api(base, { body })
    onSaved()
    onClose()
  }

  return (
    <Modal title={position ? position.position : 'Новая должность'} onClose={onClose}>
      <Form onSubmit={save}>
        <Field label="Группа нормирования">
          <select value={draft.group_id} onChange={(e) => set('group_id', e.target.value)}>
            {data.groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.category === 'aup' ? 'АУП' : 'Вспом.'} · {g.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Должность">
          <input
            list="position-suggestions"
            value={draft.position}
            onChange={(e) => set('position', e.target.value)}
            placeholder={group?.suggestions[0] ?? 'Название должности'}
            required
            minLength={2}
          />
          <datalist id="position-suggestions">
            {(group?.suggestions ?? []).map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </Field>
        <div className="row">
          <Field label="Ставок по штатке">
            <input
              inputMode="decimal"
              value={draft.approved}
              onChange={(e) => set('approved', e.target.value)}
              required
            />
          </Field>
          <Field label="Из них занято">
            <input
              inputMode="decimal"
              value={draft.occupied}
              onChange={(e) => set('occupied', e.target.value)}
              placeholder="не ведётся"
            />
          </Field>
          <Field label="Оклад за ставку, ₽/мес">
            <input
              inputMode="decimal"
              value={draft.salary}
              onChange={(e) => set('salary', e.target.value)}
              placeholder="не указан"
            />
          </Field>
        </div>
        <p className="muted">
          Норматив считается по группе: уборщик и гардеробщик вместе — «Уборка помещений». Занято
          меньше, чем по штатке, — разница вакантна. Пустое «занято» — занятость не ведётся, считаем
          по штатке.
        </p>
      </Form>
    </Modal>
  )
}

function GroupRows({
  line,
  canEdit,
  onAdd,
  onEdit,
  onDelete,
}: {
  line: ScheduleLine
  canEdit: boolean
  onAdd: () => void
  onEdit: (p: Position) => void
  onDelete: (p: Position) => void
}) {
  const [open, setOpen] = useState(false)
  const advice = line.advice
  const cut = new Map(
    (advice?.positions_cut ?? []).map((p) => [`${p.line_id}-${p.kind}`, p.fte] as const),
  )
  return (
    <>
      <tr className="group-row">
        <td colSpan={canEdit ? 7 : 6}>
          <div className="group-row-inner">
            <span>
              <strong>{line.group}</strong>
              <span className="muted">
                {' '}
                · норматив {fmtFte(line.required)} · по штатке {fmtFte(line.approved)} · занято{' '}
                {line.occupied === null ? 'не ведётся' : fmtFte(line.occupied)}
                {line.people !== null && ` · в системе ${line.people} чел.`}
              </span>
            </span>
            <span className="group-row-side">
              {advice && <AdviceLine advice={advice} />}
              {advice && advice.why.length > 0 && (
                <button className="ghost small" onClick={() => setOpen(!open)}>
                  {open ? 'Скрыть' : 'Почему'}
                </button>
              )}
              {canEdit && (
                <button className="ghost small" onClick={onAdd}>
                  <Icon name="plus" size={14} /> должность
                </button>
              )}
            </span>
          </div>
          {open && advice && <WhyList why={advice.why} />}
        </td>
      </tr>
      {line.positions.length === 0 && (
        <tr>
          <td colSpan={canEdit ? 7 : 6} className="muted">
            Должностей нет
          </td>
        </tr>
      )}
      {line.positions.map((p) => {
        const people = cut.get(`${p.line_id}-people`)
        const load = cut.get(`${p.line_id}-load`)
        const vacant = cut.get(`${p.line_id}-vacant`)
        const what = [
          vacant ? `убрать вакансии ${fmtFte(vacant)}` : null,
          load ? `уменьшить нагрузку ${fmtFte(load)}` : null,
          people ? `сократить ${fmtFte(people)}` : null,
        ].filter(Boolean)
        return (
          <tr key={p.line_id} className="position-row">
            <td data-label="Должность">
              {p.position}
              {what.length > 0 && <div className="small-text dev-surplus">{what.join(' · ')}</div>}
              {p.combined ? (
                <div className="muted small-text">из занятых совмещение {fmtFte(p.combined)}</div>
              ) : null}
            </td>
            <td data-label="По штатке" className="num">
              {fmtFte(p.approved)}
            </td>
            <td data-label="Занято" className="num">
              {p.occupied === null ? <span className="muted">—</span> : fmtFte(p.occupied)}
            </td>
            <td data-label="Вакантно" className="num">
              {p.vacant ? fmtFte(p.vacant) : <span className="muted">—</span>}
            </td>
            <td data-label="Оклад, ₽/мес" className="num">
              {p.salary === null ? <span className="muted">не указан</span> : fmtRub(p.salary)}
            </td>
            <td data-label="ФОТ, ₽/год" className="num">
              {fmtRub(p.payroll)}
            </td>
            {canEdit && (
              <td className="row-action">
                <button
                  className="ghost icon"
                  title="Изменить"
                  aria-label={`Изменить: ${p.position}`}
                  onClick={() => onEdit(p)}
                >
                  <Icon name="edit" size={15} />
                </button>
                <button
                  className="ghost icon"
                  title="Такой должности нет — убрать из штатки"
                  aria-label={`Убрать из штатки: ${p.position}`}
                  onClick={() => onDelete(p)}
                >
                  <Icon name="trash" size={15} />
                </button>
              </td>
            )}
          </tr>
        )
      })}
    </>
  )
}

/** Штатка и факт вместе: по должностям — ставки, занято, вакансии, оклад, ФОТ; по группе —
 * норматив и вывод, что можно высвободить. */
export function ScheduleDetail({
  data,
  onChanged,
}: {
  data: InstitutionSchedule
  /** Передан — должности можно добавлять, менять и убирать */
  onChanged?: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ group: number | null; position: Position | null }>()
  const t = data.totals
  const a = data.advice_totals
  const canEdit = Boolean(onChanged) && data.can_edit

  async function remove(p: Position) {
    if (!window.confirm(`Убрать из штатки «${p.position}» (${fmtFte(p.approved)} ст.)?`)) return
    setError(null)
    try {
      await api(`/staffing/institutions/${data.organization_id}/positions/${p.line_id}`, {
        method: 'DELETE',
        query: { year: data.year },
      })
      onChanged?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось убрать должность')
    }
  }

  return (
    <>
      <dl className="facts facts-row">
        <dt>По штатке</dt>
        <dd className="strong-num">{fmtFte(t.approved)} ст.</dd>
        <dt>Занято</dt>
        <dd className="strong-num">
          {t.occupied === null ? 'не ведётся' : `${fmtFte(t.occupied)} ст.`}
        </dd>
        <dt>Вакантно</dt>
        <dd className="strong-num">{fmtFte(t.vacant)} ст.</dd>
        <dt>ФОТ по штатке</dt>
        <dd className="strong-num">{fmtRubShort(t.payroll_approved)}/год</dd>
        <dt>Высвободить</dt>
        <dd className={`strong-num ${a.total ? 'dev-surplus' : 'dev-calm'}`}>
          {a.total ? `${fmtFte(a.total)} ст.` : 'нечего'}
          {a.total_cost > 0 && <small> · {fmtRubShort(a.total_cost)}/год</small>}
        </dd>
      </dl>
      <p className="muted small-text">
        Статус: {data.schedule?.status_title ?? 'штатки нет'}
        {data.schedule?.status !== 'approved' &&
          ' — в расчёте «высвободить» участвует только утверждённая штатка'}
      </p>
      {t.missing_salary > 0 && (
        <div className="notice">
          У {t.missing_salary} групп не указан оклад — их ФОТ и экономия не посчитаны. Укажите оклад
          в должности (карандаш).
        </div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      {canEdit && (
        <div className="toolbar">
          <button className="primary" onClick={() => setEditing({ group: null, position: null })}>
            <Icon name="plus" size={16} /> Добавить должность
          </button>
        </div>
      )}
      {(['aup', 'support'] as const).map((category) => {
        const lines = data.lines.filter((l) => l.category === category)
        if (!lines.length) return null
        const part = data.by_category[category]
        return (
          <section key={category}>
            <h3>
              {CATEGORY_TITLE[category]}{' '}
              <span className="muted">
                · {fmtFte(part.approved)} ст. по штатке · занято {fmtFte(part.occupied)} ·{' '}
                {fmtRubShort(part.payroll_approved)}/год
              </span>
            </h3>
            <table className="stack compact schedule-table">
              <thead>
                <tr>
                  <th>Должность</th>
                  <th className="num">По штатке</th>
                  <th className="num">Занято</th>
                  <th className="num">Вакантно</th>
                  <th className="num">Оклад, ₽/мес</th>
                  <th className="num">ФОТ, ₽/год</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <Fragment key={l.group_id}>
                    <GroupRows
                      line={l}
                      canEdit={canEdit}
                      onAdd={() => setEditing({ group: l.group_id, position: null })}
                      onEdit={(p) => setEditing({ group: l.group_id, position: p })}
                      onDelete={remove}
                    />
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
      <HowItWorks title="Как считается: штатка, занято, вакансии и «высвободить»">
        <ul className="how-list">
          <li>
            <strong>По штатке</strong> — сколько ставок должности утверждено.{' '}
            <strong>Занято</strong> — на скольких из них реально работают люди.{' '}
            <strong>Вакантно</strong> = по штатке − занято.
          </li>
          <li>
            <strong>ФОТ</strong> = оклад за ставку × ставки по штатке × 12, без надбавок.
          </li>
          <li>
            <strong>Норматив</strong> считается по группе должностей (см. «Нормативы») от
            показателей учреждения: кабинеты, площадь, обучающиеся, классы, группы.
          </li>
        </ul>
        <RulesHelp rules={data.rules} />
      </HowItWorks>
      <h3>История изменений</h3>
      <History versions={data.history} />
      {editing && (
        <PositionEditor
          data={data}
          groupId={editing.group}
          position={editing.position}
          onClose={() => setEditing(undefined)}
          onSaved={() => onChanged?.()}
        />
      )}
    </>
  )
}

export function useSchedule(organizationId: number | null, year: string, basis: StaffBasis) {
  return useApi<InstitutionSchedule>(
    organizationId ? `/staffing/institutions/${organizationId}/schedule` : null,
    { year, basis },
  )
}

/** Показатели учреждения и статус штатки, помощник. */
export function ScheduleActions({
  data,
  year,
  onChanged,
}: {
  data: InstitutionSchedule
  year: string
  onChanged: () => void
}) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  return (
    <>
      <div className="actions wrap">
        {data.can_edit && (
          <button onClick={() => setEditing(true)}>
            <Icon name="edit" size={16} /> Показатели и утверждение штатки
          </button>
        )}
        <button
          className="ghost"
          onClick={() =>
            navigate(`/staffing?tab=assistant&about=${data.organization_id}&year=${year}`)
          }
        >
          <Icon name="message" size={16} /> Спросить помощника
        </button>
      </div>
      {editing && (
        <DataEditor
          organizationId={data.organization_id}
          year={year}
          onClose={() => setEditing(false)}
          onSaved={onChanged}
        />
      )}
    </>
  )
}

export function ScheduleDrawer({
  organizationId,
  year,
  onClose,
  onChanged,
}: {
  organizationId: number
  year: string
  onClose: () => void
  onChanged: () => void
}) {
  const state = useSchedule(organizationId, year, 'occupied')
  const data = state.data
  const changed = () => {
    void state.reload({ silent: true })
    onChanged()
  }
  return (
    <Drawer
      title={
        <>
          <h2>{data?.organization ?? 'Штатка'}</h2>
          <span className="muted">
            Штатка {year}
            {data?.schedule?.updated_at && ` · изменена ${fmtDateTime(data.schedule.updated_at)}`}
          </span>
        </>
      }
      wide
      onClose={onClose}
      footer={data && <ScheduleActions data={data} year={year} onChanged={changed} />}
    >
      {state.error ? (
        <div className="notice notice-error">{state.error}</div>
      ) : !data ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : (
        <ScheduleDetail data={data} onChanged={changed} />
      )}
    </Drawer>
  )
}
