import { ReactNode } from 'react'

import { Advice, Rule, StaffAction } from '../../api'
import { fmt, fmtRubShort, fteWord } from '../../lib'
import { Icon } from '../icons'
import { Badge } from '../ui'

/** Раскрывающаяся подсказка «Как это считается». */
export function HowItWorks({
  title = 'Как это считается',
  children,
  open,
}: {
  title?: string
  children: ReactNode
  open?: boolean
}) {
  return (
    <details className="how" open={open}>
      <summary>
        <Icon name="doc" size={15} /> {title}
      </summary>
      <div className="how-body">{children}</div>
    </details>
  )
}

const RULE_ICON: Record<string, string> = {
  cut: '✂',
  cut_vacant: '○',
  cut_by_load: '⏱',
  keep_by_load: '⚠',
  hire: '+',
  data: '?',
  tolerance: '≈',
}

/** Все правила «когда сокращать» — одна таблица, та же, по которой считает система. */
export function RulesHelp({ rules }: { rules: Rule[] }) {
  return (
    <>
      <p>
        Система смотрит на каждую группу должностей учреждения: сколько ставок{' '}
        <strong>положено по нормативу</strong>, сколько <strong>по штатке</strong> и сколько{' '}
        <strong>занято</strong>. Для хозотдела — ещё сколько работы пришло заявками. Дальше
        срабатывает одно из правил:
      </p>
      <ol className="rules-list">
        {rules.map((r) => (
          <li key={r.code}>
            <span className="rule-mark" aria-hidden="true">
              {RULE_ICON[r.code] ?? '•'}
            </span>
            <span>
              <strong>{r.title}.</strong> {r.text}
            </span>
          </li>
        ))}
      </ol>
      <p className="muted">
        Экономия в год = сокращаемые ставки × оклад должности × 12. Если оклад не указан — берётся
        средний по группе в округе, такая сумма помечена «≈». Сократить — значит принять решение:
        система только показывает расчёт.
      </p>
    </>
  )
}

/** Пояснение по шагам к одному решению. */
export function WhyList({ why }: { why: string[] }) {
  if (!why.length) return null
  return (
    <ul className="why">
      {why.map((w) => (
        <li key={w}>{w}</li>
      ))}
    </ul>
  )
}

const KIND: Record<StaffAction['kind'], { label: string; tone: string }> = {
  cut: { label: 'Сократить', tone: 'orange' },
  cut_by_load: { label: 'Сократить по загрузке', tone: 'orange' },
  reduce_load: { label: 'Уменьшить нагрузку', tone: 'amber' },
  cut_vacant: { label: 'Убрать вакансии', tone: 'blue' },
  hire: { label: 'Не хватает', tone: 'red' },
  data: { label: 'Внести данные', tone: 'gray' },
}

export function ActionBadge({ kind }: { kind: StaffAction['kind'] }) {
  return <Badge tone={KIND[kind].tone}>{KIND[kind].label}</Badge>
}

/** «1 ставка», «0,5 ставки» */
export const fteText = (value: number) => `${fmt(value)} ${fteWord(value)}`

/** Одно действие: что, какие должности, сколько сэкономит и почему. */
export function ActionCard({ action }: { action: StaffAction }) {
  const cut = action.kind.startsWith('cut') || action.kind === 'reduce_load'
  return (
    <li className={`action-card action-${action.kind}`}>
      <div className="action-head">
        <ActionBadge kind={action.kind} />
        <strong>{action.group}</strong>
        {action.cost ? (
          <span className="action-cost">
            {cut ? '−' : ''}
            {fmtRubShort(action.cost)}/год
          </span>
        ) : null}
      </div>
      {action.positions.length > 0 && (
        <ul className="action-positions">
          {action.positions.map((p) => (
            <li key={`${p.line_id}-${p.kind}`}>
              <span>
                {p.kind === 'vacant' ? 'вакантные ' : p.kind === 'load' ? 'совмещение ' : ''}
                <strong>{fteText(p.fte)}</strong> — «{p.position}»
              </span>
              {p.salary !== null && (
                <span className="muted">оклад {fmtRubShort(p.salary)}/мес</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {action.kind === 'hire' && action.fte !== null && (
        <p className="action-line">
          Не хватает <strong>{fteText(action.fte)}</strong> — здесь сокращать нельзя.
        </p>
      )}
      {action.kind === 'cut_vacant' && (
        <p className="muted small-text">Ставки не заняты — увольнять никого не нужно.</p>
      )}
      {action.kind === 'reduce_load' && (
        <p className="muted small-text">
          Люди остаются на своей ставке — снимается совмещение и дополнительная нагрузка.
        </p>
      )}
      <details className="action-why">
        <summary>Почему</summary>
        <WhyList why={action.why} />
      </details>
    </li>
  )
}

/** Короткий вывод по группе — для таблицы штатки. */
export function AdviceLine({ advice }: { advice: Advice }) {
  const total = advice.cut + advice.reduce_load + advice.cut_vacant
  if (total > 0) {
    const parts = [
      advice.cut_vacant ? `вакансии ${fmt(advice.cut_vacant)}` : null,
      advice.reduce_load ? `нагрузка ${fmt(advice.reduce_load)}` : null,
      advice.cut ? `люди ${fmt(advice.cut)}` : null,
    ].filter(Boolean)
    return (
      <span className="dev-surplus">
        высвободить {fteText(total)}
        {parts.length > 1 || !advice.cut_vacant ? ` (${parts.join(', ')})` : ' вакантных'}
      </span>
    )
  }
  if (advice.verdict === 'hire')
    return <span className="dev-deficit">не хватает {fteText(advice.hire)}</span>
  if (advice.verdict === 'data')
    return <span className="muted">{advice.reasons[0] ?? 'не хватает данных'}</span>
  return <span className="dev-calm">в норме</span>
}
