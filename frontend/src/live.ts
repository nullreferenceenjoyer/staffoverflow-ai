import { useEffect, useRef, useState } from 'react'

import { getToken, LlmStatus } from './api'
import { useApi } from './lib'

/**
 * Обновления в реальном времени: один поток Server-Sent Events на вкладку.
 *
 * Сервер сообщает только номера изменившихся заявок, сами заявки интерфейс
 * перечитывает обычными запросами. Поток читается через fetch, а не EventSource:
 * так токен уходит в заголовке, а не в адресе.
 */
export type LiveEvent =
  | { type: 'requests'; ids?: number[]; all?: boolean }
  | { type: 'notifications' }
  | { type: 'llm' }
  | { type: 'hello'; live: boolean }

type Listener = (event: LiveEvent) => void

const listeners = new Set<Listener>()
const statusListeners = new Set<(connected: boolean) => void>()
let connected = false
let controller: AbortController | null = null

// Сервер шлёт пустую строку каждые 20 с; если молчит дольше — соединение мёртвое
const SILENCE_MS = 45_000

function setConnected(value: boolean) {
  if (connected === value) return
  connected = value
  statusListeners.forEach((listener) => listener(value))
}

function emit(event: LiveEvent) {
  listeners.forEach((listener) => {
    try {
      listener(event)
    } catch (e) {
      console.error(e)
    }
  })
}

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer)
      resolve()
    })
  })
}

function parse(chunk: string) {
  let type = 'message'
  let data = ''
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return
  try {
    emit({ ...JSON.parse(data), type } as LiveEvent)
  } catch {
    // Непонятное событие пропускаем: следующее плановое обновление всё поправит
  }
}

async function listen(signal: AbortSignal) {
  const attempt = new AbortController()
  const abort = () => attempt.abort()
  signal.addEventListener('abort', abort)
  let silence = window.setTimeout(abort, SILENCE_MS)
  try {
    const token = getToken()
    const response = await fetch('/api/events', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: 'no-store',
      signal: attempt.signal,
    })
    if (response.status === 401) return 'unauthorized'
    if (!response.ok || !response.body) throw new Error(`Ошибка ${response.status}`)
    setConnected(true)
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      window.clearTimeout(silence)
      silence = window.setTimeout(abort, SILENCE_MS)
      buffer += value.replace(/\r\n/g, '\n')
      let end
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        parse(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
      }
    }
  } finally {
    window.clearTimeout(silence)
    signal.removeEventListener('abort', abort)
  }
  return 'closed'
}

/** Подключается к потоку и переподключается сам, пока не вызван stopLive. */
export function startLive() {
  if (controller) return
  const current = new AbortController()
  controller = current
  void (async () => {
    let delay = 1000
    while (!current.signal.aborted) {
      try {
        const result = await listen(current.signal)
        if (result === 'unauthorized') break // токен истёк: на вход вернёт первый же запрос API
        delay = 1000
      } catch {
        // сеть пропала или сервер перезапускается — попробуем ещё раз
      }
      const was = connected
      setConnected(false)
      if (current.signal.aborted) break
      await wait(delay, current.signal)
      delay = Math.min(delay * 2, 30_000)
      if (was) {
        // Пока связи не было, события могли потеряться: после переподключения всё перечитаем
        const resync = () => {
          statusListeners.delete(resync)
          emit({ type: 'requests', all: true })
          emit({ type: 'notifications' })
          emit({ type: 'llm' })
        }
        statusListeners.add(resync)
      }
    }
  })()
}

export function stopLive() {
  controller?.abort()
  controller = null
  setConnected(false)
}

/** Подписка на события потока вне React. Возвращает функцию отписки. */
export function onLive(listener: Listener) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Подписка на смену связи: true — поток подключён. */
export function onLiveStatus(listener: (connected: boolean) => void) {
  statusListeners.add(listener)
  return () => {
    statusListeners.delete(listener)
  }
}

/** Подписка на события потока. Обработчик можно не мемоизировать. */
export function useLive(handler: Listener) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => onLive((event) => ref.current(event)), [])
}

/** Есть ли сейчас связь с потоком событий. */
export function useLiveConnected() {
  const [value, setValue] = useState(connected)
  useEffect(() => {
    setValue(connected)
    return onLiveStatus(setValue)
  }, [])
  return value
}

/** Состояние языковой модели: обновляется, как только сервер заметит перемену. */
export function useLlmStatus() {
  const state = useApi<LlmStatus>('/llm/status')
  const reload = state.reload
  useLive((event) => {
    if (event.type === 'llm') void reload({ silent: true })
  })
  useEffect(() => {
    const timer = setInterval(() => void reload({ silent: true }), 5 * 60_000)
    return () => clearInterval(timer)
  }, [reload])
  return state
}
