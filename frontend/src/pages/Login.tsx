import { useState } from 'react'

import { api, setToken, User } from '../api'
import { Icon } from '../components/icons'
import { Field, Form } from '../components/ui'

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  async function submit() {
    const form = new URLSearchParams({ username: email, password })
    const { access_token } = await api<{ access_token: string }>('/auth/login', { form })
    setToken(access_token)
    onLogin(await api<User>('/auth/me'))
  }

  return (
    <div className="login">
      <div className="login-about">
        <span className="brand-mark">
          <Icon name="users" />
        </span>
        <h1>Кадровый потенциал ОУ</h1>
        <p>
          Показывает, сколько работы у управленческого и вспомогательного персонала школ и детских
          садов на самом деле, и помогает довести решение до приказа.
        </p>
        <ul>
          <li>
            <Icon name="gauge" /> загрузка персонала по корпусам и площадкам
          </li>
          <li>
            <Icon name="pin" /> адреса и мощность зданий из РГИС
          </li>
          <li>
            <Icon name="inbox" /> заявки с ответственными и сроками
          </li>
          <li>
            <Icon name="sparkles" /> помощник, который отвечает только по вашим данным
          </li>
        </ul>
      </div>
      <div className="card login-card">
        <h2>Вход</h2>
        <Form onSubmit={submit} submitLabel="Войти">
          <Field label="E-mail">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
              required
            />
          </Field>
          <Field label="Пароль">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
        </Form>
      </div>
    </div>
  )
}
