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

/** Ответ, который сервер отдаёт кусками (модель печатает по мере генерации). */
export async function stream(
  path: string,
  body: unknown,
  onText: (text: string) => void,
  signal?: AbortSignal,
) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(response.status, payload?.detail ?? `Ошибка ${response.status}`)
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    if (value) onText(value)
  }
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
  | 'cleaner'
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
  /** Менять исполнителя и бригаду: управление образования и администратор */
  can_assign: boolean
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
  /** Система работает в одном округе — его название; иначе null */
  okrug: string | null
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
    edit_workload: boolean
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
    rooms_count: number | null
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
  /** Сколько уборщиков или сотрудников хозотдела заведено в системе; null — не считается */
  people: number | null
  /** Должности группы */
  positions: Position[]
  /** Что делать с группой: сократить, убрать вакансии, добавить, внести данные */
  advice: Advice | null
}

/** Должность в штатке — строка штатки. */
export interface Position {
  line_id: number
  position: string
  approved: number
  occupied: number | null
  vacant: number | null
  /** Из занятых — совмещение и дополнительная нагрузка */
  combined: number | null
  salary: number | null
  payroll: number | null
}

export type Verdict = 'cut' | 'reduce_load' | 'cut_vacant' | 'hire' | 'data' | 'ok'
export type RuleCode =
  'cut' | 'reduce_load' | 'cut_vacant' | 'cut_by_load' | 'keep_by_load' | 'hire' | 'data'

/** Что сократить в конкретной должности. */
export interface PositionCut {
  line_id: number
  position: string
  fte: number
  salary: number | null
  cost: number | null
  /** people — люди, load — совмещение (уменьшить нагрузку), vacant — вакансии */
  kind: 'people' | 'load' | 'vacant'
}

export interface Advice {
  group_id: number
  group: string
  code: string
  bucket: 'cleaning' | 'maintenance' | 'other'
  category: StaffCategory
  required: number | null
  approved: number
  occupied: number | null
  vacant: number | null
  people: number | null
  status: StaffingStatus
  verdict: Verdict
  rules: RuleCode[]
  cut: number
  reduce_load: number
  cut_vacant: number
  hire: number
  combined: number
  cost: number
  cost_load: number
  cost_vacant: number
  salary: number | null
  positions_cut: PositionCut[]
  /** Пояснение по шагам: норматив, факт, загрузка, вывод */
  why: string[]
  reasons: string[]
  load: {
    people: number
    needed: number
    load_pct: number | null
    requests: number
    hours: number
    capacity: number
    days: number
    complete: boolean
  } | null
  lines?: Position[]
}

export interface Rule {
  code: string
  title: string
  text: string
}

export interface AdviceTotals {
  cut: number
  reduce_load: number
  cut_vacant: number
  total: number
  cost: number
  cost_load: number
  cost_vacant: number
  total_cost: number
  hire: number
  payroll: number
  saving_pct: number | null
  approved: number
  occupied: number | null
  data_missing: number
}

export interface StaffAction {
  kind: 'cut' | 'cut_by_load' | 'reduce_load' | 'cut_vacant' | 'hire' | 'data'
  group: string
  bucket: Advice['bucket']
  fte: number | null
  cost: number | null
  positions: PositionCut[]
  why: string[]
  rules: RuleCode[]
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
  advice_totals: AdviceTotals
  rules: Rule[]
  /** Группы учреждения и их типовые должности — для «Добавить должность» */
  groups: { id: number; name: string; category: StaffCategory; suggestions: string[] }[]
}

export interface ScheduleListItem extends PayrollTotals {
  cut: number
  cut_vacant: number
  reduce_load: number
  cut_cost: number
  hire: number
  positions: number
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

// --- загрузка хозслужбы и итог «сколько лишних» ---

export type WorkloadStatus = 'surplus' | 'overload' | 'normal' | 'no_people'

export interface WorkloadSettings {
  hours_per_day: number
  target_load_pct: number
  travel_speed_kmh: number
  default_hours: number
  min_people: number
  /** Доля времени хозотдела школы на заявки, остальное — плановые работы */
  requests_share_pct: number
}

export interface WorkloadUnit {
  key: string
  /** brigade — бригада управления, onsite — хозотдел учреждения */
  kind: 'brigade' | 'onsite'
  id: number
  name: string
  municipality: string | null
  people: number
  /** От наименее загруженного к самому загруженному */
  members: { id: number; name: string; hours: number; requests: number }[]
  organizations: {
    id: number
    name: string
    requests: number
    hours: number
    trips: number
    distance_km: number | null
    per_month: number | null
  }[]
  requests: number
  work_hours: number
  travel_hours: number
  total_hours: number
  capacity_hours: number
  load_pct: number | null
  needed: number
  surplus: number
  status: WorkloadStatus
  candidates: string[]
  distance_unknown: boolean
  cost: number | null
  cost_estimated: boolean
}

export interface WorkloadTotals {
  units: number
  people: number
  needed: number
  surplus: number
  surplus_units: number
  overloaded: number
  cost: number | null
  requests: number
  hours: number
  brigade_surplus: number
  brigade_cost: number | null
  onsite_surplus: number
  onsite_cost: number | null
}

export interface WorkloadData {
  days: number
  periods: number[]
  settings: WorkloadSettings
  titles: Record<keyof WorkloadSettings, string>
  salary: number | null
  units: WorkloadUnit[]
  totals: WorkloadTotals
  since: string
  calculated_at: string
  can_edit: boolean
}

export type CutKind = 'cut_vacant' | 'reduce_load' | 'cut'

export interface SummaryBucket {
  key: 'cleaning' | 'maintenance' | 'other'
  title: string
  required: number
  approved: number
  occupied: number
  people: number
  has_people: boolean
  hire: number
  cut_vacant: number
  reduce_load: number
  cut: number
  cost_vacant: number
  cost_load: number
  cost: number
  total: number
  total_cost: number
  orgs_cut: number
}

export interface SummarySchool {
  organization_id: number
  organization: string
  cut_vacant: number
  reduce_load: number
  cut: number
  total: number
  cost: number
  payroll: number
  saving_pct: number | null
  hire: number
  main: { kind: StaffAction['kind']; group: string; fte: number | null }[]
}

export interface SummaryPosition {
  position: string
  bucket: SummaryBucket['key']
  category: StaffCategory
  approved: number
  after: number
  cut_vacant: number
  reduce_load: number
  cut: number
  total: number
  cost: number
}

export interface StaffingSummary {
  year: string
  days: number
  periods: number[]
  organizations: number
  organization: { id: number; name: string } | null
  headline: {
    cut_vacant: number
    reduce_load: number
    cut: number
    total: number
    cost: number
    brigade_cut: number
    brigade_cost: number
    hours: number
    hours_per_rate: number
    payroll: number
    base: number
    saving_pct: number | null
    taxes_pct: number
    hire: number
    schools_with_cut: number
    /** Штатных единиц к сокращению */
    staff_units: number
  }
  /** Расчёт управления для сверки; null — не загружен */
  plan: Partial<ProgramHead> | null
  buckets: SummaryBucket[]
  positions: SummaryPosition[]
  schools: SummarySchool[]
  /** Только у одного учреждения (директор) */
  actions: StaffAction[]
  groups: Advice[]
  metrics: Record<string, number | string | null>
  totals: AdviceTotals | null
  brigades: WorkloadUnit[]
  onsite: WorkloadUnit[]
  workload_settings: WorkloadSettings
  rules: Rule[]
}
export interface CleaningItem {
  organization_id: number
  organization: string
  municipality: string
  rooms: number | null
  area: number | null
  group: Advice | null
  cleaners: { id: number; name: string; requests: number; hours: number }[]
  rooms_per_fte: number | null
  area_per_fte: number | null
  rooms_per_required: number | null
  area_per_required: number | null
}

export interface CleaningData {
  year: string
  days: number
  items: CleaningItem[]
  totals: {
    required: number
    approved: number
    occupied: number
    cut: number
    cut_vacant: number
    cost: number
    hire: number
    people: number
    rooms: number
    area: number
    schools: number
    schools_cut: number
    schools_hire: number
    schools_data: number
    rooms_per_fte: number | null
    area_per_fte: number | null
  }
  rules: Rule[]
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

// --- программа оптимизации (факт по документам) ---

export interface ProgramHead {
  title: string
  passport: string
  basis: string
  start_date: string
  end_date: string
  state_date: string
  total: number
  vacancies: number
  load_reduction: number
  resignations: number
  layoffs: number
  dismissed_fte: number
  staff_units: number
  aup: { total: number; vacant_and_load: number; dismissed: number }
  vp: { total: number; vacant_and_load: number; dismissed: number }
  hours_per_rate: number
  hours: number
  dismissed_hours: number
  staff_before: number
  staff_after: number
  payroll_base_year: number
  economy_month: number
  economy_year: number
  economy_pct: number
  target_pct: number
  taxes_pct: number
  missing: string[]
}

export interface DismissalItem {
  id: number
  organization_id: number
  organization: string
  full_name: string
  position: string
  fte: number
  basis: 'own' | 'layoff'
  basis_title: string
  article: string | null
  order_number: string | null
  order_date: string | null
  dismissed_on: string | null
  notified_on: string | null
  note: string | null
  source: string | null
  /** Учтено в штатке: на сколько уменьшили «занято»; null — не учтено */
  applied_fte: number | null
  applied_position: string | null
}

export interface ProgramSchoolRow {
  organization_id: number
  organization: string
  total: number
  vacancies: number
  load_reduction: number
  resignations: number
  layoffs: number
  dismissed_fte: number
  hours: number
  staff_units: number
  orders: string | null
  dismissals: DismissalItem[]
  people: number
  matches: boolean
}

export interface ProgramOverview {
  program: ProgramHead | null
  schools: ProgramSchoolRow[]
  all_schools: number
  own_school: boolean
  dismissed_total: { people: number; fte: number; own: number; layoff: number }
  positions_cut: { name: string; category: string; cut: number; before: number; after: number }[]
}

export interface ProgramPositions {
  program: ProgramHead | null
  categories: {
    category: string
    before: number
    cut: number
    after: number
    economy_month: number
    items: {
      id: number
      name: string
      before: number
      cut: number
      after: number
      local_cut: number | null
      local_economy_month: number | null
      regional_cut: number | null
      regional_economy_month: number | null
      economy_month: number
      cut_pct: number | null
    }[]
  }[]
}

export type SimpleStatus = 'surplus' | 'deficit' | 'normal' | 'no_data' | 'brigade'

export interface CleaningRow {
  organization_id: number
  organization: string
  classes: number | null
  area: number | null
  have: number | null
  have_from: 'input' | 'schedule' | null
  by_classes: number | null
  by_area: number | null
  need: number | null
  diff: number | null
  status: SimpleStatus
  missing: string[]
  people: string[]
}

export interface CleaningSimple {
  year: string
  norm: { classes_per_rate: number; area_per_rate: number }
  items: CleaningRow[]
  totals: {
    schools: number
    filled: number
    have: number
    need: number
    surplus: number
    deficit: number
  }
  tolerance: number
  can_edit: boolean
  can_edit_norm: boolean
}

export interface MaintenanceRow {
  organization_id: number
  organization: string
  have: number | null
  people: string[]
  requests: number
  hours: number
  need: number | null
  diff: number | null
  status: SimpleStatus
  load_pct: number | null
  brigades: string[]
  brigade_requests: number
}

export interface MaintenanceSimple {
  days: number
  periods: number[]
  settings: WorkloadSettings
  rate_hours: number
  full_hours: number
  schools: MaintenanceRow[]
  brigades: Pick<
    WorkloadUnit,
    | 'id'
    | 'name'
    | 'people'
    | 'members'
    | 'organizations'
    | 'requests'
    | 'work_hours'
    | 'travel_hours'
    | 'total_hours'
    | 'load_pct'
    | 'needed'
    | 'surplus'
    | 'status'
    | 'candidates'
    | 'distance_unknown'
  >[]
  tolerance: number
  can_edit: boolean
  can_edit_brigades: boolean
}

/** Хозяйственные заявки школ: общая сводка заявок + часы и кто их выполняет. */
export interface RequestsBoard extends Omit<RequestStats, 'my_turn'> {
  /** Создано за период, без отклонённых */
  created: number
  /** Часов работы по этим заявкам */
  hours: number
  handlers: { key: 'brigade' | 'own'; requests: number; active: number; hours: number }[]
  by_complexity: { complexity: string; title: string; count: number }[]
  periods: number[]
}

export interface DismissalList {
  items: DismissalItem[]
  can_edit: boolean
  bases: Record<string, string>
}

/** Заявки в карточке бригады или хозотдела школы. */
export interface RequestSummary {
  count: number
  hours: number
  active: number
  overdue: number
  in_time_pct: number | null
  by_topic: { topic: string; title: string; count: number; hours: number }[]
  recent: {
    id: number
    title: string
    organization: string
    status: RequestStatus
    status_title: string
    kind: RequestKind
    hours: number
    created_at: string
    due_at: string | null
    assignee: string | null
    overdue: boolean
  }[]
}

/** Карточка бригады управления или своего хозотдела школы. */
export interface MaintenanceDetail {
  kind: 'brigade' | 'school'
  days: number
  settings: WorkloadSettings
  name: string
  requests: RequestSummary
  // бригада
  base_address?: string | null
  unit?: WorkloadUnit
  workdays?: number
  // школа
  row?: MaintenanceRow
  rate_hours?: number
  full_hours?: number
  people?: { name: string; requests: number; hours: number }[]
  brigade_requests?: RequestSummary
}
