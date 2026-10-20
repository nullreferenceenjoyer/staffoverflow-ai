import { useState } from 'react'

import { StaffingMeta } from '../../api'
import { ImportDialog } from '../../components/ImportDialog'
import { Icon } from '../../components/icons'
import { Card } from '../../components/ui'
import { ORG_TYPE_LABELS } from '../../lib'

type Kind = 'metrics' | 'lines' | 'norms'

const KINDS: { kind: Kind; title: string; about: string }[] = [
  {
    kind: 'metrics',
    title: 'Показатели учреждений',
    about: 'Обучающиеся, классы, группы и площадь по учебному году — от них считается норматив.',
  },
  {
    kind: 'lines',
    title: 'Штатка и занятость',
    about:
      'Утверждённые и занятые ставки по группам должностей и средний оклад за ставку. Только итоги — без ФИО и договоров. Каждая загрузка сохраняется в истории штатки.',
  },
  {
    kind: 'norms',
    title: 'Нормативы',
    about: 'Региональные коэффициенты: «1 ставка на 300 обучающихся». Документы заводятся заранее.',
  },
]

/** Загрузка из Excel или CSV: без неё раздел для сотен учреждений не заполнить. */
export function Imports({ meta, onDone }: { meta: StaffingMeta; onDone: () => void }) {
  const [open, setOpen] = useState<Kind | null>(null)
  const kinds = KINDS.filter((k) => k.kind !== 'norms' || meta.permissions.import_norms)
  const current = KINDS.find((k) => k.kind === open)

  return (
    <>
      <div className="grid-3">
        {kinds.map((k) => (
          <Card key={k.kind} title={k.title}>
            <p className="muted">{k.about}</p>
            <button onClick={() => setOpen(k.kind)}>
              <Icon name="upload" size={16} /> Загрузить из Excel
            </button>
          </Card>
        ))}
      </div>
      <p className="muted">
        После загрузки анализ пересчитывается сам. Ошибки показываются по строкам — исправьте их в
        файле и загрузите его снова: уже загруженное не задвоится.
      </p>

      <Card title="Коды групп для шаблонов">
        <table className="stack compact">
          <thead>
            <tr>
              <th>Код</th>
              <th>Группа</th>
              <th>Категория</th>
              <th>Для кого</th>
              <th>Должности</th>
            </tr>
          </thead>
          <tbody>
            {meta.groups.map((g) => (
              <tr key={g.id}>
                <td data-label="Код">
                  <code>{g.code}</code>
                </td>
                <td data-label="Группа">{g.name}</td>
                <td data-label="Категория">{g.category === 'aup' ? 'АУП' : 'Вспомогательный'}</td>
                <td data-label="Для кого">
                  {g.institution_types.length
                    ? g.institution_types.map((t) => ORG_TYPE_LABELS[t] ?? t).join(', ')
                    : 'все'}
                </td>
                <td data-label="Должности" className="muted">
                  {g.positions ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {current && (
        <ImportDialog
          kind={`staffing-${current.kind}`}
          title={`Загрузка: ${current.title.toLowerCase()}`}
          uploadUrl={`/staffing/import/${current.kind}`}
          templateUrl={`/staffing/templates/${current.kind}.xlsx`}
          onClose={() => setOpen(null)}
          onDone={onDone}
        />
      )}
    </>
  )
}
