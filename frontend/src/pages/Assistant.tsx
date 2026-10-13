import { FormEvent, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { ChatSource, streamChat } from '../api'
import { Icon } from '../components/icons'
import { Page } from '../components/ui'
import { useApi } from '../lib'

interface DataBlock {
  title: string
  markdown: string
  source: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  blocks?: DataBlock[]
  sources?: ChatSource[]
  warning?: string
  error?: string
}

const EXAMPLES = [
  'Где персонал простаивает в соседних корпусах?',
  'Где самый большой избыток АУП?',
  'Сколько заявок просрочено и по каким темам?',
  'Как идём к цели паспорта проекта?',
  'Сколько вакансий можно сократить без увольнений?',
  'Сколько логопедов положено на детей с ОВЗ и на основании чего?',
]

export function Assistant() {
  const status = useApi<{ configured: boolean; online: boolean; model: string | null }>(
    '/assistant/status',
  )
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  // Уход со страницы обрывает генерацию: иначе модель продолжит занимать CPU впустую
  useEffect(() => () => abort.current?.abort(), [])

  async function ask(question: string) {
    if (!question.trim() || busy) return
    const history = messages
      .filter((m) => m.content)
      .map(({ role, content }) => ({ role, content }))
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '', blocks: [] },
    ])
    setInput('')
    setBusy(true)

    const patchLast = (patch: (message: Message) => Message) =>
      setMessages((prev) => [...prev.slice(0, -1), patch(prev[prev.length - 1])])

    abort.current = new AbortController()
    try {
      await streamChat(
        question,
        history,
        (event) => {
          if (event.type === 'data') {
            patchLast((m) => ({ ...m, blocks: [...(m.blocks ?? []), event] }))
          } else if (event.type === 'delta') {
            patchLast((m) => ({ ...m, content: m.content + event.text }))
          } else if (event.type === 'sources') {
            patchLast((m) => ({ ...m, sources: event.items }))
          } else if (event.type === 'warning') {
            patchLast((m) => ({ ...m, warning: event.message }))
          } else if (event.type === 'error') {
            patchLast((m) => ({ ...m, error: event.message }))
          }
        },
        abort.current.signal,
      )
    } catch (e) {
      if (!abort.current.signal.aborted) {
        patchLast((m) => ({ ...m, error: e instanceof Error ? e.message : 'Ошибка' }))
      }
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void ask(input)
  }

  const offline = status.data && !status.data.online

  return (
    <Page
      title="Помощник"
      hint="Отвечает только по базе данных системы и документам из базы знаний — других источников у него нет. Под каждым ответом видно, на что он опирается."
    >
      {offline && (
        <div className="notice">
          {status.data?.configured
            ? 'Локальная модель не отвечает — помощник покажет только данные из базы, без вывода. Проверьте сервис llm или сервер в LM Studio.'
            : 'Локальная модель не подключена — помощник покажет только данные из базы, без вывода. Как подключить: README, раздел «Локальная модель».'}
        </div>
      )}
      <div className="chat">
        <div className="chat-log">
          {messages.length === 0 && (
            <div className="chat-empty">
              <p>Спросите что-нибудь о штатных расписаниях, например:</p>
              <div className="chips">
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    className="chip"
                    onClick={() => ask(example)}
                    disabled={busy}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message, index) => {
            const last = index === messages.length - 1
            if (message.role === 'user') {
              return (
                <div key={index} className="bubble user">
                  {message.content}
                </div>
              )
            }
            return (
              <div key={index} className="bubble assistant">
                {message.blocks?.map((block, i) => (
                  <details key={i} className="data-block" open>
                    <summary title={block.source}>
                      <span className={`data-tag ${block.source === 'База знаний' ? 'doc' : ''}`}>
                        {block.source === 'База знаний' ? 'документ' : 'из базы'}
                      </span>{' '}
                      {block.title}
                    </summary>
                    <Markdown remarkPlugins={[remarkGfm]}>{block.markdown}</Markdown>
                  </details>
                ))}
                {message.content && (
                  <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
                )}
                {busy && last && !message.content && !message.error && (
                  <span className="typing">
                    <i />
                    <i />
                    <i />
                  </span>
                )}
                {message.warning && (
                  <div className="chat-warning">
                    <Icon name="alert" size={14} /> {message.warning}
                  </div>
                )}
                {message.error && (
                  <div className="chat-error">
                    {message.blocks?.length
                      ? `Вывод модели не получен (${message.error}). Данные выше — из базы.`
                      : message.error}
                  </div>
                )}
                {message.sources && message.sources.length > 0 && (
                  <div className="sources">
                    Источники:
                    {message.sources.map((source, i) => (
                      <span key={i} className="source" title={source.ref ?? undefined}>
                        <Icon name={source.kind === 'document' ? 'file' : 'database'} size={13} />
                        {source.kind === 'document' ? (source.ref ?? source.title) : source.title}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          <div ref={bottom} />
        </div>
        <form className="chat-input" onSubmit={submit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ваш вопрос"
            disabled={busy}
            maxLength={2000}
          />
          {busy ? (
            <button type="button" onClick={() => abort.current?.abort()}>
              Остановить
            </button>
          ) : (
            <button className="primary" disabled={!input.trim()}>
              <Icon name="sparkles" size={16} /> Спросить
            </button>
          )}
        </form>
        <p className="muted">
          Блоки с пометками «из базы» и «документ» собирает сама система — им можно верить так же,
          как остальным разделам. Текст под ними пишет модель строго по этим блокам; если она
          упомянет документ, которого в базе знаний нет, появится предупреждение.
        </p>
      </div>
    </Page>
  )
}
