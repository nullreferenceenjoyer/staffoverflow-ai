import { useState } from 'react'

import { api, StaffingData } from '../../api'
import { fmtDateTime, useApi } from '../../lib'
import { Field, Form, Modal } from '../ui'

const toInput = (value: number | null) => (value === null ? '' : String(value).replace('.', ','))

function parse(value: string): number | null {
  const text = value.trim().replace(/\s/g, '').replace(',', '.')
  if (!text) return null
  const parsed = Number(text)
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error(`«${value}» — не число`)
  return parsed
}

/**
 * Показатели учреждения, от которых считается норматив, и утверждение штатки.
 * Сами должности правятся в таблице штатки — по одной.
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
      title={data ? `Показатели: ${data.organization}` : 'Показатели учреждения'}
      onClose={onClose}
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
    rooms_count: toInput(data.metrics.rooms_count),
  })
  const [approved, setApproved] = useState(data.schedule?.status === 'approved')
  const [comment, setComment] = useState(data.schedule?.comment ?? '')

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
        rooms_count: whole(metrics.rooms_count, 'Кабинеты'),
        status: approved ? 'approved' : 'draft',
        comment: comment || null,
      },
    })
    onSaved()
    onClose()
  }

  const metric = (key: keyof typeof metrics, label: string, hint: string) => (
    <Field label={label}>
      <input
        inputMode="decimal"
        value={metrics[key]}
        onChange={(e) => setMetrics({ ...metrics, [key]: e.target.value })}
        title={hint}
      />
    </Field>
  )

  return (
    <Form onSubmit={save}>
      <p className="muted">
        {year}. От этих цифр считается норматив: сколько ставок положено учреждению. Без нужного
        показателя система не скажет ни «лишние», ни «не хватает».
        {data.schedule?.updated_at && ` Изменено ${fmtDateTime(data.schedule.updated_at)}.`}
      </p>
      <div className="row">
        {metric(
          'students_count',
          school ? 'Обучающиеся' : 'Воспитанники',
          'Для делопроизводства, пищеблока, учебно-вспомогательных',
        )}
        {school && metric('classes_count', 'Классы', 'Для заместителей директора')}
        {kindergarten && metric('groups_count', 'Группы', 'Для помощников воспитателя')}
      </div>
      <div className="row">
        {metric('total_area_m2', 'Площадь, м²', 'Для уборщиков и хозотдела')}
        {metric('rooms_count', 'Кабинеты для уборки', 'Для норматива уборщиков по кабинетам')}
      </div>
      <label className="check">
        <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
        Штатное расписание утверждено — использовать в расчёте «высвободить»
      </label>
      <Field label="Комментарий к штатке">
        <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} />
      </Field>
      <p className="muted small-text">
        Должности, ставки и оклады меняются в таблице штатки: «Добавить должность», карандаш и
        корзина у каждой строки.
      </p>
    </Form>
  )
}
