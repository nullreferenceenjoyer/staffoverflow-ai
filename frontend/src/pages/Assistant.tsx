import { FormEvent, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { streamChat } from '../api'
import { Page } from '../components/ui'
import { useApi } from '../lib'

interface DataBlock {
  title: string
  markdown: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  blocks?: DataBlock[]
  steps?: string[]
  error?: string
}

const TOOL_LABELS: Record<string, string> = {
  organizations: 'подбираю учреждения',
  organization_report: 'открываю отчёт по учреждению',
  deviations: 'ищу отклонения',
  centralization: 'считаю сценарий централизации',
  knowledge_search: 'ищу в нормативных документах',
}

const EXAMPLES = [
  'Где самый большой избыток АУП?',
  'Как идём к цели паспорта проекта?',
  'Сколько ставок высвободит централизация бухгалтерии и кадров?',
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
      { role: 'assistant', content: '', blocks: [], steps: [] },
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
          } else if (event.type === 'tool') {
            patchLast((m) => ({
              ...m,
              steps: [...(m.steps ?? []), TOOL_LABELS[event.name] ?? event.name],
            }))
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
      hint="Сначала показывает данные из базы, подобранные под вопрос, затем локальная модель пишет к ним вывод. Всё в пределах ваших прав доступа."
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
                    <summary>
                      <span className="data-tag">из базы</span> {block.title}
                    </summary>
                    <Markdown remarkPlugins={[remarkGfm]}>{block.markdown}</Markdown>
                  </details>
                ))}
                {message.steps?.map((step, i) => (
                  <div key={i} className="chat-step">
                    {step}…
                  </div>
                ))}
                {message.content && (
                  <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
                )}
                {busy && last && !message.content && !message.error && (
                  <span className="muted">Модель пишет вывод…</span>
                )}
                {message.error && (
                  <div className="chat-error">
                    {message.blocks?.length
                      ? `Вывод модели не получен (${message.error}). Данные выше — из базы.`
                      : message.error}
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
              Спросить
            </button>
          )}
        </form>
        <p className="muted">
          Таблицы с пометкой «из базы» собирает сама система — им можно верить так же, как остальным
          разделам. Текст под ними пишет модель: это подсказка, а не решение.
        </p>
      </div>
    </Page>
  )
}
