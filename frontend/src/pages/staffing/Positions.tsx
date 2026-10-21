import { useState } from 'react'

import { ProgramPositions, StaffingSummary } from '../../api'
import { Async, Card, Empty } from '../../components/ui'
import { fmt, fmtRubShort, useApi } from '../../lib'

/** По должностям: было → вакансии, нагрузка, люди → стало; рядом — расчёт управления. */
export function Positions() {
  const state = useApi<StaffingSummary>('/staffing/summary')
  const plan = useApi<ProgramPositions>('/program/positions')
  const [all, setAll] = useState(false)
  const planned = new Map(
    (plan.data?.categories ?? []).flatMap((c) => c.items).map((i) => [i.name, i.cut] as const),
  )
  return (
    <Async state={state}>
      {(data) => {
        const rows = data.positions.filter((p) => all || p.total)
        if (!data.positions.length) return <Empty>Штатки школ не заполнены.</Empty>
        const sum = (key: 'approved' | 'cut_vacant' | 'reduce_load' | 'cut' | 'after' | 'cost') =>
          rows.reduce((s, p) => s + p[key], 0)
        return (
          <>
            <div className="positions-total">
              <span>
                Было <strong>{fmt(sum('approved'))}</strong> ставок
              </span>
              <span className="dev-surplus">
                высвободить <strong>{fmt(data.headline.total)}</strong>
              </span>
              <span>
                стало <strong>{fmt(sum('after'))}</strong>
              </span>
              <span>
                экономия <strong>{fmtRubShort(data.headline.cost)}</strong> в год
              </span>
            </div>
            <div className="toolbar">
              <label className="check">
                <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
                Показать и должности, где высвобождать нечего
              </label>
            </div>
            <Card>
              <table className="stack staffing-table">
                <thead>
                  <tr>
                    <th>Должность</th>
                    <th className="num">Было</th>
                    <th className="num">Вакансии</th>
                    <th className="num">Нагрузка</th>
                    <th className="num">Люди</th>
                    <th className="num">Стало</th>
                    <th className="num">Экономия в год</th>
                    {planned.size > 0 && <th className="num">Расчёт УО</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => {
                    const uo = planned.get(p.position)
                    const ok = uo !== undefined && Math.abs(uo - p.total) < 0.011
                    return (
                      <tr key={p.position}>
                        <td data-label="Должность">
                          {p.position}
                          <div className="muted small-text">
                            {p.category === 'aup' ? 'АУП' : 'Вспомогательный'}
                          </div>
                        </td>
                        <td data-label="Было" className="num">
                          {fmt(p.approved)}
                        </td>
                        <td data-label="Вакансии" className="num">
                          {p.cut_vacant ? fmt(p.cut_vacant) : <span className="muted">—</span>}
                        </td>
                        <td data-label="Нагрузка" className="num">
                          {p.reduce_load ? fmt(p.reduce_load) : <span className="muted">—</span>}
                        </td>
                        <td data-label="Люди" className="num">
                          {p.cut ? fmt(p.cut) : <span className="muted">—</span>}
                        </td>
                        <td data-label="Стало" className="num">
                          {fmt(p.after)}
                        </td>
                        <td data-label="Экономия" className="num">
                          {p.cost ? fmtRubShort(p.cost) : <span className="muted">—</span>}
                        </td>
                        {planned.size > 0 && (
                          <td data-label="Расчёт УО" className="num">
                            {uo === undefined ? (
                              <span className="muted">—</span>
                            ) : (
                              <span className={ok ? 'dev-calm' : 'warn-text'}>
                                {ok ? '✓ ' : ''}
                                {fmt(uo)}
                              </span>
                            )}
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td>
                      <strong>Итого</strong>
                    </td>
                    <td className="num">{fmt(sum('approved'))}</td>
                    <td className="num">{fmt(sum('cut_vacant'))}</td>
                    <td className="num">{fmt(sum('reduce_load'))}</td>
                    <td className="num">{fmt(sum('cut'))}</td>
                    <td className="num">{fmt(sum('after'))}</td>
                    <td className="num">{fmtRubShort(sum('cost'))}</td>
                    {planned.size > 0 && <td />}
                  </tr>
                </tfoot>
              </table>
            </Card>
            <p className="muted small-text">
              Высвобождение по должности считается так же, как по школе: сначала вакансии, потом
              совмещение и доп. нагрузка, остальное — люди. «Расчёт УО» — сколько по этой должности
              сократили в расчёте управления от 08.09.2026; ✓ — система получила то же самое.
              Педагогические должности не анализируются.
            </p>
          </>
        )
      }}
    </Async>
  )
}
