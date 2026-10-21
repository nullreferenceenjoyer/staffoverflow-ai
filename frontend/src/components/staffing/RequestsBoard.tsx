import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { RequestsBoard as Board } from '../../api'
import { fmtDay, fmtHours, fmtInt, plural, REQUEST_KIND } from '../../lib'
import { StatusBar } from '../blocks'
import { AXIS, ChartTip, Legend, Meter, SERIES } from '../charts'
import { Icon } from '../icons'
import { Avatar, Badge, Card, Counter, Empty, Kpi } from '../ui'

const HANDLER = { brigade: 'Бригады управления', own: 'Свой хозотдел школ' }

/** За год по дням график превращается в шум — длинные периоды складываем по неделям. */
function flowOf(data: Board) {
  const step = data.days > 90 ? 7 : 1
  const out: { name: string; created: number; closed: number }[] = []
  data.flow.forEach((p, i) => {
    if (i % step === 0) out.push({ name: fmtDay(p.date), created: 0, closed: 0 })
    const last = out[out.length - 1]
    last.created += p.created
    last.closed += p.closed
  })
  return { points: out, weekly: step > 1 }
}

export function FlowChart({ data, height = 230 }: { data: Board; height?: number }) {
  const { points } = flowOf(data)
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={points}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="name" {...AXIS} minTickGap={28} />
          <YAxis {...AXIS} allowDecimals={false} width={28} />
          <Tooltip content={<ChartTip format={fmtInt} />} />
          <Area
            isAnimationActive={false}
            type="monotone"
            dataKey="created"
            name="Пришло"
            stroke={SERIES[0]}
            strokeWidth={2}
            fill={SERIES[0]}
            fillOpacity={0.12}
          />
          <Area
            isAnimationActive={false}
            type="monotone"
            dataKey="closed"
            name="Выполнено"
            stroke={SERIES[2]}
            strokeWidth={2}
            fill={SERIES[2]}
            fillOpacity={0.12}
          />
        </AreaChart>
      </ResponsiveContainer>
      <Legend
        items={[
          ['Пришло', SERIES[0]],
          ['Выполнено', SERIES[2]],
        ]}
      />
    </>
  )
}

export function RequestKpis({ data }: { data: Board }) {
  return (
    <div className="kpis">
      <Kpi
        icon="inbox"
        label={`Пришло за ${data.days === 365 ? 'год' : `${data.days} дн.`}`}
        value={<Counter value={data.created} format={fmtInt} />}
        note={`≈ ${fmtInt(Math.round(data.hours))} ч работы мастеров`}
      />
      <Kpi
        icon="wrench"
        label="В работе сейчас"
        value={<Counter value={data.active} format={fmtInt} />}
        note={
          data.unassigned ? `${data.unassigned} ещё без исполнителя` : 'у всех есть исполнитель'
        }
        tone={data.unassigned ? 'warn' : undefined}
      />
      <Kpi
        icon="alert"
        label="Просрочено"
        value={<Counter value={data.overdue} format={fmtInt} />}
        note={data.overdue ? 'срок вышел, работа не сдана' : 'всё в сроке'}
        tone={data.overdue ? 'critical' : 'good'}
      />
      <Kpi
        icon="check"
        label="Сделано в срок"
        value={data.in_time_pct === null ? '—' : `${fmtInt(data.in_time_pct)} %`}
        note={`из ${data.resolved} выполненных · в среднем ${fmtHours(data.avg_hours)}`}
        tone={data.in_time_pct !== null && data.in_time_pct < 80 ? 'warn' : undefined}
      />
    </div>
  )
}

/** Кто делает работу: бригады управления или свой хозотдел, — и сколько часов на каждых. */
function Handlers({ data }: { data: Board }) {
  const peak = Math.max(...data.handlers.map((h) => h.hours), 1)
  return (
    <>
      {data.handlers.map((h) => (
        <Meter
          key={h.key}
          label={
            <>
              {HANDLER[h.key]}
              <div className="muted">
                {h.requests} {plural(h.requests, 'заявка', 'заявки', 'заявок')} · в работе{' '}
                {h.active}
              </div>
            </>
          }
          value={h.hours}
          max={peak}
          suffix=" ч"
        />
      ))}
    </>
  )
}

export function RequestsBoard({ data }: { data: Board }) {
  const topicPeak = Math.max(...data.by_topic.map((t) => t.total), 1)
  const { weekly } = flowOf(data)
  if (!data.total) return <Empty>За этот период хозяйственных заявок нет.</Empty>
  return (
    <>
      <RequestKpis data={data} />
      <div className="grid-wide">
        <Card title={weekly ? 'Заявки по неделям' : 'Заявки по дням'}>
          <p className="card-sub">
            Если синяя линия долго выше зелёной — заявки копятся быстрее, чем их успевают делать.
          </p>
          <FlowChart data={data} />
        </Card>
        <Card title="Кто выполняет">
          <p className="card-sub">Часы работы по заявкам за период.</p>
          <Handlers data={data} />
          <h3 className="board-sub">Статусы</h3>
          <StatusBar items={data.by_status} />
          <h3 className="board-sub">Открытые по срочности</h3>
          <div className="chips">
            {data.by_kind.map((k) => (
              <Badge key={k.kind} tone={REQUEST_KIND[k.kind].tone}>
                {k.title}: {k.count}
              </Badge>
            ))}
          </div>
          <h3 className="board-sub">Сложность новых</h3>
          <div className="chips">
            {data.by_complexity.map((c) => (
              <Badge key={c.complexity} tone="gray">
                {c.title}: {c.count}
              </Badge>
            ))}
          </div>
        </Card>
      </div>
      <div className="grid-board">
        <Card title="Что чинят">
          <p className="card-sub">Темы заявок и среднее время выполнения.</p>
          {data.by_topic.map((t) => (
            <Meter
              key={t.topic}
              label={
                <>
                  {t.title}
                  <div className="muted">
                    {t.avg_hours === null ? 'ещё не выполнялись' : fmtHours(t.avg_hours)}
                    {t.overdue > 0 && ` · просрочено ${t.overdue}`}
                  </div>
                </>
              }
              value={t.total}
              max={topicPeak}
              suffix=""
              low={t.overdue > 0}
            />
          ))}
        </Card>
        <Card title="Откуда больше всего">
          {data.by_organization.length === 0 ? (
            <Empty>Нет заявок.</Empty>
          ) : (
            data.by_organization.map((o) => (
              <Meter
                key={o.id}
                label={
                  <>
                    {o.name}
                    <div className="muted">
                      в работе {o.active}
                      {o.overdue > 0 && ` · просрочено ${o.overdue}`}
                    </div>
                  </>
                }
                value={o.total}
                max={data.by_organization[0].total}
                suffix=""
                low={o.overdue > 0}
              />
            ))
          )}
        </Card>
        <Card title="Исполнители">
          {data.by_assignee.length === 0 ? (
            <Empty>Нет открытых заявок с исполнителем.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Кто</th>
                  <th className="num">В работе</th>
                  <th className="num">Просроч.</th>
                  <th className="num">Сделано</th>
                </tr>
              </thead>
              <tbody>
                {data.by_assignee.map((p) => (
                  <tr key={p.key}>
                    <td>
                      <span className="chips">
                        {p.id === null && p.key !== 'None' ? (
                          <Icon name="truck" size={16} />
                        ) : (
                          <Avatar name={p.name} small />
                        )}{' '}
                        {p.name}
                      </span>
                    </td>
                    <td className="num">{p.active}</td>
                    <td className="num">
                      {p.overdue ? <span className="delta-minus">{p.overdue}</span> : '—'}
                    </td>
                    <td className="num">{p.done}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  )
}
