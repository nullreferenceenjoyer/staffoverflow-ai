import { ReactNode, useState } from 'react'

import { api, download, ImportResult } from '../api'
import { Icon } from './icons'
import { Modal } from './ui'

const TITLES = {
  organizations: 'Загрузка учреждений из Excel',
  users: 'Загрузка пользователей из Excel',
}

/** Пароли новых пользователей — файлом, чтобы раздать их и не переписывать с экрана. */
function savePasswords(rows: ImportResult['passwords']) {
  const lines = ['ФИО;E-mail;Пароль', ...rows.map((r) => `${r.full_name};${r.email};${r.password}`)]
  // BOM — чтобы Excel открыл файл в правильной кодировке
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'пароли.csv'
  link.click()
  URL.revokeObjectURL(url)
}

/**
 * Загрузка справочника из таблицы: шаблон, выбор файла и отчёт о том, что получилось.
 * Дополнительные поля формы (например, муниципалитет по умолчанию) передаются в children.
 */
export function ImportDialog({
  kind,
  onClose,
  onDone,
  children,
  extra,
  title,
  uploadUrl,
  templateUrl,
}: {
  kind: string
  onClose: () => void
  onDone: () => void
  children?: ReactNode
  extra?: Record<string, string>
  /** Для загрузок вне администрирования: свои заголовок и адреса */
  title?: string
  uploadUrl?: string
  templateUrl?: string
}) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)

  async function upload() {
    if (!file) return
    setBusy(true)
    setError(null)
    const form = new FormData()
    form.append('file', file)
    for (const [key, value] of Object.entries(extra ?? {})) form.append(key, value)
    try {
      setResult(await api<ImportResult>(uploadUrl ?? `/admin/import/${kind}`, { form }))
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить файл')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={title ?? TITLES[kind as keyof typeof TITLES]} onClose={onClose} wide>
      {result ? (
        <div className="import-result">
          <div className="kpis">
            <div className="kpi">
              <span className="muted">Добавлено</span>
              <strong>{result.created}</strong>
            </div>
            <div className="kpi">
              <span className="muted">Обновлено</span>
              <strong>{result.updated}</strong>
            </div>
            <div className="kpi">
              <span className="muted">Пропущено</span>
              <strong className={result.skipped ? 'late' : ''}>{result.skipped}</strong>
            </div>
          </div>
          {result.created_municipalities.length > 0 && (
            <p className="muted">
              Новые муниципалитеты: {result.created_municipalities.join(', ')}
            </p>
          )}
          {result.passwords.length > 0 && (
            <div className="notice notice-info">
              <Icon name="alert" />
              <div>
                <strong>Пароли новых пользователей показываются один раз.</strong> Сохраните их и
                передайте людям.
                <table className="stack compact">
                  <tbody>
                    {result.passwords.map((p) => (
                      <tr key={p.email}>
                        <td data-label="ФИО">{p.full_name}</td>
                        <td data-label="E-mail">{p.email}</td>
                        <td data-label="Пароль">
                          <code>{p.password}</code>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button onClick={() => savePasswords(result.passwords)}>
                  <Icon name="download" size={16} /> Скачать пароли
                </button>
              </div>
            </div>
          )}
          {result.errors.length > 0 && (
            <>
              <h3>Что не загрузилось</h3>
              <table className="stack">
                <thead>
                  <tr>
                    <th>Строка</th>
                    <th>Причина</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((e) => (
                    <tr key={`${e.row}-${e.message}`}>
                      <td data-label="Строка" className="num">
                        {e.row}
                      </td>
                      <td data-label="Причина">{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">
                Исправьте эти строки в файле и загрузите его снова: то, что уже загружено, не
                задвоится.
              </p>
            </>
          )}
          <div className="form-actions">
            <button onClick={() => setResult(null)}>Загрузить ещё файл</button>
            <button className="primary" onClick={onClose}>
              Готово
            </button>
          </div>
        </div>
      ) : (
        <div className="form">
          <ol className="import-steps">
            <li>
              <span>Скачайте шаблон и заполните его. На втором листе — что писать в колонках.</span>
              <button
                type="button"
                onClick={() =>
                  download(templateUrl ?? `/admin/templates/${kind}.xlsx`, `шаблон-${kind}.xlsx`)
                }
              >
                <Icon name="download" size={16} /> Шаблон Excel
              </button>
            </li>
            <li>
              <span>Выберите заполненный файл — .xlsx или .csv.</span>
              <label className="file-pick">
                <Icon name="upload" size={16} />
                {file ? file.name : 'Выбрать файл'}
                <input
                  type="file"
                  accept=".xlsx,.csv"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </li>
          </ol>
          {children}
          {error && <div className="notice notice-error">{error}</div>}
          <div className="form-actions">
            <button className="primary" disabled={!file || busy} onClick={upload}>
              {busy ? 'Загружаем…' : 'Загрузить'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
