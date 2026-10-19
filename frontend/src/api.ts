const TOKEN_KEY = 'hr-edu-token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token: string | null) =>
  token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  form?: FormData | URLSearchParams
  query?: Record<string, string | number | null | undefined>
}

function buildUrl(path: string, query?: RequestOptions['query']) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value))
  }
  const suffix = params.toString()
  return `/api${path}${suffix ? `?${suffix}` : ''}`
}

async function request(path: string, options: RequestOptions = {}) {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? (options.body !== undefined || options.form ? 'POST' : 'GET'),
    headers,
    body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
  })

  if (response.status === 401 && token) {
    // Токен истёк — возвращаем на форму входа
    setToken(null)
    window.location.reload()
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join('; ')
          : `Ошибка ${response.status}`
    throw new ApiError(response.status, message)
  }
  return response
}

export async function api<T>(path: string, options?: RequestOptions): Promise<T> {
  const response = await request(path, options)
  return response.status === 204 ? (undefined as T) : response.json()
}

/** Скачивание файла с авторизацией: обычная ссылка не передаст токен. */
export async function download(path: string, filename: string) {
  const response = await request(path)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

// --- типы ответов API ---

export type Role =
  | 'admin'
  | 'regional_analyst'
  | 'municipal_specialist'
  | 'director'
  | 'observer'
  | 'executor'
  | 'brigade'
  | 'employee'
export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  municipality_id: number | null
  organization_id: number | null
  brigade_id: number | null
  is_active: boolean
}

export interface Municipality {
  id: number
  name: string
}

export interface Organization {
  id: number
  name: string
  municipality_id: number
}

export interface Building {
  id: number | null
  name: string
  address: string | null
}

/** Учреждение в учёте администратора. */
export interface OrgRecord {
  id: number
  name: string
  org_type: 'school' | 'preschool' | 'complex'
  address: string | null
  external_id: string | null
  municipality_id: number
  municipality: string
  latitude: number | null
  longitude: number | null
  buildings: Building[]
  users: number
  requests: number
  brigades: { id: number; name: string }[]
}

export interface Brigade {
  id: number
  name: string
  municipality_id: number | null
  municipality: string | null
  base_address: string | null
  latitude: number | null
  longitude: number | null
  topics: string[]
  is_active: boolean
  members: { id: number; name: string; email: string; is_active: boolean }[]
  organizations: { id: number; name: string; distance_km: number | null }[]
  active_requests: number
}

export interface BrigadeSuggestions {
  has_base: boolean
  items: {
    id: number
    name: string
    municipality: string
    distance_km: number | null
    assigned: boolean
    nearest: { id: number; name: string } | null
    other_brigades: string[]
  }[]
}

export interface ImportResult {
  created: number
  updated: number
  skipped: number
  errors: { row: number; message: string }[]
  created_municipalities: string[]
  passwords: { email: string; full_name: string; password: string }[]
}

export type Complexity = 'simple' | 'complex' | 'major'

export type RequestStatus =
  'new' | 'assigned' | 'in_progress' | 'on_hold' | 'done' | 'closed' | 'rejected'
export type RequestKind = 'planned' | 'urgent' | 'emergency'

export interface Person {
  id: number
  name: string
  role: Role
}

export interface OrgRequest {
  id: number
  title: string
  text: string
  kind: RequestKind
  topic: string
  topic_title: string
  status: RequestStatus
  organization_id: number
  organization: string
  municipality: string
  building_id: number | null
  building: string | null
  location: string | null
  author: Person | null
  assignee: Person | null
  /** Бригада, которой направлена заявка; взять её может любой участник. */
  brigade: { id: number; name: string } | null
  effort_hours: number | null
  complexity: Complexity
  complexity_title: string
  effort_by: 'llm' | 'rules' | 'manual' | null
  parent: { id: number; title: string } | null
  stages: number
  routed_role: Role
  classified_by: 'llm' | 'rules' | 'manual'
  created_at: string
  due_at: string | null
  started_at: string | null
  resolved_at: string | null
  closed_at: string | null
  overdue: boolean
  resolution: string | null
  comments: number
  can_manage: boolean
  is_author: boolean
  actions: RequestStatus[]
  /** Что сейчас должен сделать текущий пользователь; null — ход не за ним. */
  my_turn: string | null
  events?: {
    id: number
    kind: 'comment' | 'status' | 'assignee' | 'deadline' | 'effort'
    text: string
    created_at: string
    author: string | null
  }[]
  assignable?: Person[]
  brigades?: { id: number; name: string; serves: boolean; members: number }[]
  children?: { id: number; title: string; status: RequestStatus; assignee: string | null }[]
}

export interface RequestMeta {
  topics: { code: string; title: string; days: number; role: Role; field: boolean }[]
  kinds: { code: RequestKind; title: string; hours: number | null }[]
  statuses: { code: RequestStatus; title: string }[]
  organizations: { id: number; name: string; buildings: { id: number; name: string }[] }[]
}

export interface RequestStats {
  days: number
  total: number
  active: number
  unassigned: number
  complex: number
  overdue: number
  waiting_confirmation: number
  my_turn: number
  resolved: number
  in_time_pct: number | null
  avg_hours: number | null
  by_status: { status: RequestStatus; title: string; count: number }[]
  by_kind: { kind: RequestKind; title: string; count: number }[]
  by_topic: {
    topic: string
    title: string
    total: number
    active: number
    overdue: number
    avg_hours: number | null
  }[]
  by_assignee: {
    id: number | null
    key: string
    name: string
    active: number
    overdue: number
    done: number
  }[]
  by_organization: { id: number; name: string; total: number; active: number; overdue: number }[]
  flow: { date: string; created: number; closed: number }[]
}

export interface Notification {
  id: number
  text: string
  request_id: number | null
  created_at: string
  read_at: string | null
}
