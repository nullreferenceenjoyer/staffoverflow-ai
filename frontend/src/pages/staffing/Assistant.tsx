import { FormEvent, KeyboardEvent, ReactNode, useEffect, useRef, useState } from 'react'

import { api, AssistantChat, AssistantMessage, StaffingData, StaffingMeta } from '../../api'
import { Icon } from '../../components/icons'
import { Empty } from '../../components/ui'
import { useLlmStatus } from '../../live'
import { fmtDateTime, fmtRelative, useApi } from '../../lib'

const ABOUT_REGION = [
  'Где самый большой дефицит ставок?',
  'У каких учреждений нет данных и чего именно не хватает?',
  'Где ставок больше норматива и что с этим делать?',
  'Где штатки меняли и как изменился ФОТ?',
  'Сколько стоит закрыть дефицит и где он дороже всего?',
]
const ABOUT_ORG = [
  'Объясни, откуда взялся норматив по каждой группе',
  'Где у нас дефицит и какую заявку создать?',
  'Как изменился ФОТ после последнего изменения штатки?',
  'Что будет с ФОТ, если сократить 1 ставку уборщика?',
]

/** **жирный** внутри строки. Больше разметки модели не нужно. */
function inline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={i}>{part.slice(2, -2)}</strong>
      ) : (
        part
      ),
    )
}

/** Ответ модели: абзацы и списки «- …» / «1. …». */
export function Formatted({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>)
    blocks.push(
      list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>,
    )
    list = null
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const bullet = line.match(/^[-*•]\s+(.*)$/)
    const numbered = line.match(/^\d+[.)]\s+(.*)$/)
    if (bullet || numbered) {
      const ordered = Boolean(numbered)
      if (list && list.ordered !== ordered) flush()
      list ??= { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
      continue
    }
    flush()
    if (!line) continue
    const heading = line.replace(/^#+\s*/, '')
    blocks.push(
      heading !== line ? (
        <p key={blocks.length}>
          <strong>{inline(heading)}</strong>
        </p>
      ) : (
        <p key={blocks.length}>{inline(line)}</p>
      ),
    )
  }
  flush()
  return <>{blocks}</>
}

function Bubble({
  message,
}: {
  message: Pick<AssistantMessage, 'role' | 'content'> & { created_at?: string }
}) {
  return (
    <div className={`chat-msg chat-${message.role}`}>
      <div className="chat-bubble">
        {message.role === 'assistant' ? <Formatted text={message.content} /> : message.content}
      </div>
      {message.created_at && <time className="muted">{fmtDateTime(message.created_at)}</time>}
    </div>
  )
}

export function Assistant({
  meta,
  year,
  about,
  onAboutDone,
}: {
  meta: StaffingMeta
  year: string
  /** Учреждение, про которое начать новый разговор (кнопка в панели учреждения) */
  about: number | null
  onAboutDone: () => void
}) {
  const chats = useApi<AssistantChat[]>('/assistant/chats')
  const llm = useLlmStatus()
  const [active, setActive] = useState<AssistantChat | null>(null)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const thread = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  // Название учреждения для нового разговора про него
  const aboutOrg = useApi<StaffingData>(about ? `/staffing/institutions/${about}/data` : null, {
    year,
  })
  const director = meta.organization !== null

  useEffect(() => {
    if (about) {
      setActive(null)
      input.current?.focus()
    }
  }, [about])

  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: 'smooth' })
  }, [active, pending])

  async function open(id: number) {
    setError(null)
    onAboutDone()
    try {
      setActive(await api<AssistantChat>(`/assistant/chats/${id}`))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось открыть разговор')
    }
  }

  function startNew() {
    setActive(null)
    setError(null)
    onAboutDone()
    input.current?.focus()
  }

  async function remove(chat: AssistantChat) {
    if (!window.confirm(`Удалить разговор «${chat.title}»?`)) return
    await api(`/assistant/chats/${chat.id}`, { method: 'DELETE' })
    if (active?.id === chat.id) setActive(null)
    void chats.reload({ silent: true })
  }

  async function send(question: string) {
    const text = question.trim()
    if (text.length < 2 || pending) return
    setPending(text)
    setDraft('')
    setError(null)
    try {
      const chat = await api<AssistantChat>('/assistant/ask', {
        body: active
          ? { chat_id: active.id, question: text }
          : { year, organization_id: about, question: text },
      })
      setActive(chat)
      onAboutDone()
      void chats.reload({ silent: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Помощник не ответил')
      setDraft(text) // вопрос не теряется: можно отправить ещё раз
    } finally {
      setPending(null)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void send(draft)
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send(draft)
    }
  }

  const messages = active?.messages ?? []
  const aboutName = about ? (aboutOrg.data?.organization ?? '…') : null
  const subject = active
    ? (active.organization ?? 'вся территория')
    : (aboutName ?? (director ? meta.organization!.name : 'вся территория'))
  const chatYear = active?.year ?? year
  const suggestions = active?.organization_id || about || director ? ABOUT_ORG : ABOUT_REGION
  const down = llm.data && (llm.data.available === false || !llm.data.configured)

  return (
    <div className="assistant">
      <aside className="assistant-list" aria-label="Разговоры">
        <button className="primary" onClick={startNew}>
          <Icon name="plus" size={16} /> Новый разговор
        </button>
        {chats.data?.length === 0 && <p className="muted">Разговоров пока нет.</p>}
        <ul>
          {chats.data?.map((chat) => (
            <li key={chat.id} className={chat.id === active?.id ? 'active' : ''}>
              <button className="assistant-chat" onClick={() => void open(chat.id)}>
                <strong>{chat.title}</strong>
                <span className="muted">
                  {chat.organization ?? 'Вся территория'} · {chat.year} ·{' '}
                  {fmtRelative(chat.updated_at)}
                </span>
              </button>
              <button
                className="ghost icon-only"
                aria-label="Удалить разговор"
                onClick={() => void remove(chat)}
              >
                <Icon name="x" size={14} />
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="assistant-main card">
        <div className="assistant-head">
          <div>
            <strong>{active ? active.title : 'Новый разговор'}</strong>
            <div className="muted">
              Про: {subject} · {chatYear}
            </div>
          </div>
        </div>

        {down && (
          <div className="notice">
            Локальная модель сейчас не отвечает, помощник недоступен. Анализ и заявки работают как
            обычно.
          </div>
        )}

        <div className="assistant-thread" ref={thread}>
          {messages.length === 0 && !pending ? (
            <Empty>
              <p>
                Помощник видит то же, что и вы в разделе: нормативы, показатели, штатку с окладами и
                историей изменений, ФОТ, результаты анализа и кадровые заявки. Он объясняет цифры и
                подсказывает, что делать, но сам ничего не меняет.
              </p>
              <div className="chips assistant-suggest">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    className="chip"
                    disabled={!!pending}
                    onClick={() => void send(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </Empty>
          ) : (
            <>
              {messages.map((m) => (
                <Bubble key={m.id} message={m} />
              ))}
              {pending && (
                <>
                  <Bubble message={{ role: 'user', content: pending }} />
                  <div className="chat-msg chat-assistant">
                    <div className="chat-bubble chat-typing" aria-live="polite">
                      Смотрю данные и думаю…
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        <form className="assistant-input" onSubmit={submit}>
          <textarea
            ref={input}
            rows={2}
            value={draft}
            maxLength={2000}
            placeholder="Например: почему по делопроизводству дефицит?"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            disabled={!!pending}
          />
          <button className="primary" type="submit" disabled={!!pending || draft.trim().length < 2}>
            <Icon name="message" size={16} /> Спросить
          </button>
        </form>
      </section>
    </div>
  )
}
