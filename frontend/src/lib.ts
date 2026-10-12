import { useCallback, useEffect, useState } from 'react'

import { api, Category, Role, User } from './api'

/** Загружает данные при монтировании и при смене path/query. */
export function useApi<T>(path: string | null, query?: Record<string, string | number | null>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(path))
  const queryKey = JSON.stringify(query ?? {})

  const reload = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      setData(await api<T>(path, { query: JSON.parse(queryKey) }))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить данные')
    } finally {
      setLoading(false)
    }
  }, [path, queryKey])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, error, loading, reload }
}

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export const fmt = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : number.format(value)

export const fmtInt = (value: number) => integer.format(value)

export const fmtDelta = (value: number) => (value > 0 ? '+' : '') + number.format(value)

export function fmtMoney(value: number) {
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${number.format(Math.round(value / 100_000) / 10)} млн ₽`
  if (abs >= 1_000) return `${integer.format(Math.round(value / 1000))} тыс. ₽`
  return `${integer.format(value)} ₽`
}

export const fmtDate = (value: string | null) =>
  value ? new Date(value).toLocaleDateString('ru-RU') : '—'

export const fmtDateTime = (value: string) =>
  new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Администратор',
  regional_analyst: 'Региональный аналитик',
  municipal_specialist: 'Специалист управления образования',
  director: 'Директор ОУ',
  observer: 'Наблюдатель',
}

export const CATEGORY_LABELS: Record<Category, string> = {
  teaching: 'Педагоги',
  admin: 'АУП',
  support: 'Вспомогательный персонал',
  medical: 'Медработники',
}

// Короткие подписи для осей графиков
export const CATEGORY_SHORT: Record<Category, string> = {
  teaching: 'Педагоги',
  admin: 'АУП',
  support: 'ВП',
  medical: 'Медработники',
}

export const ORG_TYPE_LABELS: Record<string, string> = {
  school: 'Школа',
  preschool: 'Детский сад',
  complex: 'Образовательный комплекс',
}

export const LEVEL_LABELS: Record<string, string> = {
  preschool: 'Дошкольное',
  primary: '1–4 классы',
  basic: '5–9 классы',
  secondary: '10–11 классы',
}

export const FORM_LABELS: Record<string, string> = {
  full_time: 'Очная',
  distance: 'Дистанционная',
  home: 'На дому',
}

export const PROJECT_STATUS: Record<string, { label: string; tone: string }> = {
  draft: { label: 'Черновик', tone: 'gray' },
  review: { label: 'На согласовании', tone: 'amber' },
  approved: { label: 'Утверждён', tone: 'green' },
  rejected: { label: 'Отклонён', tone: 'red' },
  implemented: { label: 'Внедрён', tone: 'blue' },
}

export const TASK_STATUS: Record<string, string> = {
  waiting: 'Ждёт предыдущего шага',
  todo: 'К выполнению',
  in_progress: 'В работе',
  done: 'Готово',
}

// Те же группы ролей, что и в backend/app/deps.py
export const canEdit = (user: User) => user.role !== 'observer'
export const canPlan = (user: User) =>
  ['admin', 'regional_analyst', 'municipal_specialist'].includes(user.role)
export const canApprove = (user: User) => ['admin', 'regional_analyst'].includes(user.role)
export const isRegional = (user: User) =>
  ['admin', 'regional_analyst', 'observer'].includes(user.role)
