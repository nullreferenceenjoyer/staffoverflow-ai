import { FormEvent, useState } from 'react'

import { api, download, KnowledgeDoc, SearchHit } from '../api'
import { useUser } from '../App'
import { ActionButton, Async, Badge, Card, Empty, Field, Form, Modal, Page } from '../components/ui'
import { canApprove, useApi } from '../lib'

function Upload({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [file, setFile] = useState<File | null>(null)

  async function submit() {
    if (!file) throw new Error('Выберите файл')
    const form = new FormData()
    form.set('file', file)
    form.set('title', title)
    form.set('source_ref', sourceRef)
    await api('/knowledge/documents', { form })
    onDone()
    onClose()
  }

  return (
    <Modal title="Загрузка документа" onClose={onClose}>
      <Form onSubmit={submit} submitLabel="Загрузить и проиндексировать">
        <Field label="Название">
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </Field>
        <Field label="Реквизиты (номер, дата)">
          <input value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} />
        </Field>
        <Field label="Файл: PDF, DOCX, TXT или MD">
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <p className="muted">
          У PDF должен быть текстовый слой: сканы без распознавания не читаются.
        </p>
      </Form>
    </Modal>
  )
}

export function Knowledge() {
  const user = useUser()
  const documents = useApi<KnowledgeDoc[]>('/knowledge/documents')
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [uploading, setUploading] = useState(false)

  async function search(event: FormEvent) {
    event.preventDefault()
    if (query.trim().length < 3) return
    setSearching(true)
    try {
      setHits(await api<SearchHit[]>('/knowledge/search', { query: { q: query } }))
    } finally {
      setSearching(false)
    }
  }

  return (
    <Page
      title="База знаний"
      hint="Нормативные документы и методики. Поиск работает по смыслу запроса, а не только по точным словам."
      actions={
        canApprove(user) && (
          <button className="primary" onClick={() => setUploading(true)}>
            Загрузить документ
          </button>
        )
      }
    >
      <Card>
        <form className="search" onSubmit={search}>
          <input
            type="search"
            placeholder="Например: сколько логопедов положено на детей с ОВЗ"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="primary" disabled={searching}>
            {searching ? 'Ищу…' : 'Найти'}
          </button>
        </form>
        {hits?.length === 0 && <Empty>Ничего не найдено.</Empty>}
        {hits?.map((hit, index) => (
          <div key={index} className="hit">
            <div className="card-head">
              <strong>{hit.title}</strong>
              <span className="muted">близость {Math.round(hit.score * 100)} %</span>
            </div>
            <div className="muted">
              {hit.source_ref}
              {hit.is_summary && ' · краткая справка, не официальный текст'}
            </div>
            <p>{hit.content}</p>
            {hit.norms.length > 0 && (
              <div className="chips">
                <span className="muted">Используется в нормативах:</span>
                {hit.norms.map((norm) => (
                  <span key={norm.id} className="chip">
                    {norm.title}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </Card>

      <Card title="Документы">
        <Async state={documents}>
          {(list) => (
            <table>
              <thead>
                <tr>
                  <th>Документ</th>
                  <th>Реквизиты</th>
                  <th>Связанные нормативы</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      {doc.title} {doc.is_summary && <Badge tone="amber">справка</Badge>}
                    </td>
                    <td className="muted">{doc.source_ref ?? '—'}</td>
                    <td className="muted">{doc.norms.map((n) => n.title).join('; ') || '—'}</td>
                    <td className="nowrap">
                      {doc.has_file && (
                        <button
                          onClick={() => download(`/knowledge/documents/${doc.id}/file`, doc.title)}
                        >
                          Скачать
                        </button>
                      )}{' '}
                      {canApprove(user) && (
                        <ActionButton
                          className="ghost"
                          confirm={`Удалить документ «${doc.title}»?`}
                          onClick={async () => {
                            await api(`/knowledge/documents/${doc.id}`, { method: 'DELETE' })
                            await documents.reload()
                          }}
                        >
                          Удалить
                        </ActionButton>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Async>
      </Card>
      {uploading && <Upload onClose={() => setUploading(false)} onDone={documents.reload} />}
    </Page>
  )
}
