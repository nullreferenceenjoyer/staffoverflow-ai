import { useState } from 'react'

import { api, setToken, User } from '../api'
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
        <h1>Кадровый потенциал ОУ</h1>
        <p>
          Система сравнивает штатные расписания школ и детских садов с нормативами и показывает, где
          ставок больше или меньше, чем нужно.
        </p>
        <ul>
          <li>считает нормативную численность по контингенту и зданиям;</li>
          <li>находит избыток, нехватку и дублирование функций;</li>
          <li>оценивает эффект от централизации бухгалтерии, кадров, уборки и охраны;</li>
          <li>готовит проекты штатных расписаний и документы к ним.</li>
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
