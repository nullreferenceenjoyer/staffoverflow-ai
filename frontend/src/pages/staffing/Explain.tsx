import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react'

import { api, stream, StaffingMeta, StaffingSummary } from '../../api'
import { Icon } from '../../components/icons'
import { Empty } from '../../components/ui'
import { useLlmStatus } from '../../live'
import { useApi } from '../../lib'
import { Formatted } from './Assistant'

interface Turn {
  role: 'user' | 'assistant'
  content: string
}

function suggestions(school: string | null, position: string | null) {
  if (position)
    return [
      `Почему высвобождают ставки «${position}»?`,
      `Что будет с сотрудниками на должности «${position}»?`,
      'Это вакансии, совмещение или занятые ставки?',
    ]
  if (school)
    return [
      'Что в этой школе высвобождается и почему?',
      'Можно ли здесь обойтись без сокращения людей?',
      'Что будет с сотрудниками этой школы?',
    ]
  return [
    'Как система решает, какие ставки высвобождать?',
    'Кого касается сокращение и что положено сотрудникам?',
    'Что значит «снять совмещение» для сотрудника?',
    'Куда может перейти сотрудник с сокращаемой ставки?',
  ]
}

/**
 * Разъяснения по высвобождению: модель отвечает потоком по короткой справке, поэтому
 * первые слова видны почти сразу. Разговор не сохраняется — это подсказка, а не журнал.
 */
export function Explain({ meta }: { meta: StaffingMeta }) {
  const summary = useApi<StaffingSummary>('/staffing/summary')
  const llm = useLlmStatus()
  const director = meta.organization !== null
  const [school, setSchool] = useState<number | null>(null)
  const [position, setPosition] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const thread = useRef<HTMLDivElement>(null)
  const stop = useRef<AbortController | null>(null)

  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight })
  }, [turns])

  useEffect(() => () => stop.current?.abort(), [])

  // Модель заранее читает справку по выбранной школе и должности: вопрос потом
  // отвечается почти сразу. Ошибки не важны — без прогрева просто чуть дольше
  useEffect(() => {
    const timer = setTimeout(() => {
      void api('/program/explain/warm', {
        body: { organization_id: director ? null : school, position: position || null },
      }).catch(() => undefined)
    }, 600)
    return () => clearTimeout(timer)
  }, [director, school, position])

  const data = summary.data
  const schools = (data?.schools ?? []).filter((s) => s.total > 0)
  const positions = (data?.positions ?? []).map((p) => p.position)
  const schoolName = director
    ? (meta.organization?.name ?? null)
    : (schools.find((s) => s.organization_id === school)?.organization ?? null)

  async function ask(question: string) {
    const text = question.trim()
    if (text.length < 2 || busy) return
    const history = turns
    setTurns([...history, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    setDraft('')
    setError(null)
    setBusy(true)
    const controller = new AbortController()
    stop.current = controller
    try {
      await stream(
        '/program/explain',
        {
          question: text,
          organization_id: director ? null : school,
          position: position || null,
          history,
        },
        (piece) =>
          setTurns((all) => {
            const next = [...all]
            const last = next[next.length - 1]
            next[next.length - 1] = { ...last, content: last.content + piece }
            return next
          }),
        controller.signal,
      )
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : 'Модель не ответила')
        setTurns(history)
        setDraft(text)
      }
    } finally {
      setBusy(false)
      stop.current = null
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void ask(draft)
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void ask(draft)
    }
  }

  const down = llm.data && (llm.data.available === false || !llm.data.configured)
  const last = turns[turns.length - 1]

  return (
    <section className="assistant-main card explain">
      <div className="assistant-head explain-head">
        <div>
          <strong>Разъяснения по высвобождению ставок</strong>
          <div className="muted">
            Почему, откуда цифра, как это делается и что дальше с сотрудником. Отвечает локальная
            модель{llm.data?.model ? ` (${llm.data.model})` : ''} по расчёту системы.
          </div>
        </div>
        <div className="explain-filters">
          {!director && (
            <select
              aria-label="Школа"
              value={school ?? ''}
              onChange={(e) => setSchool(Number(e.target.value) || null)}
            >
              <option value="">Весь округ</option>
              {schools.map((s) => (
                <option key={s.organization_id} value={s.organization_id}>
                  {s.organization}
                </option>
              ))}
            </select>
          )}
          <select
            aria-label="Должность"
            value={position}
            onChange={(e) => setPosition(e.target.value)}
          >
            <option value="">Все должности</option>
            {positions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          {turns.length > 0 && (
            <button className="ghost" onClick={() => setTurns([])} disabled={busy}>
              Очистить
            </button>
          )}
        </div>
      </div>

      {down && (
        <div className="notice">
          Локальная модель сейчас не отвечает. Расчёт и объяснения на вкладке «Итог» доступны как
          обычно.
        </div>
      )}

      <div className="assistant-thread" ref={thread}>
        {turns.length === 0 ? (
          <Empty>
            <p>
              Спросите, почему высвобождаются ставки — по округу, по школе или по должности. Модель
              видит итог расчёта и порядок: сначала вакансии, потом совмещение, и только остаток —
              сокращение занятых ставок.
            </p>
            <div className="chips assistant-suggest">
              {suggestions(schoolName, position || null).map((s) => (
                <button key={s} className="chip" disabled={busy} onClick={() => void ask(s)}>
                  {s}
                </button>
              ))}
            </div>
          </Empty>
        ) : (
          turns.map((t, i) => (
            <div key={i} className={`chat-msg chat-${t.role}`}>
              <div className="chat-bubble" aria-live={t === last ? 'polite' : undefined}>
                {t.role === 'assistant' ? (
                  t.content ? (
                    <Formatted text={t.content} />
                  ) : (
                    <span className="chat-typing">Смотрю расчёт…</span>
                  )
                ) : (
                  t.content
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      <form className="assistant-input" onSubmit={submit}>
        <textarea
          rows={2}
          value={draft}
          maxLength={1000}
          placeholder={
            schoolName
              ? `Например: почему в «${schoolName}» снимают совмещение?`
              : 'Например: почему сокращают грузчиков?'
          }
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          disabled={busy}
        />
        {busy ? (
          <button type="button" onClick={() => stop.current?.abort()}>
            <Icon name="pause" size={16} /> Остановить
          </button>
        ) : (
          <button className="primary" type="submit" disabled={draft.trim().length < 2}>
            <Icon name="message" size={16} /> Спросить
          </button>
        )}
      </form>
    </section>
  )
}
