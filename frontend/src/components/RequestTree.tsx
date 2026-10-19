import { useMemo, useState } from 'react'

import { OrgRequest, RequestStatus } from '../api'
import { fmtRelative, REQUEST_STATUS } from '../lib'
import { STATUS_COLOR } from './blocks'
import { Icon, IconName } from './icons'
import { Avatar, Badge } from './ui'

export type Grouping = 'place' | 'status' | 'assignee' | 'topic'

export const GROUPINGS: [Grouping, string][] = [
  ['place', 'По месту'],
  ['status', 'По этапу'],
  ['assignee', 'По исполнителю'],
  ['topic', 'По теме'],
]

export const STATUS_ORDER: RequestStatus[] = [
  'new',
  'assigned',
  'in_progress',
  'on_hold',
  'done',
  'closed',
  'rejected',
]
const ACTIVE: RequestStatus[] = ['new', 'assigned', 'in_progress', 'on_hold']
// Больше в узле сразу не показываем — дерево должно оставаться обозримым
const LEAF_PAGE = 30

interface Level {
  key: (r: OrgRequest) => string
  label: (r: OrgRequest) => string
  icon: IconName
}

interface TreeNode {
  key: string
  label: string
  icon: IconName
  requests: OrgRequest[]
  children: TreeNode[]
  open: number
  overdue: number
  mine: number
}

function levelsFor(grouping: Grouping, requests: OrgRequest[]): Level[] {
  if (grouping === 'status') {
    return [{ key: (r) => r.status, label: (r) => REQUEST_STATUS[r.status].label, icon: 'tasks' }]
  }
  if (grouping === 'assignee') {
    return [
      {
        key: (r) => (r.assignee ? `u${r.assignee.id}` : r.brigade ? `b${r.brigade.id}` : 'none'),
        label: (r) =>
          r.assignee?.name ?? (r.brigade ? `Бригада «${r.brigade.name}»` : 'Без исполнителя'),
        icon: 'user',
      },
    ]
  }
  if (grouping === 'topic') {
    return [{ key: (r) => r.topic, label: (r) => r.topic_title, icon: 'wrench' }]
  }
  // По месту: муниципалитет → учреждение → корпус. Уровень, где выбирать не из чего
  // (у директора одно учреждение), пропускаем, чтобы не щёлкать лишний раз.
  const distinct = (pick: (r: OrgRequest) => unknown) => new Set(requests.map(pick)).size
  const levels: Level[] = []
  if (distinct((r) => r.municipality) > 1) {
    levels.push({ key: (r) => r.municipality, label: (r) => r.municipality, icon: 'pin' })
  }
  if (distinct((r) => r.organization_id) > 1) {
    levels.push({
      key: (r) => String(r.organization_id),
      label: (r) => r.organization,
      icon: 'building',
    })
  }
  levels.push({
    key: (r) => String(r.building_id ?? 'none'),
    label: (r) => r.building ?? 'Корпус не указан',
    icon: 'grid',
  })
  return levels
}

function build(requests: OrgRequest[], levels: Level[], prefix: string, byStatus: boolean) {
  const [level, ...rest] = levels
  const groups = new Map<string, OrgRequest[]>()
  for (const r of requests) {
    const key = level.key(r)
    groups.set(key, [...(groups.get(key) ?? []), r])
  }
  const nodes: TreeNode[] = [...groups].map(([key, items]) => ({
    key: `${prefix}/${key}`,
    label: level.label(items[0]),
    icon: level.icon,
    requests: items,
    children: rest.length ? build(items, rest, `${prefix}/${key}`, false) : [],
    open: items.filter((r) => ACTIVE.includes(r.status)).length,
    overdue: items.filter((r) => r.overdue).length,
    mine: items.filter((r) => r.my_turn).length,
  }))
  if (byStatus) {
    return nodes.sort(
      (a, b) =>
        STATUS_ORDER.indexOf(a.requests[0].status) - STATUS_ORDER.indexOf(b.requests[0].status),
    )
  }
  // Сверху то, что требует внимания: просрочки, потом больше открытых
  return nodes.sort(
    (a, b) => b.overdue - a.overdue || b.open - a.open || a.label.localeCompare(b.label, 'ru'),
  )
}

function plural(n: number) {
  const tail = n % 100 >= 11 && n % 100 <= 14 ? 5 : n % 10
  return `${n} ${tail === 1 ? 'заявка' : tail >= 2 && tail <= 4 ? 'заявки' : 'заявок'}`
}

function urgency(r: OrgRequest) {
  return (r.my_turn ? 0 : 2) + (r.overdue ? 0 : 1)
}

function sortLeaves(requests: OrgRequest[]) {
  return [...requests].sort(
    (a, b) =>
      urgency(a) - urgency(b) ||
      (a.due_at ?? '9').localeCompare(b.due_at ?? '9') ||
      b.created_at.localeCompare(a.created_at),
  )
}

function MiniBar({ requests }: { requests: OrgRequest[] }) {
  const counts = STATUS_ORDER.map(
    (s) => [s, requests.filter((r) => r.status === s).length] as const,
  )
  return (
    <span className="statusbar mini" aria-hidden="true">
      {counts
        .filter(([, n]) => n > 0)
        .map(([status, n]) => (
          <i
            key={status}
            style={{ flex: n, background: STATUS_COLOR[status] }}
            title={`${REQUEST_STATUS[status].label}: ${n}`}
          />
        ))}
    </span>
  )
}

function Leaf({ request, onOpen }: { request: OrgRequest; onOpen: (id: number) => void }) {
  const active = ACTIVE.includes(request.status)
  const where = [request.building, request.location].filter(Boolean).join(', ')
  return (
    <button
      className={`tree-leaf ${request.my_turn ? 'mine' : ''} ${request.overdue ? 'overdue' : ''}`}
      onClick={() => onOpen(request.id)}
    >
      <span className="dot" style={{ color: STATUS_COLOR[request.status] }} />
      <span className="tree-leaf-main">
        <strong>{request.title}</strong>
        <span className="muted">
          № {request.id} · {request.topic_title}
          {where && ` · ${where}`}
        </span>
        {request.my_turn && <span className="turn">{request.my_turn}</span>}
      </span>
      <span className="tree-leaf-side">
        <Badge tone={REQUEST_STATUS[request.status].tone}>
          {REQUEST_STATUS[request.status].label}
        </Badge>
        {request.kind !== 'planned' && (
          <Badge tone={request.kind === 'emergency' ? 'red' : 'amber'}>
            {request.kind === 'emergency' ? 'Аварийная' : 'Срочная'}
          </Badge>
        )}
      </span>
      <span className="tree-leaf-side muted">
        {request.assignee ? (
          <>
            <Avatar name={request.assignee.name} small /> {request.assignee.name}
          </>
        ) : request.brigade ? (
          <>
            <Icon name="truck" size={14} /> {request.brigade.name}
          </>
        ) : (
          <span className="late">нет исполнителя</span>
        )}
      </span>
      <span className={`tree-leaf-due ${request.overdue ? 'late' : 'muted'}`}>
        {request.status === 'on_hold'
          ? 'срок на паузе'
          : active && request.due_at
            ? `${request.overdue ? 'просрочена ' : 'срок '}${fmtRelative(request.due_at)}`
            : ''}
      </span>
    </button>
  )
}

function Branch({
  node,
  depth,
  isOpen,
  toggle,
  onOpen,
}: {
  node: TreeNode
  depth: number
  isOpen: (node: TreeNode, depth: number) => boolean
  toggle: (node: TreeNode, depth: number) => void
  onOpen: (id: number) => void
}) {
  const [limit, setLimit] = useState(LEAF_PAGE)
  const open = isOpen(node, depth)
  const leaves = useMemo(
    () => (open && !node.children.length ? sortLeaves(node.requests) : []),
    [open, node],
  )

  return (
    <div className="tree-node">
      <button className="tree-row" aria-expanded={open} onClick={() => toggle(node, depth)}>
        <span className={`tree-chevron ${open ? 'open' : ''}`}>
          <Icon name="chevron" size={15} />
        </span>
        <Icon name={node.icon} size={16} />
        <span className="tree-label">{node.label}</span>
        {!node.key.startsWith('status/') && <MiniBar requests={node.requests} />}
        <span className="tree-nums">
          <span className="muted">{plural(node.requests.length)}</span>
          {node.overdue > 0 && <Badge tone="red">просрочено {node.overdue}</Badge>}
          {node.mine > 0 && <Badge tone="blue">ждут вас {node.mine}</Badge>}
        </span>
      </button>
      {open && (
        <div className="tree-children">
          {node.children.map((child) => (
            <Branch
              key={child.key}
              node={child}
              depth={depth + 1}
              isOpen={isOpen}
              toggle={toggle}
              onOpen={onOpen}
            />
          ))}
          {leaves.slice(0, limit).map((r) => (
            <Leaf key={r.id} request={r} onOpen={onOpen} />
          ))}
          {leaves.length > limit && (
            <button className="ghost small tree-more" onClick={() => setLimit(limit + LEAF_PAGE)}>
              Показать ещё {Math.min(LEAF_PAGE, leaves.length - limit)} из {leaves.length - limit}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/** Дерево заявок: группы раскрываются по щелчку, в каждой видно, сколько открыто и просрочено. */
export function RequestTree({
  requests,
  grouping,
  onOpen,
}: {
  requests: OrgRequest[]
  grouping: Grouping
  onOpen: (id: number) => void
}) {
  const nodes = useMemo(
    () => build(requests, levelsFor(grouping, requests), grouping, grouping === 'status'),
    [requests, grouping],
  )
  // Явно раскрытые и свёрнутые пользователем узлы; остальные — по правилу ниже
  const [manual, setManual] = useState<Record<string, boolean>>({})
  const [all, setAll] = useState<boolean | null>(null)

  const isOpen = (node: TreeNode, depth: number) => {
    if (node.key in manual) return manual[node.key]
    if (all !== null) return all
    // Сразу видно то, что ждёт пользователя, и верхний уровень, если он короткий
    return node.mine > 0 || (depth === 0 && nodes.length <= 4)
  }
  const toggle = (node: TreeNode, depth: number) =>
    setManual({ ...manual, [node.key]: !isOpen(node, depth) })
  const setEverything = (value: boolean) => {
    setManual({})
    setAll(value)
  }

  return (
    <div className="tree">
      <div className="tree-tools">
        <button className="ghost small" onClick={() => setEverything(true)}>
          Развернуть всё
        </button>
        <button className="ghost small" onClick={() => setEverything(false)}>
          Свернуть всё
        </button>
      </div>
      {nodes.map((node) => (
        <Branch
          key={node.key}
          node={node}
          depth={0}
          isOpen={isOpen}
          toggle={toggle}
          onOpen={onOpen}
        />
      ))}
    </div>
  )
}
