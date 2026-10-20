import { useMemo, useState } from 'react'

import { api, NormCoefficient, NormDocument, RequestMeta, StaffingMeta } from '../../api'
import { useUser } from '../../App'
import { Icon } from '../../components/icons'
import { Async, Badge, Card, Empty, Field, Form, Modal, Segmented } from '../../components/ui'
import { fmtDate, useApi } from '../../lib'

const STATE: Record<NormCoefficient['state'], { label: string; tone: string }> = {
  active: { label: 'Действует', tone: 'green' },
  future: { label: 'Вступит в силу', tone: 'blue' },
  expired: { label: 'Истёк', tone: 'gray' },
  inactive: { label: 'Документ не действует', tone: 'gray' },
}

const text = (value: number | string | null | undefined) =>
  value === null || value === undefined ? '' : String(value).replace('.', ',')

function numberOrNull(value: string, label: string): number | null {
  const cleaned = value.trim().replace(/\s/g, '').replace(',', '.')
  if (!cleaned) return null
  const parsed = Number(cleaned)
  if (!Number.isFinite(parsed)) throw new Error(`${label}: нужно число`)
  return parsed
}

function period(c: { effective_from: string | null; effective_to: string | null }) {
  if (!c.effective_from && !c.effective_to) return 'бессрочно'
  if (!c.effective_to) return `с ${fmtDate(c.effective_from)}`
  if (!c.effective_from) return `до ${fmtDate(c.effective_to)}`
  return `${fmtDate(c.effective_from)} — ${fmtDate(c.effective_to)}`
}

function CoefficientEditor({
  meta,
  coefficient,
  documents,
  onClose,
  onSaved,
}: {
  meta: StaffingMeta
  coefficient: NormCoefficient | null
  documents: NormDocument[]
  onClose: () => void
  onSaved: () => void
}) {
  const user = useUser()
  const regional = meta.permissions.edit_regional_norms
  const organizations = useApi<RequestMeta>('/requests/meta').data?.organizations ?? []
  const [draft, setDraft] = useState({
    group_id: String(coefficient?.group_id ?? meta.groups[0]?.id ?? ''),
    document_id: String(coefficient?.document_id ?? ''),
    institution_type: coefficient?.institution_type ?? 'all',
    scope_level: coefficient?.scope_level ?? (regional ? 'region' : 'municipality'),
    scope_id: String(coefficient?.scope_id ?? (regional ? '' : (user.municipality_id ?? ''))),
    metric: coefficient?.metric ?? 'students_count',
    unit_size: text(coefficient?.unit_size),
    fte_per_unit: text(coefficient?.fte_per_unit ?? 1),
    min_fte: text(coefficient?.min_fte),
    max_fte: text(coefficient?.max_fte),
    applies_from: text(coefficient?.applies_from),
    applies_to: text(coefficient?.applies_to),
    rounding_step: text(coefficient?.rounding_step ?? 0.25),
    rounding_mode: coefficient?.rounding_mode ?? 'up',
    tolerance_abs: text(coefficient?.tolerance_abs),
    tolerance_pct: text(coefficient?.tolerance_pct),
    priority: String(coefficient?.priority ?? 0),
    effective_from: coefficient?.effective_from ?? '',
    effective_to: coefficient?.effective_to ?? '',
    is_mandatory: coefficient?.is_mandatory ?? true,
    comment: coefficient?.comment ?? '',
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })
  const fixed = draft.metric === 'none'

  async function save() {
    const body = {
      group_id: Number(draft.group_id),
      document_id: draft.document_id ? Number(draft.document_id) : null,
      institution_type: draft.institution_type,
      scope_level: draft.scope_level,
      scope_id: draft.scope_level === 'region' ? null : Number(draft.scope_id) || null,
      metric: draft.metric,
      unit_size: fixed ? null : numberOrNull(draft.unit_size, 'На сколько единиц'),
      fte_per_unit: numberOrNull(draft.fte_per_unit, 'Ставок') ?? 0,
      min_fte: numberOrNull(draft.min_fte, 'Минимум'),
      max_fte: numberOrNull(draft.max_fte, 'Максимум'),
      applies_from: fixed ? null : numberOrNull(draft.applies_from, 'Показатель от'),
      applies_to: fixed ? null : numberOrNull(draft.applies_to, 'Показатель до'),
      rounding_step: numberOrNull(draft.rounding_step, 'Шаг округления'),
      rounding_mode: draft.rounding_mode,
      tolerance_abs: numberOrNull(draft.tolerance_abs, 'Допуск'),
      tolerance_pct: numberOrNull(draft.tolerance_pct, 'Допуск, %'),
      priority: Number(draft.priority) || 0,
      effective_from: draft.effective_from || null,
      effective_to: draft.effective_to || null,
      is_mandatory: draft.is_mandatory,
      comment: draft.comment || null,
    }
    if (coefficient) await api(`/norms/coefficients/${coefficient.id}`, { method: 'PUT', body })
    else await api('/norms/coefficients', { body })
    onSaved()
    onClose()
  }

  async function remove() {
    if (!coefficient || !window.confirm('Удалить норматив? Анализ будет пересчитан.')) return
    await api(`/norms/coefficients/${coefficient.id}`, { method: 'DELETE' })
    onSaved()
    onClose()
  }

  return (
    <Modal title={coefficient ? 'Норматив' : 'Новый норматив'} onClose={onClose} wide>
      <Form onSubmit={save}>
        <div className="row">
          <Field label="Группа">
            <select value={draft.group_id} onChange={(e) => set('group_id', e.target.value)}>
              {meta.groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.category === 'aup' ? 'АУП' : 'Вспом.'} · {g.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Для каких учреждений">
            <select
              value={draft.institution_type}
              onChange={(e) => set('institution_type', e.target.value)}
            >
              {meta.institution_types.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.title}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="row">
          <Field label="Показатель">
            <select value={draft.metric} onChange={(e) => set('metric', e.target.value)}>
              {meta.metrics.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Ставок">
            <input
              inputMode="decimal"
              value={draft.fte_per_unit}
              onChange={(e) => set('fte_per_unit', e.target.value)}
              required
            />
          </Field>
          {!fixed && (
            <Field label="На сколько единиц">
              <input
                inputMode="decimal"
                placeholder="пусто — не зависит от размера"
                value={draft.unit_size}
                onChange={(e) => set('unit_size', e.target.value)}
              />
            </Field>
          )}
        </div>
        <p className="muted">
          Например: «1 ставка на 300 обучающихся» — показатель «Обучающиеся», ставок 1, на 300
          единиц. Без «на сколько единиц» норматив даёт фиксированное число ставок.
        </p>
        <div className="row">
          {!fixed && (
            <>
              <Field label="Действует при показателе от">
                <input
                  inputMode="decimal"
                  value={draft.applies_from}
                  onChange={(e) => set('applies_from', e.target.value)}
                />
              </Field>
              <Field label="до">
                <input
                  inputMode="decimal"
                  value={draft.applies_to}
                  onChange={(e) => set('applies_to', e.target.value)}
                />
              </Field>
            </>
          )}
          <Field label="Минимум ставок">
            <input
              inputMode="decimal"
              value={draft.min_fte}
              onChange={(e) => set('min_fte', e.target.value)}
            />
          </Field>
          <Field label="Максимум ставок">
            <input
              inputMode="decimal"
              value={draft.max_fte}
              onChange={(e) => set('max_fte', e.target.value)}
            />
          </Field>
        </div>
        <div className="row">
          <Field label="Округление">
            <select
              value={draft.rounding_step}
              onChange={(e) => set('rounding_step', e.target.value)}
            >
              <option value="">до сотых</option>
              <option value="0,25">до 0,25</option>
              <option value="0,5">до 0,5</option>
              <option value="1">до целой ставки</option>
            </select>
          </Field>
          <Field label="В какую сторону">
            <select
              value={draft.rounding_mode}
              onChange={(e) =>
                set('rounding_mode', e.target.value as NormCoefficient['rounding_mode'])
              }
            >
              <option value="up">в большую</option>
              <option value="down">в меньшую</option>
              <option value="nearest">математически</option>
            </select>
          </Field>
          <Field label="Допуск, ставок">
            <input
              inputMode="decimal"
              placeholder="0,25"
              value={draft.tolerance_abs}
              onChange={(e) => set('tolerance_abs', e.target.value)}
            />
          </Field>
          <Field label="Допуск, %">
            <input
              inputMode="decimal"
              placeholder="5"
              value={draft.tolerance_pct}
              onChange={(e) => set('tolerance_pct', e.target.value)}
            />
          </Field>
        </div>
        <div className="row">
          <Field label="Документ-основание">
            <select value={draft.document_id} onChange={(e) => set('document_id', e.target.value)}>
              <option value="">Не указан</option>
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                  {d.status !== 'active' ? ` (${d.status_title.toLowerCase()})` : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Действует с">
            <input
              type="date"
              value={draft.effective_from}
              onChange={(e) => set('effective_from', e.target.value)}
            />
          </Field>
          <Field label="по">
            <input
              type="date"
              value={draft.effective_to}
              onChange={(e) => set('effective_to', e.target.value)}
            />
          </Field>
        </div>
        <div className="row">
          <Field label="Уровень">
            <select
              value={draft.scope_level}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  scope_level: e.target.value as NormCoefficient['scope_level'],
                  scope_id:
                    e.target.value === 'municipality' && !regional
                      ? String(user.municipality_id ?? '')
                      : '',
                })
              }
            >
              {meta.scope_levels
                .filter((s) => regional || s.code !== 'region')
                .map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.title}
                  </option>
                ))}
            </select>
          </Field>
          {draft.scope_level === 'municipality' && (
            <Field label="Муниципалитет">
              <select value={draft.scope_id} onChange={(e) => set('scope_id', e.target.value)}>
                <option value="">Выберите…</option>
                {meta.municipalities.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {draft.scope_level === 'organization' && (
            <Field label="Учреждение">
              <select value={draft.scope_id} onChange={(e) => set('scope_id', e.target.value)}>
                <option value="">Выберите…</option>
                {organizations.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Приоритет">
            <input
              inputMode="numeric"
              value={draft.priority}
              onChange={(e) => set('priority', e.target.value)}
            />
          </Field>
        </div>
        <p className="muted">
          Местный норматив учреждения важнее муниципального, муниципальный — регионального, норматив
          для типа учреждения — общего. При равенстве берётся больший приоритет, а нормативы одного
          уровня складываются.
        </p>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.is_mandatory}
            onChange={(e) => set('is_mandatory', e.target.checked)}
          />
          Обязательный норматив (иначе — рекомендация)
        </label>
        <Field label="Пояснение">
          <input value={draft.comment} onChange={(e) => set('comment', e.target.value)} />
        </Field>
        {coefficient && (
          <button type="button" className="danger" onClick={remove}>
            Удалить норматив
          </button>
        )}
      </Form>
    </Modal>
  )
}

function DocumentEditor({
  meta,
  document,
  onClose,
  onSaved,
}: {
  meta: StaffingMeta
  document: NormDocument | null
  onClose: () => void
  onSaved: () => void
}) {
  const regional = meta.permissions.edit_regional_norms
  const [draft, setDraft] = useState({
    title: document?.title ?? '',
    doc_type: document?.doc_type ?? 'приказ',
    number: document?.number ?? '',
    issued_at: document?.issued_at ?? '',
    effective_from: document?.effective_from ?? '',
    effective_to: document?.effective_to ?? '',
    issuer: document?.issuer ?? '',
    scope_level: document?.scope_level ?? (regional ? 'region' : 'municipality'),
    status: document?.status ?? 'active',
    source_ref: document?.source_ref ?? '',
  })
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })

  async function save() {
    const body = Object.fromEntries(
      Object.entries(draft).map(([k, v]) => [k, typeof v === 'string' && !v ? null : v]),
    )
    if (document) await api(`/norms/documents/${document.id}`, { method: 'PUT', body })
    else await api('/norms/documents', { body })
    onSaved()
    onClose()
  }

  async function remove() {
    if (!document || !window.confirm(`Удалить «${document.label}»?`)) return
    await api(`/norms/documents/${document.id}`, { method: 'DELETE' })
    onSaved()
    onClose()
  }

  return (
    <Modal title={document ? 'Документ-основание' : 'Новый документ'} onClose={onClose} wide>
      <Form onSubmit={save}>
        <Field label="Название">
          <input value={draft.title} onChange={(e) => set('title', e.target.value)} required />
        </Field>
        <div className="row">
          <Field label="Вид">
            <input
              list="doc-types"
              value={draft.doc_type}
              onChange={(e) => set('doc_type', e.target.value)}
              required
            />
            <datalist id="doc-types">
              {meta.doc_types.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </Field>
          <Field label="Номер">
            <input value={draft.number} onChange={(e) => set('number', e.target.value)} />
          </Field>
          <Field label="Дата">
            <input
              type="date"
              value={draft.issued_at}
              onChange={(e) => set('issued_at', e.target.value)}
            />
          </Field>
        </div>
        <div className="row">
          <Field label="Действует с">
            <input
              type="date"
              value={draft.effective_from}
              onChange={(e) => set('effective_from', e.target.value)}
            />
          </Field>
          <Field label="по">
            <input
              type="date"
              value={draft.effective_to}
              onChange={(e) => set('effective_to', e.target.value)}
            />
          </Field>
          <Field label="Статус">
            <select
              value={draft.status}
              onChange={(e) => set('status', e.target.value as NormDocument['status'])}
            >
              {meta.doc_statuses.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.title}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="row">
          <Field label="Кто издал">
            <input value={draft.issuer} onChange={(e) => set('issuer', e.target.value)} />
          </Field>
          <Field label="Уровень">
            <select
              value={draft.scope_level}
              onChange={(e) => set('scope_level', e.target.value as NormDocument['scope_level'])}
            >
              {meta.scope_levels
                .filter((s) => regional || s.code !== 'region')
                .map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.title}
                  </option>
                ))}
            </select>
          </Field>
        </div>
        <Field label="Ссылка или реквизиты публикации">
          <input value={draft.source_ref} onChange={(e) => set('source_ref', e.target.value)} />
        </Field>
        <p className="muted">
          Хранятся только реквизиты — файл приказа загружать не нужно. Документ, который перестал
          действовать, переведите в «Заменён» или «В архиве»: его нормативы перестанут применяться.
        </p>
        {document && document.coefficients === 0 && (
          <button type="button" className="danger" onClick={remove}>
            Удалить документ
          </button>
        )}
      </Form>
    </Modal>
  )
}

export function Norms({ meta }: { meta: StaffingMeta }) {
  const user = useUser()
  const coefficients = useApi<NormCoefficient[]>('/norms/coefficients')
  const documents = useApi<NormDocument[]>('/norms/documents')
  const [category, setCategory] = useState<'all' | 'aup' | 'support'>('all')
  const [type, setType] = useState('')
  const [group, setGroup] = useState('')
  const [document, setDocument] = useState('')
  const [onlyActive, setOnlyActive] = useState(true)
  const [editing, setEditing] = useState<NormCoefficient | 'new' | null>(null)
  const [editingDoc, setEditingDoc] = useState<NormDocument | 'new' | null>(null)
  const canEdit = meta.permissions.edit_norms

  const shown = useMemo(
    () =>
      (coefficients.data ?? []).filter(
        (c) =>
          (category === 'all' || c.category === category) &&
          (!type || c.institution_type === type || c.institution_type === 'all') &&
          (!group || String(c.group_id) === group) &&
          (!document || String(c.document_id ?? '') === document) &&
          (!onlyActive || c.state === 'active'),
      ),
    [coefficients.data, category, type, group, document, onlyActive],
  )

  function changed() {
    void coefficients.reload({ silent: true })
    void documents.reload({ silent: true })
  }

  return (
    <>
      {user.role === 'director' && (
        <p className="muted">Показаны нормативы, которые применяются к вашему учреждению.</p>
      )}
      <Card
        title="Нормативы"
        aside={
          canEdit && (
            <button className="primary" onClick={() => setEditing('new')}>
              <Icon name="plus" size={16} /> Добавить норматив
            </button>
          )
        }
      >
        <div className="toolbar">
          <Segmented
            label="Категория"
            value={category}
            onChange={setCategory}
            options={[
              ['all', 'Все'],
              ['aup', 'АУП'],
              ['support', 'Вспомогательный'],
            ]}
          />
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            aria-label="Тип учреждения"
          >
            <option value="">Все типы учреждений</option>
            {meta.institution_types
              .filter((t) => t.code !== 'all')
              .map((t) => (
                <option key={t.code} value={t.code}>
                  {t.title}
                </option>
              ))}
          </select>
          <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Группа">
            <option value="">Все группы</option>
            {meta.groups
              .filter((g) => category === 'all' || g.category === category)
              .map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
          </select>
          <select
            value={document}
            onChange={(e) => setDocument(e.target.value)}
            aria-label="Документ"
          >
            <option value="">Все документы</option>
            {(documents.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.doc_type} № {d.number ?? '—'}
              </option>
            ))}
          </select>
          <button
            className={`chip ${onlyActive ? 'chip-on' : ''}`}
            aria-pressed={onlyActive}
            onClick={() => setOnlyActive(!onlyActive)}
          >
            Только действующие
          </button>
        </div>
        <Async state={coefficients}>
          {() =>
            shown.length === 0 ? (
              <Empty>
                {coefficients.data?.length
                  ? 'Под выбранные условия нормативов нет.'
                  : 'Нормативов пока нет. Без них анализ покажет «норматив не настроен».'}
              </Empty>
            ) : (
              <table className="stack">
                <thead>
                  <tr>
                    <th>Группа</th>
                    <th>Для кого</th>
                    <th>Показатель</th>
                    <th>Норматив</th>
                    <th>Документ</th>
                    <th>Действует</th>
                    <th>Статус</th>
                    {canEdit && <th />}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((c) => (
                    <tr key={c.id}>
                      <td data-label="Группа">
                        {c.group}
                        <div className="muted">
                          {c.category === 'aup' ? 'АУП' : 'Вспомогательный'}
                        </div>
                      </td>
                      <td data-label="Для кого">
                        {c.institution_type_title}
                        {c.scope_title && <div className="muted">только: {c.scope_title}</div>}
                      </td>
                      <td data-label="Показатель">{c.metric_title}</td>
                      <td data-label="Норматив">
                        {c.rule}
                        {!c.is_mandatory && <div className="muted">рекомендация</div>}
                      </td>
                      <td data-label="Документ" className="reason">
                        {c.document ?? <span className="muted">не указан</span>}
                      </td>
                      <td data-label="Действует">{period(c)}</td>
                      <td data-label="Статус">
                        <Badge tone={STATE[c.state].tone}>{STATE[c.state].label}</Badge>
                      </td>
                      {canEdit && (
                        <td className="row-action">
                          {c.can_edit && <button onClick={() => setEditing(c)}>Изменить</button>}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </Async>
      </Card>

      <Card
        title="Документы-основания"
        aside={
          canEdit && (
            <button onClick={() => setEditingDoc('new')}>
              <Icon name="plus" size={16} /> Добавить документ
            </button>
          )
        }
      >
        <Async state={documents}>
          {(items) =>
            items.length === 0 ? (
              <Empty>Документов пока нет.</Empty>
            ) : (
              <table className="stack">
                <thead>
                  <tr>
                    <th>Документ</th>
                    <th>Кто издал</th>
                    <th>Действует</th>
                    <th className="num">Нормативов</th>
                    <th>Статус</th>
                    {canEdit && <th />}
                  </tr>
                </thead>
                <tbody>
                  {items.map((d) => (
                    <tr key={d.id}>
                      <td data-label="Документ" className="reason">
                        {d.label}
                        {d.source_ref && <div className="muted">{d.source_ref}</div>}
                      </td>
                      <td data-label="Кто издал">{d.issuer ?? '—'}</td>
                      <td data-label="Действует">{period(d)}</td>
                      <td data-label="Нормативов" className="num">
                        {d.coefficients}
                      </td>
                      <td data-label="Статус">
                        <Badge tone={d.status === 'active' ? 'green' : 'gray'}>
                          {d.status_title}
                        </Badge>
                      </td>
                      {canEdit && (
                        <td className="row-action">
                          {(meta.permissions.edit_regional_norms || d.scope_level !== 'region') && (
                            <button onClick={() => setEditingDoc(d)}>Изменить</button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </Async>
      </Card>

      {editing && (
        <CoefficientEditor
          meta={meta}
          coefficient={editing === 'new' ? null : editing}
          documents={documents.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={changed}
        />
      )}
      {editingDoc && (
        <DocumentEditor
          meta={meta}
          document={editingDoc === 'new' ? null : editingDoc}
          onClose={() => setEditingDoc(null)}
          onSaved={changed}
        />
      )}
    </>
  )
}
