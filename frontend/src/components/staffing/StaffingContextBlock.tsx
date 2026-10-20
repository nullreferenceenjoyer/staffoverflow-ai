import { Link } from 'react-router-dom'

import { StaffingContext } from '../../api'
import { fmtDate, fmtFte } from '../../lib'
import { Icon } from '../icons'
import { Deviation, factLabel, StatusBadge } from './parts'

/**
 * Суть нормативного анализа в карточке заявки — без всей таблицы групп.
 * Значения — на момент создания связи: если норматив потом поменяли, здесь прежняя картина.
 */
export function StaffingContextBlock({ items }: { items: StaffingContext[] }) {
  if (!items.length) return null
  return (
    <section className="staffing-context">
      <h3>
        <Icon name="scale" size={14} /> Нормативная численность
      </h3>
      {items.map((item) => (
        <div key={item.link_id} className="staffing-context-item">
          <div className="muted">
            {item.year} · {item.category_title} · {item.basis_title}
          </div>
          <dl className="facts">
            <dt>Группа</dt>
            <dd>{item.group ?? 'вся категория'}</dd>
            <dt>Норматив</dt>
            <dd>{fmtFte(item.required)} ставки</dd>
            <dt>{factLabel(item.basis)}</dt>
            <dd>{fmtFte(item.fact)} ставки</dd>
            <dt>Отклонение</dt>
            <dd>
              <Deviation value={item.deviation} status={item.status} /> ставки
            </dd>
            <dt>Статус</dt>
            <dd>
              <StatusBadge status={item.status} />
              {item.reasons.length > 0 && <div className="muted">{item.reasons.join('; ')}</div>}
            </dd>
            {item.documents.length > 0 && (
              <>
                <dt>Основание</dt>
                <dd>{item.documents.join('; ')}</dd>
              </>
            )}
          </dl>
          <div className="actions wrap">
            <Link
              className="button-link"
              to={`/staffing?org=${item.organization_id}&year=${encodeURIComponent(item.year)}&category=${item.category}&basis=${item.basis}`}
            >
              Открыть анализ <Icon name="arrow" size={14} />
            </Link>
            <span className="muted">
              {item.created_by === 'system' ? 'связано автоматически' : 'создано из анализа'}
              {item.is_current ? '' : `, расчёт от ${fmtDate(item.calculated_at)}`}
            </span>
          </div>
        </div>
      ))}
    </section>
  )
}
