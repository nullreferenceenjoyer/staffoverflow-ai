import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, StaffBasis, StaffCategory, StaffingInstitution, StaffingMeta } from '../../api'
import { fmt, fmtDate, fmtDateTime, fmtFte, useApi } from '../../lib'
import { Icon } from '../icons'
import { Drawer, Segmented } from '../ui'
import { DataEditor } from './DataEditor'
import { Deviation, factLabel, StatusBadge, Totals } from './parts'
import { RequestDialog } from './RequestDialog'

const CATEGORIES: [StaffCategory, string][] = [
  ['aup', 'АУП'],
  ['support', 'Вспомогательный'],
]
const BASES: [StaffBasis, string][] = [
  ['occupied', 'По занятости'],
  ['approved', 'По штатке'],
]

/** Показатели, от которых считался норматив, одной строкой. */
export function MetricsLine({ metrics }: { metrics: StaffingInstitution['metrics'] }) {
  const parts = [
    metrics.students_count !== null && `обучающихся ${fmt(metrics.students_count as number)}`,
    metrics.classes_count !== null && `классов ${fmt(metrics.classes_count as number)}`,
    metrics.groups_count !== null && `групп ${fmt(metrics.groups_count as number)}`,
    metrics.total_area_m2 !== null && `площадь ${fmt(metrics.total_area_m2 as number)} м²`,
  ].filter(Boolean)
  const schedule =
    metrics.schedule_status === 'approved'
      ? `штатка утверждена${metrics.schedule_approved_at ? ` ${fmtDate(metrics.schedule_approved_at as string)}` : ''}`
      : metrics.schedule_status === 'draft'
        ? 'штатка — черновик'
        : 'штатки нет'
  return (
    <span className="muted">
      {parts.length ? parts.join(' · ') : 'показатели не указаны'} · {schedule}
    </span>
  )
}

export function InstitutionDrawer({
  organizationId,
  year,
  category: initialCategory,
  basis: initialBasis,
  meta,
  onClose,
  onChanged,
}: {
  organizationId: number
  year: string
  category: StaffCategory
  basis: StaffBasis
  meta: StaffingMeta
  onClose: () => void
  onChanged: () => void
}) {
  const state = useApi<StaffingInstitution>(`/staffing/institutions/${organizationId}/analysis`, {
    year,
  })
  const navigate = useNavigate()
  const [category, setCategory] = useState(initialCategory)
  const [basis, setBasis] = useState(initialBasis)
  const [editing, setEditing] = useState(false)
  const [requesting, setRequesting] = useState<{ group: number | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const data = state.data
  const slot = data?.analysis[category][basis]
  const total = slot?.total

  async function recalculate() {
    setBusy(true)
    setError(null)
    try {
      await api('/staffing/analysis/recalculate', {
        body: { year, organization_id: organizationId },
      })
      await state.reload({ silent: true })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось пересчитать')
    } finally {
      setBusy(false)
    }
  }

  const categoryTitle = CATEGORIES.find(([k]) => k === category)?.[1]
  const basisTitle = basis === 'occupied' ? 'по занятости' : 'по штатке'

  return (
    <Drawer
      onClose={onClose}
      title={
        <>
          <h2>{data?.organization ?? 'Учреждение'}</h2>
          <span className="muted">
            {categoryTitle} · {year} · {basisTitle}
          </span>
        </>
      }
      footer={
        data && (
          <>
            {error && <div className="inline-error">{error}</div>}
            <div className="actions wrap">
              {meta.permissions.create_requests && total && (
                <button className="primary" onClick={() => setRequesting({ group: null })}>
                  <Icon name="plus" size={16} /> Создать заявку
                </button>
              )}
              {data.can_edit && (
                <button onClick={() => setEditing(true)}>
                  <Icon name="edit" size={16} /> Исправить данные
                </button>
              )}
              {data.can_edit && (
                <button disabled={busy} onClick={recalculate}>
                  <Icon name="refresh" size={16} /> {busy ? 'Считаем…' : 'Пересчитать'}
                </button>
              )}
              <button
                className="ghost"
                onClick={() =>
                  navigate(`/staffing?tab=assistant&about=${organizationId}&year=${year}`)
                }
              >
                <Icon name="message" size={16} /> Спросить помощника
              </button>
            </div>
          </>
        )
      }
    >
      {state.error ? (
        <div className="notice notice-error">{state.error}</div>
      ) : !data || !slot ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : (
        <>
          <div className="toolbar">
            <Segmented
              label="Категория"
              options={CATEGORIES}
              value={category}
              onChange={setCategory}
            />
            <Segmented label="Основа" options={BASES} value={basis} onChange={setBasis} />
          </div>

          <h3>Итог</h3>
          {total ? <Totals row={total} /> : <p className="muted">Расчёта нет.</p>}

          {slot.groups.length > 0 && (
            <>
              <h3>По группам</h3>
              <table className="compact staffing-groups">
                <thead>
                  <tr>
                    <th>Группа</th>
                    <th className="num">Норматив</th>
                    <th className="num">{factLabel(basis)}</th>
                    <th className="num">Отклонение</th>
                  </tr>
                </thead>
                <tbody>
                  {slot.groups.map((g) => (
                    <tr
                      key={g.id}
                      className={meta.permissions.create_requests ? 'clickable' : ''}
                      title={
                        meta.permissions.create_requests ? 'Создать заявку по этой группе' : ''
                      }
                      onClick={() =>
                        meta.permissions.create_requests && setRequesting({ group: g.group_id })
                      }
                    >
                      <td>
                        {g.group}
                        {g.status !== 'normal' && (
                          <div>
                            <StatusBadge status={g.status} />
                          </div>
                        )}
                      </td>
                      <td className="num">{fmtFte(g.required)}</td>
                      <td className="num">{fmtFte(g.fact)}</td>
                      <td className="num">
                        <Deviation value={g.deviation} status={g.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3>Почему так получилось</h3>
          <ul className="why">
            {slot.groups.map((g) => (
              <li key={g.id}>
                <strong>{g.group}.</strong>{' '}
                {g.coefficients.length
                  ? g.coefficients.map((c) => c.explain ?? c.missing ?? c.rule).join('; ')
                  : 'норматив не настроен'}
                {g.reasons.length > 0 && g.coefficients.length > 0 && (
                  <span className="muted"> — {g.reasons.join('; ')}</span>
                )}
              </li>
            ))}
          </ul>
          <p>
            <MetricsLine metrics={data.metrics} />
          </p>

          {data.documents.length > 0 && (
            <>
              <h3>Основание</h3>
              <ul className="why">
                {data.documents.map((d) => (
                  <li key={d}>
                    <Icon name="doc" size={14} /> {d}
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.calculated_at && (
            <p className="muted">Расчёт на {fmtDateTime(data.calculated_at)}</p>
          )}
        </>
      )}

      {editing && data && (
        <DataEditor
          organizationId={organizationId}
          year={year}
          onClose={() => setEditing(false)}
          onSaved={() => {
            void state.reload({ silent: true })
            onChanged()
          }}
        />
      )}
      {requesting && data && slot && (
        <RequestDialog
          organizationId={organizationId}
          organization={data.organization}
          year={year}
          category={category}
          basis={basis}
          groups={slot.groups}
          groupId={requesting.group}
          onClose={() => setRequesting(null)}
          onCreated={(id) => navigate(`/requests?open=${id}`)}
        />
      )}
    </Drawer>
  )
}
