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
          <Icon name="inbox" />
        </span>
        <h1>Заявки ОУ</h1>
        <p>
          Сотрудник школы или детского сада пишет, что нужно сделать. Исполнителя и срок система
          подберёт сама, а дальше покажет, на каком этапе работа.
        </p>
        <ul>
          <li>
            <Icon name="wrench" /> тема и исполнитель определяются по тексту заявки
          </li>
          <li>
            <Icon name="clock" /> сроки, напоминания и пауза, пока ждут ответа
          </li>
          <li>
            <Icon name="message" /> переписка и вся история в карточке заявки
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
