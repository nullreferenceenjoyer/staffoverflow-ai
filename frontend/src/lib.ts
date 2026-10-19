import { useCallback, useEffect, useState } from 'react'

import { api, Role } from './api'

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

export const fmtDateTime = (value: string) =>
  new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })

export const fmtDay = (value: string) =>
  new Date(value).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })

/** «через 3 ч», «2 дн. назад» — для сроков заявок. */
export function fmtRelative(value: string, now = Date.now()) {
  const diff = new Date(value).getTime() - now
  const hours = Math.abs(diff) / 3_600_000
  const amount =
    hours < 1
      ? 'меньше часа'
      : hours < 48
        ? `${Math.round(hours)} ч`
        : `${Math.round(hours / 24)} дн.`
  return diff >= 0 ? `через ${amount}` : `${amount} назад`
}

export function fmtHours(hours: number | null) {
  if (hours === null) return '—'
  return hours < 48
    ? `${number.format(Math.round(hours))} ч`
    : `${number.format(Math.round(hours / 2.4) / 10)} дн.`
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Администратор',
  regional_analyst: 'Региональный аналитик',
  municipal_specialist: 'Специалист управления образования',
  director: 'Директор ОУ',
  observer: 'Наблюдатель',
  executor: 'Хозяйственная служба на точке',
  brigade: 'Выездная бригада',
  employee: 'Сотрудник ОУ',
}

export const REQUEST_STATUS: Record<string, { label: string; tone: string }> = {
  new: { label: 'Новая', tone: 'amber' },
  assigned: { label: 'Назначена', tone: 'blue' },
  in_progress: { label: 'В работе', tone: 'blue' },
  on_hold: { label: 'Ждёт ответа', tone: 'orange' },
  done: { label: 'Выполнена', tone: 'green' },
  closed: { label: 'Закрыта', tone: 'gray' },
  rejected: { label: 'Отклонена', tone: 'red' },
}

export const REQUEST_KIND: Record<string, { label: string; tone: string }> = {
  planned: { label: 'Плановая', tone: 'gray' },
  urgent: { label: 'Срочная', tone: 'amber' },
  emergency: { label: 'Аварийная', tone: 'red' },
}
