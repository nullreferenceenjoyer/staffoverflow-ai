import { useEffect, useState } from 'react'

import { api, StaffBasis, StaffCategory, StaffingDraft, StaffingResult } from '../../api'
import { fmtDeviation } from '../../lib'
import { Field, Form, Modal } from '../ui'

/**
 * Заявка из анализа: обычная заявка, но тема, адресат и текст уже подобраны.
 * Текст можно поправить перед отправкой.
 */
export function RequestDialog({
  organizationId,
  organization,
  year,
  category,
  basis,
  groups,
  groupId,
  onClose,
  onCreated,
}: {
  organizationId: number
  organization: string
  year: string
  category: StaffCategory
  basis: StaffBasis
  groups: StaffingResult[]
  groupId: number | null
  onClose: () => void
  onCreated: (requestId: number) => void
}) {
  const [group, setGroup] = useState<number | null>(groupId)
  const [draft, setDraft] = useState<StaffingDraft | null>(null)
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setDraft(null)
    setError(null)
    api<StaffingDraft>('/staffing/request-draft', {
      query: { organization_id: organizationId, year, category, basis, group_id: group },
    })
      .then((d) => {
        if (!alive) return
        setDraft(d)
        setTitle(d.title)
        setText(d.text)
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : 'Не удалось'))
    return () => {
      alive = false
    }
  }, [organizationId, year, category, basis, group])

  // Заявку обычно пишут о том, что не в норме: такие группы — первыми
  const choices = [...groups].sort(
    (a, b) =>
      Number(a.status === 'normal') - Number(b.status === 'normal') ||
      Math.abs(b.deviation ?? 0) - Math.abs(a.deviation ?? 0),
  )

  return (
    <Modal title="Заявка по результатам анализа" onClose={onClose} wide>
      <Form
        submitLabel="Создать заявку"
        onSubmit={async () => {
          const created = await api<{ request_id: number }>('/staffing/requests', {
            body: {
              organization_id: organizationId,
              year,
              category,
              basis,
              group_id: group,
              title,
              text,
            },
          })
          onCreated(created.request_id)
        }}
      >
        <p className="muted">
          {organization} · {year}
        </p>
        <Field label="О чём заявка">
          <select
            value={group ?? ''}
            onChange={(e) => setGroup(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Вся категория</option>
            {choices.map((g) => (
              <option key={g.id} value={g.group_id ?? ''}>
                {g.group} — {g.status_title.toLowerCase()}
                {g.deviation !== null && g.status !== 'normal'
                  ? ` ${fmtDeviation(g.deviation)}`
                  : ''}
              </option>
            ))}
          </select>
        </Field>
        {error && <div className="notice notice-error">{error}</div>}
        {draft ? (
          <>
            <dl className="facts">
              <dt>Тема</dt>
              <dd>{draft.topic_title}</dd>
              <dt>Кому</dt>
              <dd>{draft.routed_role_title}</dd>
            </dl>
            <Field label="Заголовок">
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
            </Field>
            <Field label="Текст заявки">
              <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            <p className="muted">
              Заявка сохранит снимок анализа: если норматив потом изменится, в ней останется картина
              на сегодня.
            </p>
          </>
        ) : (
          !error && <div className="skeleton" style={{ height: 180 }} />
        )}
      </Form>
    </Modal>
  )
}
