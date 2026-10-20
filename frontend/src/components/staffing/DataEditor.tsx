import { useMemo, useState } from 'react'

import { api, StaffingData } from '../../api'
import { fmtDateTime, fmtRub, fmtRubDelta, useApi } from '../../lib'
import { Field, Form, Modal } from '../ui'

const toInput = (value: number | null) => (value === null ? '' : String(value).replace('.', ','))

function parse(value: string): number | null {
  const text = value.trim().replace(/\s/g, '').replace(',', '.')
  if (!text) return null
  const parsed = Number(text)
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error(`«${value}» — не число`)
  return parsed
}

/** Число из поля ввода без исключений — для подсказки «как изменится ФОТ». */
function soft(value: string): number | null {
  try {
    return parse(value)
  } catch {
    return null
  }
}

/** ФОТ за год: Σ оклад × утверждённые ставки × 12. */
function payroll(lines: { approved: string; salary: string }[]) {
  return lines.reduce((sum, l) => sum + (soft(l.approved) ?? 0) * (soft(l.salary) ?? 0) * 12, 0)
}

/**
 * Штатка, занятость, оклады и показатели учреждения за год. Только итоги по группам
 * должностей: средний оклад за ставку, без ФИО.
 */
export function DataEditor({
  organizationId,
  year,
  onClose,
  onSaved,
}: {
  organizationId: number
  year: string
  onClose: () => void
  onSaved: () => void
}) {
  const state = useApi<StaffingData>(`/staffing/institutions/${organizationId}/data`, { year })
  const data = state.data
  return (
    <Modal
      title={data ? `Данные: ${data.organization}` : 'Данные учреждения'}
      onClose={onClose}
      wide
    >
      {state.error ? (
        <div className="notice notice-error">{state.error}</div>
      ) : !data ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : (
        <Editor data={data} year={year} onSaved={onSaved} onClose={onClose} />
      )}
    </Modal>
  )
}

function Editor({
  data,
  year,
  onSaved,
  onClose,
}: {
  data: StaffingData
  year: string
  onSaved: () => void
  onClose: () => void
}) {
  const school = data.org_type !== 'preschool'
  const kindergarten = data.org_type !== 'school'
  const [metrics, setMetrics] = useState({
    students_count: toInput(data.metrics.students_count),
    classes_count: toInput(data.metrics.classes_count),
    groups_count: toInput(data.metrics.groups_count),
    total_area_m2: toInput(data.metrics.total_area_m2),
  })
  const [lines, setLines] = useState(
    data.lines.map((l) => ({
      id: l.id,
      name: l.name,
      positions: l.positions,
      category: l.category,
      approved: toInput(l.approved),
      occupied: toInput(l.occupied),
      salary: toInput(l.salary),
    })),
  )
  const before = useMemo(() => payroll(lines), []) // eslint-disable-line react-hooks/exhaustive-deps
  const after = payroll(lines)
  const [approved, setApproved] = useState(data.schedule?.status === 'approved')
  const [comment, setComment] = useState(data.schedule?.comment ?? '')

  function setLine(i: number, key: 'approved' | 'occupied' | 'salary', value: string) {
    setLines(lines.map((l, j) => (j === i ? { ...l, [key]: value } : l)))
  }

  async function save() {
    const whole = (value: string, label: string) => {
      const parsed = parse(value)
      if (parsed !== null && !Number.isInteger(parsed)) throw new Error(`${label} — целое число`)
      return parsed
    }
    await api(`/staffing/institutions/${data.organization_id}/data`, {
      method: 'PUT',
      body: {
        year,
        students_count: whole(metrics.students_count, 'Обучающиеся'),
        classes_count: whole(metrics.classes_count, 'Классы'),
        groups_count: whole(metrics.groups_count, 'Группы'),
        total_area_m2: parse(metrics.total_area_m2),
        status: approved ? 'approved' : 'draft',
        comment: comment || null,
        lines: lines
          .map((l) => ({
            group_id: l.id,
            approved_fte: parse(l.approved),
            occupied_fte: parse(l.occupied),
            salary_rub: parse(l.salary) || null,
          }))
          .filter((l) => l.approved_fte !== null || l.occupied_fte !== null),
      },
    })
    onSaved()
    onClose()
  }

  const metric = (key: keyof typeof metrics, label: string) => (
    <Field label={label}>
      <input
        inputMode="decimal"
        value={metrics[key]}
        onChange={(e) => setMetrics({ ...metrics, [key]: e.target.value })}
      />
    </Field>
  )

  return (
    <Form onSubmit={save}>
      <p className="muted">
        {year}. Только итоги по группам должностей: ставки и средний оклад одной ставки, без ФИО и
        договоров. ФОТ = оклад × ставки × 12.
        {data.schedule?.updated_at && ` Изменено ${fmtDateTime(data.schedule.updated_at)}.`}
      </p>
      <h3>Показатели учреждения</h3>
      <div className="row">
        {metric('students_count', school ? 'Обучающиеся' : 'Воспитанники')}
        {school && metric('classes_count', 'Классы')}
        {kindergarten && metric('groups_count', 'Группы')}
        {metric('total_area_m2', 'Площадь, м²')}
      </div>

      <h3>Ставки по группам</h3>
      <table className="stack compact">
        <thead>
          <tr>
            <th>Группа</th>
            <th className="num">Утверждено</th>
            <th className="num">Занято</th>
            <th className="num">Оклад, ₽/мес</th>
            <th className="num">ФОТ, ₽/год</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={l.id}>
              <td data-label="Группа">
                {l.name}
                <div className="muted small-text">
                  {l.category === 'aup' ? 'АУП' : 'Вспомогательный'}
                  {l.positions ? ` · ${l.positions}` : ''}
                </div>
              </td>
              <td data-label="Утверждено" className="num">
                <input
                  className="fte"
                  inputMode="decimal"
                  aria-label={`${l.name}: утверждено ставок`}
                  value={l.approved}
                  onChange={(e) => setLine(i, 'approved', e.target.value)}
                />
              </td>
              <td data-label="Занято" className="num">
                <input
                  className="fte"
                  inputMode="decimal"
                  aria-label={`${l.name}: занято ставок`}
                  placeholder="не ведётся"
                  value={l.occupied}
                  onChange={(e) => setLine(i, 'occupied', e.target.value)}
                />
              </td>
              <td data-label="Оклад, ₽/мес" className="num">
                <input
                  className="salary"
                  inputMode="decimal"
                  aria-label={`${l.name}: средний оклад за ставку`}
                  placeholder="не указан"
                  value={l.salary}
                  onChange={(e) => setLine(i, 'salary', e.target.value)}
                />
              </td>
              <td data-label="ФОТ, ₽/год" className="num muted">
                {soft(l.salary) && soft(l.approved)
                  ? fmtRub((soft(l.approved) ?? 0) * (soft(l.salary) ?? 0) * 12)
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={`payroll-preview ${after !== before ? 'changed' : ''}`} aria-live="polite">
        <span>ФОТ по штатке</span>
        <strong>{fmtRub(after)} в год</strong>
        {after !== before && (
          <span className={after < before ? 'dev-calm' : 'dev-surplus'}>
            {fmtRubDelta(after - before)} к сохранённой штатке
          </span>
        )}
      </div>
      <p className="muted">
        Пустое «Занято» — занятость не ведётся: анализ «по занятости» для группы покажет «нет
        данных», а «по штатке» посчитается.
      </p>
      <label className="check">
        <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
        Штатное расписание утверждено — использовать в анализе
      </label>
      <Field label="Комментарий">
        <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} />
      </Field>
    </Form>
  )
}
