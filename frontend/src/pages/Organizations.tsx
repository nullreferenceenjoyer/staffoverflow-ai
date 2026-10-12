import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, OrgSummary } from '../api'
import { useUser } from '../App'
import { Async, Card, Delta, Field, Form, Modal, MunicipalitySelect, Page } from '../components/ui'
import { canEdit, fmt, fmtInt, fmtMoney, ORG_TYPE_LABELS, useApi } from '../lib'

interface ImportResult {
  imported: number
  skipped: number
  organizations: number
  dropped_columns: string[]
  errors: string[]
}

function ImportDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState<'staffing' | 'enrollment'>('staffing')
  const [file, setFile] = useState<File | null>(null)
  const [replace, setReplace] = useState(true)
  const [result, setResult] = useState<ImportResult | null>(null)

  async function submit() {
    if (!file) throw new Error('Выберите файл')
    const form = new FormData()
    form.set('file', file)
    form.set('replace', String(replace))
    setResult(await api<ImportResult>(`/import/${kind}`, { form }))
    onDone()
  }

  return (
    <Modal title="Импорт данных" onClose={onClose}>
      <Form onSubmit={submit} submitLabel="Загрузить">
        <Field label="Что загружаем">
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="staffing">Штатное расписание</option>
            <option value="enrollment">Контингент</option>
          </select>
        </Field>
        <Field label="Файл CSV или XLSX">
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        {kind === 'staffing' ? (
          <>
            <label className="check">
              <input
                type="checkbox"
                checked={replace}
                onChange={(e) => setReplace(e.target.checked)}
              />
              Заменить расписание учреждений, которые есть в файле
            </label>
            <p className="muted">
              Колонки: Организация, Подразделение, Должность, Количество ставок, ФОТ, Сотрудник,
              Часов в неделю. ФИО заменяется обезличенным идентификатором, остальные колонки
              (паспорт, СНИЛС и т. п.) не сохраняются.
            </p>
          </>
        ) : (
          <p className="muted">
            Колонки: Организация, Учебный год, Ступень (дошкольное, начальное, основное, среднее),
            Форма обучения, Классов, Обучающихся, ОВЗ.
          </p>
        )}
      </Form>
      {result && (
        <div className="notice">
          Загружено строк: {result.imported}, пропущено: {result.skipped}, учреждений:{' '}
          {result.organizations}.
          {result.dropped_columns.length > 0 && (
            <div>Не сохранены колонки: {result.dropped_columns.join(', ')}.</div>
          )}
          {result.errors.map((e) => (
            <div key={e} className="delta-minus">
              {e}
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

type SortKey = 'name' | 'students' | 'actual' | 'delta' | 'compliance' | 'saving_potential_year'

export function Organizations() {
  const user = useUser()
  const [municipality, setMunicipality] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('saving_potential_year')
  const [importing, setImporting] = useState(false)
  const state = useApi<OrgSummary[]>('/organizations', { municipality_id: municipality })

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const filtered = (state.data ?? []).filter((o) => o.name.toLowerCase().includes(needle))
    const value = (o: OrgSummary) => (sort === 'delta' ? o.actual - o.norm : o[sort])
    return filtered.sort((a, b) =>
      sort === 'name' ? a.name.localeCompare(b.name, 'ru') : Number(value(b)) - Number(value(a)),
    )
  }, [state.data, search, sort])

  const header = (key: SortKey, label: string, numeric = true) => (
    <th className={numeric ? 'num sortable' : 'sortable'} onClick={() => setSort(key)}>
      {label}
      {sort === key && ' ↓'}
    </th>
  )

  return (
    <Page
      title="Учреждения"
      hint="Факт и норматив по каждому учреждению. Нажмите на заголовок столбца, чтобы отсортировать."
      actions={
        <>
          <input
            type="search"
            placeholder="Поиск по названию"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <MunicipalitySelect value={municipality} onChange={setMunicipality} />
          {canEdit(user) && (
            <button className="primary" onClick={() => setImporting(true)}>
              Импорт
            </button>
          )}
        </>
      }
    >
      <Card>
        <Async state={state}>
          {() => (
            <table>
              <thead>
                <tr>
                  {header('name', 'Учреждение', false)}
                  <th>Тип</th>
                  {header('students', 'Обучающихся')}
                  {header('actual', 'Факт, ст.')}
                  <th className="num">Норматив, ст.</th>
                  {header('delta', 'Отклонение')}
                  {header('compliance', 'Соответствие')}
                  {header('saving_potential_year', 'Экономия в год')}
                </tr>
              </thead>
              <tbody>
                {/* Тысяча строк в таблице браузеру по силам, но листать её неудобно */}
                {rows.slice(0, 300).map((o) => (
                  <tr key={o.id}>
                    <td>
                      <Link to={`/organizations/${o.id}`}>{o.name}</Link>
                    </td>
                    <td>{ORG_TYPE_LABELS[o.org_type] ?? o.org_type}</td>
                    <td className="num">{fmtInt(o.students)}</td>
                    <td className="num">{fmt(o.actual)}</td>
                    <td className="num">{fmt(o.norm)}</td>
                    <td className="num">
                      <Delta value={o.actual - o.norm} />
                    </td>
                    <td className="num">{fmt(o.compliance)} %</td>
                    <td className="num">{fmtMoney(o.saving_potential_year)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Async>
        {rows.length > 300 && (
          <p className="muted">
            Показаны первые 300 из {rows.length}. Уточните поиск или выберите муниципалитет.
          </p>
        )}
      </Card>
      {importing && <ImportDialog onClose={() => setImporting(false)} onDone={state.reload} />}
    </Page>
  )
}
