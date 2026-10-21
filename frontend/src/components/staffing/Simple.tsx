import { ReactNode } from 'react'

import { SimpleStatus } from '../../api'
import { fmt, fteWord } from '../../lib'
import { Badge } from '../ui'

/** «11,25 ставки» */
export const st = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${fmt(value)} ${fteWord(value)}`

/** Итог простого расчёта крупно: «лишние 2 ставки», «не хватает 1», «норма». */
export function Verdict({
  status,
  diff,
  big,
}: {
  status: SimpleStatus
  diff: number | null
  big?: boolean
}) {
  const cls = big ? 'verdict verdict-big' : 'verdict'
  if (status === 'surplus') return <span className={`${cls} dev-surplus`}>лишние {st(diff)}</span>
  if (status === 'deficit')
    return <span className={`${cls} dev-deficit`}>не хватает {st(-(diff ?? 0))}</span>
  if (status === 'normal') return <span className={`${cls} dev-calm`}>в норме</span>
  if (status === 'brigade') return <Badge tone="blue">обслуживает бригада</Badge>
  return <span className={`${cls} muted`}>не внесено</span>
}

/** Расчёт в столбик: строки «что ÷ на что = сколько» и итог. */
export function Formula({ lines, result }: { lines: ReactNode[]; result?: ReactNode }) {
  return (
    <div className="formula">
      {lines.map((line, i) => (
        <div key={i} className="formula-line">
          {line}
        </div>
      ))}
      {result && <div className="formula-result">{result}</div>}
    </div>
  )
}
