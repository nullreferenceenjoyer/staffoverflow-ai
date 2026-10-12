import { useState } from 'react'

import { api, OrgRequest, OrgSummary } from '../api'
import { useUser } from '../App'
import { ActionButton, Async, Badge, Card, Empty, Field, Form, Modal, Page } from '../components/ui'
import { fmtDateTime, ROLE_LABELS, useApi } from '../lib'

const STATUS: Record<OrgRequest['status'], { label: string; tone: string }> = {
  new: { label: 'Новое', tone: 'amber' },
  in_progress: { label: 'В работе', tone: 'blue' },
  closed: { label: 'Закрыто', tone: 'gray' },
}

function NewRequest({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const user = useUser()
  const isDirector = user.role === 'director'
  const organizations = useApi<OrgSummary[]>(isDirector ? null : '/organizations')
  const [organization, setOrganization] = useState('')
  const [text, setText] = useState('')

  async function submit() {
    await api('/requests', {
      body: { text, organization_id: isDirector ? null : Number(organization) },
    })
    onCreated()
    onClose()
  }

  return (
    <Modal title="Новое обращение" onClose={onClose}>
      <Form onSubmit={submit} submitLabel="Отправить">
        {!isDirector && (
          <Field label="Учреждение">
            <select value={organization} onChange={(e) => setOrganization(e.target.value)} required>
              <option value="">Выберите…</option>
              {organizations.data?.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Текст обращения">
          <textarea
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Например: нужна дополнительная ставка логопеда, в первые классы пришло 14 детей с ОВЗ"
            minLength={10}
            required
          />
        </Field>
        <p className="muted">
          Система сама определит тему и направит обращение нужному специалисту.
        </p>
      </Form>
    </Modal>
  )
}

export function Requests() {
  const user = useUser()
  const state = useApi<OrgRequest[]>('/requests')
  const [creating, setCreating] = useState(false)

  async function update(request: OrgRequest, body: Record<string, unknown>) {
    await api(`/requests/${request.id}`, { method: 'PATCH', body })
    await state.reload()
  }

  async function close(request: OrgRequest) {
    const resolution = window.prompt('Ответ учреждению')
    if (resolution) await update(request, { status: 'closed', resolution })
  }

  return (
    <Page
      title="Обращения"
      hint="Заявки от учреждений. Тема определяется автоматически, обращение попадает к ответственной роли."
      actions={
        user.role !== 'observer' && (
          <button className="primary" onClick={() => setCreating(true)}>
            Новое обращение
          </button>
        )
      }
    >
      <Async state={state}>
        {(requests) =>
          requests.length === 0 ? (
            <Empty>Обращений нет.</Empty>
          ) : (
            <>
              {requests.map((request) => {
                // Отвечать может адресат обращения или администратор
                const mine = user.role === request.routed_role || user.role === 'admin'
                return (
                  <Card key={request.id}>
                    <div className="card-head">
                      <div className="chips">
                        <Badge tone={STATUS[request.status].tone}>
                          {STATUS[request.status].label}
                        </Badge>
                        <Badge tone="blue">{request.topic_title}</Badge>
                        <span className="muted">
                          → {ROLE_LABELS[request.routed_role]} · определено{' '}
                          {request.classified_by === 'llm' ? 'моделью' : 'по ключевым словам'}
                        </span>
                      </div>
                      <span className="muted">{fmtDateTime(request.created_at)}</span>
                    </div>
                    <p>{request.text}</p>
                    <div className="muted">{request.organization}</div>
                    {request.resolution && (
                      <div className="notice">Ответ: {request.resolution}</div>
                    )}
                    {mine && request.status !== 'closed' && (
                      <div className="actions">
                        {request.status === 'new' && (
                          <ActionButton onClick={() => update(request, { status: 'in_progress' })}>
                            Взять в работу
                          </ActionButton>
                        )}
                        <ActionButton onClick={() => close(request)}>
                          Ответить и закрыть
                        </ActionButton>
                      </div>
                    )}
                  </Card>
                )
              })}
            </>
          )
        }
      </Async>
      {creating && <NewRequest onClose={() => setCreating(false)} onCreated={state.reload} />}
    </Page>
  )
}
