import { useCallback, useEffect, useState } from 'react'

import { api, Role } from './api'

/**
 * Загружает данные при монтировании и при смене path/query.
 *
 * reload({ silent: true }) обновляет данные без индикатора загрузки и, если запрос
 * не удался, оставляет на экране прежние данные: так работают обновления в реальном времени.
 */
export function useApi<T>(path: string | null, query?: Record<string, string | number | null>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(path))
  const queryKey = JSON.stringify(query ?? {})

  const reload = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!path) return
      const silent = options?.silent === true
      if (!silent) setLoading(true)
      try {
        setData(await api<T>(path, { query: JSON.parse(queryKey) }))
        setError(null)
      } catch (e) {
        if (!silent) setError(e instanceof Error ? e.message : 'Не удалось загрузить данные')
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [path, queryKey],
  )

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, error, loading, reload, setData }
}

/** Вызывает fn не чаще, чем раз в delay мс: пачка событий — один запрос. */
export function debounce(fn: () => void, delay: number) {
  let timer: number | undefined
  const run = () => {
    window.clearTimeout(timer)
    timer = window.setTimeout(fn, delay)
  }
  run.cancel = () => window.clearTimeout(timer)
  return run
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

// Людей в системе три вида: сотрудник (с группой), директор и администратор. Подпись роли —
// это группа сотрудника: уборщик, хозяйственный отдел, сотрудник управления образования…
export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Администратор',
  regional_analyst: 'Сотрудник управления образования (все муниципалитеты)',
  municipal_specialist: 'Сотрудник управления образования',
  director: 'Директор',
  observer: 'Наблюдатель (только просмотр)',
  executor: 'Хозяйственный отдел учреждения',
  brigade: 'Бригада управления образования',
  employee: 'Сотрудник',
  cleaner: 'Уборщик',
}

/** Кратко, для подписи в списках: «Хозотдел», «Бригада УО». */
export const ROLE_SHORT: Record<Role, string> = {
  admin: 'Администратор',
  regional_analyst: 'Управление образования',
  municipal_specialist: 'Управление образования',
  director: 'Директор',
  observer: 'Наблюдатель',
  executor: 'Хозотдел',
  brigade: 'Бригада УО',
  employee: 'Сотрудник',
  cleaner: 'Уборщик',
}

/** «1,5 ставки», «2 человека» — склонение по числу. */
export function plural(value: number, one: string, few: string, many: string) {
  if (!Number.isInteger(value)) return few
  const n = Math.abs(value)
  if (n % 10 === 1 && n % 100 !== 11) return one
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return few
  return many
}

export const fteWord = (value: number) => plural(value, 'ставка', 'ставки', 'ставок')

export const REQUEST_STATUS: Record<string, { label: string; tone: string }> = {
  new: { label: 'Новая', tone: 'amber' },
  assigned: { label: 'Назначена', tone: 'blue' },
  in_progress: { label: 'В работе', tone: 'blue' },
  on_hold: { label: 'Ждёт ответа', tone: 'orange' },
  done: { label: 'Выполнена', tone: 'green' },
  closed: { label: 'Закрыта', tone: 'gray' },
  rejected: { label: 'Отклонена', tone: 'red' },
}

const fte2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Ставки: «5,25». Пусто — прочерк. */
export const fmtFte = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : fte2.format(value)

/** Отклонение со знаком: «+0,75», «−1,25», «0,00». */
export function fmtDeviation(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return sign + fte2.format(Math.abs(value))
}

const rub = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const short = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

/** Деньги: «1 234 567 ₽». */
export const fmtRub = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : `${value < 0 ? '−' : ''}${rub.format(Math.abs(value))} ₽`

/** Деньги со знаком: «+270 000 ₽», «−270 000 ₽». */
export const fmtRubDelta = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${value > 0 ? '+' : ''}${fmtRub(value)}`

/** Крупные суммы коротко: «2,7 млн ₽», «450 тыс. ₽». */
export function fmtRubShort(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  const size = Math.abs(value)
  const sign = value < 0 ? '−' : ''
  if (size >= 1e9) return `${sign}${short.format(size / 1e9)} млрд ₽`
  if (size >= 1e6) return `${sign}${short.format(size / 1e6)} млн ₽`
  if (size >= 1e4) return `${sign}${short.format(size / 1e3)} тыс. ₽`
  return fmtRub(value)
}

export const fmtDate = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleDateString('ru-RU') : '—'

/** Статусы нормативного анализа: человеческие слова и цвет бейджа. */
export const STAFFING_STATUS: Record<string, { label: string; tone: string; color: string }> = {
  deficit: { label: 'Дефицит', tone: 'red', color: 'var(--critical)' },
  surplus: { label: 'Сверх норматива', tone: 'orange', color: 'var(--serious)' },
  warning: { label: 'Требует проверки', tone: 'amber', color: 'var(--warn)' },
  no_data: { label: 'Нет данных', tone: 'gray', color: 'var(--series-muted)' },
  normal: { label: 'Норма', tone: 'green', color: 'var(--good)' },
}

export const ORG_TYPE_LABELS: Record<string, string> = {
  school: 'Школа',
  preschool: 'Детский сад',
  complex: 'Образовательный комплекс',
}

export const REQUEST_KIND: Record<string, { label: string; tone: string }> = {
  planned: { label: 'Плановая', tone: 'gray' },
  urgent: { label: 'Срочная', tone: 'amber' },
  emergency: { label: 'Аварийная', tone: 'red' },
}
