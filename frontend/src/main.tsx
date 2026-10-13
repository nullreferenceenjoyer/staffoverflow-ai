import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import './styles.css'

// Тему выставляем до первой отрисовки, иначе форма входа мигнёт светлой
document.documentElement.dataset.theme =
  localStorage.getItem('hr-edu-theme') ??
  (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
