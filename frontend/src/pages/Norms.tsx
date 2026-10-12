import { useState } from 'react'

import { api, Norm, NormMeta } from '../api'
import { useUser } from '../App'
import { ActionButton, Async, Badge, Card, Field, Form, Modal, Page } from '../components/ui'
import { canApprove, fmt, ORG_TYPE_LABELS, useApi } from '../lib'

const SOURCE: Record<Norm['source_kind'], { label: string; tone: string }> = {
  federal: { label: 'Федеральный', tone: 'green' },
  regional: { label: 'Региональный', tone: 'blue' },
  assumption: { label: 'Допущение', tone: 'amber' },
}

const BLANK: Omit<Norm, 'id'> = {
  code: '',
  title: '',
  kind: 'staff',
  function_code: 'teacher',
  org_types: [],
  driver: 'students_total',
  unit_size: 1,
  per_unit: 0,
  base: 0,
  threshold: 0,
  min_value: null,
  max_value: null,
  rounding: 0.25,
  centralization_effect: 0,
  source_kind: 'regional',
  legal_ref: null,
  document_id: null,
  is_active: true,
}

/** Формула словами: «0,5 + 1 × обучающихся / 300». */
function formula(norm: Norm, meta: NormMeta) {
  const driver = meta.drivers.find((d) => d.key === norm.driver)?.title ?? norm.driver
  const parts = []
  if (norm.base) parts.push(fmt(norm.base))
  if (norm.per_unit) {
    parts.push(
      `${fmt(norm.per_unit)} × ${driver}${norm.unit_size !== 1 ? ` / ${fmt(norm.unit_size)}` : ''}`,
    )
  }
  return parts.join(' + ') || '0'
}

function NormEditor({
  norm,
  meta,
  onClose,
  onSaved,
}: {
  norm: Norm | null
  meta: NormMeta
  onClose: () => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState<Omit<Norm, 'id'>>(norm ?? BLANK)
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) =>
    setDraft({ ...draft, [key]: value })

  async function save() {
    if (norm) await api(`/norms/${norm.id}`, { method: 'PUT', body: draft })
    else await api('/norms', { body: draft })
    onSaved()
    onClose()
  }

  const numeric = (
    key: 'base' | 'per_unit' | 'unit_size' | 'threshold' | 'rounding' | 'centralization_effect',
    label: string,
  ) => (
    <Field label={label}>
      <input
        type="number"
        step="any"
        value={draft[key]}
        onChange={(e) => set(key, Number(e.target.value))}
      />
    </Field>
  )
  const optional = (key: 'min_value' | 'max_value', label: string) => (
    <Field label={label}>
      <input
        type="number"
        step="any"
        value={draft[key] ?? ''}
        onChange={(e) => set(key, e.target.value === '' ? null : Number(e.target.value))}
      />
    </Field>
  )

  return (
    <Modal title={norm ? 'Норматив' : 'Новый норматив'} onClose={onClose} wide>
      <Form onSubmit={save}>
        <div className="row">
          <Field label="Код (латиницей)">
            <input
              value={draft.code}
              onChange={(e) => set('code', e.target.value)}
              pattern="[a-z0-9_]+"
              required
            />
          </Field>
          <Field label="Вид">
            <select
              value={draft.kind}
              onChange={(e) => set('kind', e.target.value as Norm['kind'])}
            >
              <option value="staff">Численность, ставок</option>
              <option value="allowance">Надбавка, ₽ в месяц</option>
            </select>
          </Field>
        </div>
        <Field label="Название">
          <input value={draft.title} onChange={(e) => set('title', e.target.value)} required />
        </Field>
        <div className="row">
          <Field label="Функция">
            <select
              value={draft.function_code}
              onChange={(e) => set('function_code', e.target.value)}
            >
              {meta.functions.map((f) => (
                <option key={f.code} value={f.code}>
                  {f.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Показатель учреждения">
            <select value={draft.driver} onChange={(e) => set('driver', e.target.value)}>
              {meta.drivers.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.title}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <p className="muted">
          Значение = база + коэффициент × показатель / размер единицы. Например, «1 ставка на 600
          м²»: коэффициент 1, размер единицы 600.
        </p>
        <div className="row">
          {numeric('base', 'База')}
          {numeric('per_unit', 'Коэффициент')}
          {numeric('unit_size', 'Размер единицы')}
        </div>
        <div className="row">
          {numeric('threshold', 'Применять от значения показателя')}
          {optional('min_value', 'Минимум')}
          {optional('max_value', 'Максимум')}
        </div>
        <div className="row">
          {numeric('rounding', 'Шаг округления')}
          {numeric('centralization_effect', 'Эффект централизации (0–0,9)')}
          <Field label="Источник">
            <select
              value={draft.source_kind}
              onChange={(e) => set('source_kind', e.target.value as Norm['source_kind'])}
            >
              {Object.entries(SOURCE).map(([key, { label }]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Типы учреждений (пусто — все)">
          <div className="chips">
            {Object.entries(ORG_TYPE_LABELS).map(([type, label]) => (
              <label key={type} className="check">
                <input
                  type="checkbox"
                  checked={draft.org_types.includes(type)}
                  onChange={(e) =>
                    set(
                      'org_types',
                      e.target.checked
                        ? [...draft.org_types, type]
                        : draft.org_types.filter((t) => t !== type),
                    )
                  }
                />
                {label}
              </label>
            ))}
          </div>
        </Field>
        <Field label="Основание (реквизиты документа)">
          <input
            value={draft.legal_ref ?? ''}
            onChange={(e) => set('legal_ref', e.target.value || null)}
          />
        </Field>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(e) => set('is_active', e.target.checked)}
          />
          Применять в расчётах
        </label>
      </Form>
    </Modal>
  )
}

export function Norms() {
  const user = useUser()
  const editable = canApprove(user)
  const state = useApi<Norm[]>('/norms')
  const meta = useApi<NormMeta>('/norms/meta')
  const [editing, setEditing] = useState<Norm | 'new' | null>(null)

  return (
    <Page
      title="Нормативы"
      hint="Формулы, по которым считается нормативная численность. Изменение норматива сразу пересчитывает все отчёты."
      actions={
        editable && (
          <button className="primary" onClick={() => setEditing('new')}>
            Добавить норматив
          </button>
        )
      }
    >
      <div className="notice">
        Нормативы с пометкой «Допущение» — рабочие значения для демонстрации. Перед использованием в
        управленческих решениях их нужно заменить утверждёнными региональными.
      </div>
      <Card>
        <Async state={state}>
          {(norms) => (
            <table>
              <thead>
                <tr>
                  <th>Норматив</th>
                  <th>Формула</th>
                  <th>Источник</th>
                  <th>Основание</th>
                  {editable && <th />}
                </tr>
              </thead>
              <tbody>
                {norms.map((norm) => (
                  <tr key={norm.id} className={norm.is_active ? undefined : 'inactive'}>
                    <td>
                      {norm.title}
                      {norm.kind === 'allowance' && <span className="muted"> · надбавка</span>}
                      {!norm.is_active && <span className="muted"> · отключён</span>}
                    </td>
                    <td className="nowrap">{meta.data ? formula(norm, meta.data) : ''}</td>
                    <td>
                      <Badge tone={SOURCE[norm.source_kind].tone}>
                        {SOURCE[norm.source_kind].label}
                      </Badge>
                    </td>
                    <td className="muted">{norm.legal_ref ?? '—'}</td>
                    {editable && (
                      <td className="nowrap">
                        <button onClick={() => setEditing(norm)}>Изменить</button>{' '}
                        <ActionButton
                          className="ghost"
                          confirm={`Удалить норматив «${norm.title}»?`}
                          onClick={async () => {
                            await api(`/norms/${norm.id}`, { method: 'DELETE' })
                            await state.reload()
                          }}
                        >
                          Удалить
                        </ActionButton>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Async>
      </Card>
      {editing && meta.data && (
        <NormEditor
          norm={editing === 'new' ? null : editing}
          meta={meta.data}
          onClose={() => setEditing(null)}
          onSaved={state.reload}
        />
      )}
    </Page>
  )
}
