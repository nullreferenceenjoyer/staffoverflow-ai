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
export async function download(path: string, filename: string, query?: RequestOptions['query']) {
  const response = await request(path, { query })
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export type ChatEvent =
  | { type: 'delta'; text: string }
  | { type: 'data'; title: string; markdown: string }
  | { type: 'tool'; name: string; arguments: Record<string, unknown> }
  | { type: 'error'; message: string }
  | { type: 'done' }

/** Читает ответ помощника как поток SSE. */
export async function streamChat(
  question: string,
  history: { role: string; content: string }[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
) {
  const response = await fetch('/api/assistant/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify({ question, history }),
    signal,
  })
  if (!response.ok || !response.body) throw new ApiError(response.status, 'Помощник недоступен')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      if (frame.startsWith('data:')) onEvent(JSON.parse(frame.slice(5)))
    }
  }
}

// --- типы ответов API ---

export type Role = 'admin' | 'regional_analyst' | 'municipal_specialist' | 'director' | 'observer'
export type Category = 'teaching' | 'admin' | 'support' | 'medical'

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  municipality_id: number | null
  organization_id: number | null
  is_active: boolean
  telegram_chat_id: number | null
  max_chat_id: number | null
}

export interface Municipality {
  id: number
  name: string
}

export interface CategoryTotals {
  key: Category
  title: string
  actual: number
  norm: number
  surplus: number
  shortage: number
}

export interface OrgSummary {
  id: number
  name: string
  org_type: string
  municipality_id: number
  municipality: string
  students: number
  actual: number
  norm: number
  surplus: number
  shortage: number
  compliance: number
  fot_actual_year: number
  saving_potential_year: number
}

export interface Stage {
  category: Category
  actual: number
  norm: number
  centralized: number
}

export interface Dashboard {
  organizations: number
  students: number
  actual_total: number
  norm_total: number
  surplus: number
  shortage: number
  compliance: number
  fot_actual_year: number
  saving_potential_year: number
  categories: CategoryTotals[]
  municipalities: {
    id: number
    name: string
    organizations: number
    actual: number
    norm: number
    surplus: number
    shortage: number
    saving: number
  }[]
  centralization: { stages: Stage[]; released_total: number; saving_year: number }
  projects_by_status: Record<string, number>
  overdue_tasks: number | null
  top_organizations: OrgSummary[]
}

export interface ReportLine {
  function_code: string
  title: string
  category: Category
  actual_rate: number
  actual_pay: number
  vacant_rate: number
  norm_rate: number | null
  delta: number
  has_norm: boolean
  explanations: string[]
}

export interface Building {
  id: number
  name: string
  area_sqm: number
  floors: number
  year_built: number | null
  condition: string
}

export interface Enrollment {
  id: number
  academic_year: number
  level: string
  study_form: string
  classes_count: number
  students_count: number
  special_needs_count: number
}

export interface OrgDetails extends OrgSummary {
  address: string | null
  metrics: { key: string; title: string; value: number }[]
  lines: ReportLine[]
  allowances: { title: string; value: number; explanation: string; legal_ref: string | null }[]
  buildings: Building[]
  enrollments: Enrollment[]
}

export interface Position {
  id: number
  department: string | null
  title: string
  category: Category
  function_code: string
  rate: number
  monthly_pay: number
  weekly_hours: number | null
  employee_ref: string | null
}

export interface Deviation {
  organization_id: number
  organization: string
  municipality: string
  title: string
  category: Category
  actual: number
  norm: number
  delta: number
  fot_effect_year: number
  explanations: string[]
}

export interface CentralFunction {
  function_code: string
  title: string
  category: Category
  center: string
  organizations: number
  actual: number
  norm: number
  centralized: number
  released: number
  saving_year: number
  members: { organization_id: number; organization: string; actual: number; norm: number | null }[]
}

export interface Scenario {
  organizations: number
  functions: CentralFunction[]
  stages: Stage[]
  released_total: number
  saving_year: number
}

export interface Norm {
  id: number
  code: string
  title: string
  kind: 'staff' | 'allowance'
  function_code: string
  org_types: string[]
  driver: string
  unit_size: number
  per_unit: number
  base: number
  threshold: number
  min_value: number | null
  max_value: number | null
  rounding: number
  centralization_effect: number
  source_kind: 'federal' | 'regional' | 'assumption'
  legal_ref: string | null
  document_id: number | null
  is_active: boolean
}

export interface NormMeta {
  drivers: { key: string; title: string }[]
  functions: { code: string; title: string; category: Category }[]
  categories: { key: Category; title: string }[]
}

export interface ProjectItem {
  id: number
  organization_name: string
  function_code: string
  title: string
  category: Category
  current_rate: number
  proposed_rate: number
  fot_effect_year: number
  vacant_rate: number
  reason: string
}

export interface GeneratedDoc {
  id: number
  kind: string
  title: string
  narrative: string
  written_by_llm: boolean
  created_at: string
}

export interface Project {
  id: number
  title: string
  kind: string
  status: string
  municipality_id: number
  organization_id: number | null
  summary: string | null
  rate_delta: number
  fot_effect_year: number
  created_at: string
  decided_at: string | null
  items?: ProjectItem[]
  documents?: GeneratedDoc[]
}

export interface WorkflowStep {
  title: string
  role: Role
  duration_days: number
}

export interface WorkflowTemplate {
  id: number
  name: string
  description: string | null
  steps: WorkflowStep[]
}

export interface Task {
  id: number
  project_id: number | null
  run_id: string | null
  step_index: number
  title: string
  assignee_role: Role
  status: 'waiting' | 'todo' | 'in_progress' | 'done'
  due_date: string | null
  completed_at: string | null
}

export interface KnowledgeDoc {
  id: number
  title: string
  doc_type: string
  source_ref: string | null
  is_summary: boolean
  has_file: boolean
  chunks: number
  norms: { id: number; title: string }[]
}

export interface SearchHit {
  document_id: number
  title: string
  source_ref: string | null
  is_summary: boolean
  content: string
  score: number
  norms: { id: number; code: string; title: string }[]
}

export interface OrgRequest {
  id: number
  organization: string
  text: string
  topic_title: string
  routed_role: Role
  classified_by: 'llm' | 'rules'
  status: 'new' | 'in_progress' | 'closed'
  resolution: string | null
  created_at: string
}

export interface Milestone {
  id: number
  ordinal: number
  title: string
  start_date: string
  end_date: string
  responsible: string | null
  status: 'planned' | 'in_progress' | 'done'
}

export interface DigitalTool {
  function_code: string
  function: string
  name: string
  description: string | null
  coverage_pct: number | null
}

export interface ProgramCategory {
  category: 'admin' | 'support'
  baseline_rate: number
  current_rate: number
  done_rates: number
  plan_rates: number
  plan_dismissals: number
  plan_hours: number
  done_hours: number
  potential_rates: number
  potential_vacant: number
  potential_saving_year: number
}

export interface ProgramData {
  id: number
  municipality: string
  title: string
  description: string | null
  start_date: string
  end_date: string
  milestones: Milestone[]
  scoreboard: {
    baseline_fixed: boolean
    baseline_at: string | null
    baseline_fot_year: number
    current_fot_year: number
    target_pct: number
    target_saving_year: number
    done_saving_year: number
    done_pct: number
    plan_saving_year: number
    potential_saving_year: number
    potential_pct: number
    centralization_saving_year: number
    centralization_released: number
    hours_per_rate: number
    days_left: number
    organizations: number
    categories: ProgramCategory[]
  }
}

export interface Notification {
  id: number
  text: string
  created_at: string
  read_at: string | null
}
