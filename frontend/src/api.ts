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
    kind: 'comment' | 'status' | 'assignee' | 'deadline' | 'effort' | 'staffing'
    text: string
    created_at: string
    author: string | null
  }[]
  assignable?: Person[]
  brigades?: { id: number; name: string; serves: boolean; members: number }[]
  children?: { id: number; title: string; status: RequestStatus; assignee: string | null }[]
  /** Связанные результаты нормативного анализа; пусто, если раздел пользователю не виден. */
  staffing?: StaffingContext[]
}

// --- нормативная численность ---

export type StaffCategory = 'aup' | 'support'
export type StaffBasis = 'occupied' | 'approved'
export type StaffingStatus = 'deficit' | 'surplus' | 'normal' | 'no_data' | 'warning'

/** Снимок норматива, применённого в расчёте. */
export interface AppliedNorm {
  id: number
  rule: string
  metric: string
  document_id: number | null
  document: string | null
  is_mandatory: boolean
  value?: number | null
  fte?: number
  explain?: string
  missing?: string
}

export interface StaffingResult {
  id: number
  group_id: number | null
  group: string | null
  category: StaffCategory
  basis: StaffBasis
  year: string
  period_date: string
  required: number | null
  approved: number | null
  occupied: number | null
  fact: number | null
  deviation: number | null
  deviation_pct: number | null
  status: StaffingStatus
  status_title: string
  severity: 'low' | 'medium' | 'high' | null
  reasons: string[]
  coefficients: AppliedNorm[]
  metrics: Record<string, number | string | null>
  calculated_at: string
  is_current: boolean
}

export interface StaffingProblem {
  group: string
  status: StaffingStatus
  deviation: number | null
  reasons: string[]
}

export interface StaffingAnalysisItem extends StaffingResult {
  organization_id: number
  organization: string
  org_type: OrgRecord['org_type']
  municipality_id: number
  municipality: string
  problems: StaffingProblem[]
}

export interface StaffingAnalysis {
  year: string
  category: StaffCategory
  basis: StaffBasis
  summary: Record<StaffingStatus, number>
  calculated_at: string | null
  items: StaffingAnalysisItem[]
}

export interface StaffingSlot {
  total: StaffingResult | null
  groups: StaffingResult[]
}

export interface StaffingInstitution {
  organization_id: number
  organization: string
  org_type: OrgRecord['org_type']
  municipality: string
  year: string
  analysis: Record<StaffCategory, Record<StaffBasis, StaffingSlot>>
  documents: string[]
  metrics: Record<string, number | string | null>
  calculated_at: string | null
  can_edit: boolean
  buildings: number
}

export interface StaffingGroup {
  id: number
  code: string
  name: string
  category: StaffCategory
  subcategory: string | null
  institution_types: string[]
  positions: string | null
  is_active: boolean
}

interface Choice {
  code: string
  title: string
}

export interface StaffingMeta {
  years: string[]
  current_year: string
  categories: Choice[]
  bases: Choice[]
  statuses: Choice[]
  metrics: Choice[]
  institution_types: Choice[]
  scope_levels: Choice[]
  doc_types: string[]
  doc_statuses: Choice[]
  groups: StaffingGroup[]
  municipalities: Municipality[]
  organization: { id: number; name: string; org_type: OrgRecord['org_type'] } | null
  permissions: {
    details: boolean
    edit_data: boolean
    create_requests: boolean
    edit_norms: boolean
    edit_regional_norms: boolean
    import: boolean
    import_norms: boolean
  }
}

export interface StaffingData {
  organization_id: number
  organization: string
  org_type: OrgRecord['org_type']
  year: string
  schedule: {
    id: number
    status: 'draft' | 'approved' | 'archived'
    approved_at: string | null
    comment: string | null
    updated_at: string
  } | null
  metrics: {
    students_count: number | null
    classes_count: number | null
    groups_count: number | null
    total_area_m2: number | null
    source: string | null
    confirmed_at: string | null
  }
  lines: (StaffingGroup & {
    approved: number | null
    occupied: number | null
    /** Средний оклад за ставку, ₽ в месяц */
    salary: number | null
  })[]
}

export interface StaffingDraft {
  result_id: number
  status: StaffingStatus
  topic: string
  topic_title: string
  routed_role: Role
  routed_role_title: string
  title: string
  text: string
}

export interface StaffingContext extends StaffingResult {
  link_id: number
  link_type: string
  created_by: 'system' | 'user'
  organization_id: number
  category_title: string
  basis_title: string
  documents: string[]
}

export interface NormDocument {
  id: number
  title: string
  doc_type: string
  number: string | null
  issued_at: string | null
  effective_from: string | null
  effective_to: string | null
  issuer: string | null
  scope_level: 'region' | 'municipality' | 'organization'
  status: 'active' | 'superseded' | 'archived'
  status_title: string
  source_ref: string | null
  label: string
  coefficients: number
}

export interface NormCoefficient {
  id: number
  group_id: number
  group: string
  category: StaffCategory
  document_id: number | null
  document: string | null
  institution_type: string
  institution_type_title: string
  scope_level: 'region' | 'municipality' | 'organization'
  scope_id: number | null
  scope_title: string | null
  metric: string
  metric_title: string
  unit_size: number | null
  fte_per_unit: number
  min_fte: number | null
  max_fte: number | null
  applies_from: number | null
  applies_to: number | null
  rounding_step: number | null
  rounding_mode: 'up' | 'down' | 'nearest'
  tolerance_abs: number | null
  tolerance_pct: number | null
  priority: number
  effective_from: string | null
  effective_to: string | null
  is_mandatory: boolean
  comment: string | null
  rule: string
  state: 'active' | 'future' | 'expired' | 'inactive'
  can_edit: boolean
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

/** Локальная модель, которая определяет тему заявки. */
export interface LlmStatus {
  configured: boolean
  /** null — ещё не проверяли */
  available: boolean | null
  checked_at: string | null
  /** С какого момента модель в нынешнем состоянии */
  since: string | null
  /** Только для администратора */
  model?: string
  error?: string | null
}

export interface Notification {
  id: number
  text: string
  request_id: number | null
  created_at: string
  read_at: string | null
}

export interface AssistantMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface AssistantChat {
  id: number
  title: string
  year: string
  /** Пусто — разговор про всю территорию пользователя */
  organization_id: number | null
  organization: string | null
  created_at: string
  updated_at: string
  messages?: AssistantMessage[]
}

// --- ФОТ, штатка и дашборд ---

export interface PayrollTotals {
  approved: number
  occupied: number | null
  vacant: number | null
  /** ₽ в год: оклад × ставки × 12 */
  payroll_approved: number | null
  payroll_occupied: number | null
  vacant_payroll: number | null
  /** Групп со ставками, но без оклада */
  missing_salary: number
}

export interface ScheduleChange {
  group_id: number
  group: string
  approved_before: number
  approved_after: number
  approved_delta: number
  salary_before: number | null
  salary_after: number | null
  payroll_delta: number | null
}

export interface ScheduleVersion {
  id: number
  created_at: string
  author: string | null
  source: string
  source_title: string
  status: string
  status_title: string
  comment: string | null
  /** Первая версия за год — сравнивать не с чем */
  first: boolean
  approved: number
  occupied: number | null
  payroll_approved: number | null
  payroll_occupied: number | null
  approved_delta: number | null
  payroll_delta: number | null
  changes: ScheduleChange[]
}

export interface ScheduleLine {
  group_id: number
  group: string
  category: StaffCategory
  positions: string | null
  approved: number | null
  occupied: number | null
  vacant: number | null
  salary: number | null
  salary_estimated: boolean
  payroll_approved: number | null
  payroll_occupied: number | null
  required: number | null
  deviation: number | null
  /** ₽ в год: отклонение × оклад × 12; минус — столько стоит закрыть дефицит */
  deviation_cost: number | null
  status: StaffingStatus | null
}

export interface InstitutionSchedule {
  organization_id: number
  organization: string
  year: string
  basis: StaffBasis
  schedule: {
    status: string
    status_title: string
    approved_at: string | null
    updated_at: string
    comment: string | null
  } | null
  lines: ScheduleLine[]
  totals: PayrollTotals
  by_category: Record<StaffCategory, PayrollTotals>
  history: ScheduleVersion[]
  can_edit: boolean
}

export interface ScheduleListItem extends PayrollTotals {
  organization_id: number
  organization: string
  org_type: OrgRecord['org_type']
  municipality: string
  status: string | null
  status_title: string
  updated_at: string | null
  staffed_pct: number | null
  last_change: ScheduleVersion | null
}

export interface ScheduleList {
  year: string
  items: ScheduleListItem[]
  totals: PayrollTotals
}

export interface DashboardGroup {
  group_id: number
  group: string
  category: StaffCategory
  required: number
  fact: number
  deficit: number
  surplus: number
  deficit_cost: number
  surplus_cost: number
  payroll: number
}

export interface StaffingDashboard {
  year: string
  basis: StaffBasis
  organizations: number
  kpi: PayrollTotals & {
    problems: number
    no_data: number
    normal: number
    deficit_fte: number
    surplus_fte: number
    deficit_cost: number
    surplus_cost: number
    /** Часть цены посчитана по среднему окладу территории */
    cost_estimated: boolean
  }
  status: Record<StaffCategory, Record<StaffingStatus, number>>
  by_group: DashboardGroup[]
  by_municipality: {
    municipality_id: number
    municipality: string
    organizations: number
    problems: number
    no_data: number
    deficit: number
    surplus: number
    deficit_cost: number
    payroll: number
  }[]
  top: {
    organization_id: number
    organization: string
    municipality: string
    deficit: number
    surplus: number
    deficit_cost: number
    surplus_cost: number
  }[]
  changes: (ScheduleVersion & { organization_id: number; organization: string })[]
}
