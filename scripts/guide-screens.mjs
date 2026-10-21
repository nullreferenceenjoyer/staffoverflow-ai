// Снимает скриншоты для docs/guide.md с поднятого стенда (docker compose, порт 8090).
//
//   node scripts/guide-screens.mjs [http://localhost:8090] [12-uvolennye]
//
// Второй аргумент — снять только кадры, чьё имя с него начинается.
// Нужны Node 22+ и Chrome. Вход — демо-учётками из seed.py. На вкладке «Уволенные»
// фамилии и имена файлов приказов перед съёмкой заменяются: в репозиторий их не кладём.
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.argv[2] ?? 'http://localhost:8090'
const ONLY = process.argv[3]
// Какую школу показывать в карточках; по умолчанию — первая подходящая
const SCHOOL = process.env.GUIDE_SCHOOL ?? ''
const HOZ_SCHOOL = process.env.GUIDE_HOZ_SCHOOL ?? ''
const OUT = fileURLToPath(new URL('../docs/guide/', import.meta.url))
const CHROME = process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PASSWORD = 'demo12345'
const PORT = 9333
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function login(email) {
  const response = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    body: new URLSearchParams({ username: email, password: PASSWORD }),
  })
  if (!response.ok) throw new Error(`Не удалось войти как ${email}: ${response.status}`)
  return (await response.json()).access_token
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    const waiting = new Map()
    const listeners = []
    let id = 0
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.id && waiting.has(message.id)) {
        const [ok, fail] = waiting.get(message.id)
        waiting.delete(message.id)
        if (message.error) fail(new Error(message.error.message))
        else ok(message.result)
      } else if (message.method) {
        listeners.forEach((l) => l(message))
      }
    }
    ws.onerror = reject
    ws.onopen = () =>
      resolve({
        send: (method, params = {}) =>
          new Promise((ok, fail) => {
            id += 1
            waiting.set(id, [ok, fail])
            ws.send(JSON.stringify({ id, method, params }))
          }),
        once: (method) =>
          new Promise((ok) => {
            const listener = (m) => {
              if (m.method !== method) return
              listeners.splice(listeners.indexOf(listener), 1)
              ok(m.params)
            }
            listeners.push(listener)
          }),
        close: () => ws.close(),
      })
  })
}

// Хелперы внутри страницы: найти карточку по заголовку, нажать кнопку по тексту.
// Анимации выключаются, иначе снимок ловит карточки на середине появления
const HELPERS = `
  window.__card = (title) => [...document.querySelectorAll('.card')]
    .find((c) => c.querySelector('h2')?.textContent.includes(title))
  window.__click = (text) => {
    const button = [...document.querySelectorAll('button, [role=tab]')]
      .find((b) => b.textContent.trim() === text)
    button?.click()
    return Boolean(button)
  }
  document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style')
    style.textContent = '*, *::before, *::after { animation: none !important; transition: none !important }'
    document.head.append(style)
  })
`

async function main() {
  mkdirSync(OUT, { recursive: true })
  const profile = mkdtempSync(join(tmpdir(), 'guide-chrome-'))
  const chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--hide-scrollbars',
    '--window-size=1440,900',
    'about:blank',
  ])
  try {
    let pages = null
    for (let i = 0; i < 50 && !pages; i++) {
      await sleep(200)
      pages = await fetch(`http://127.0.0.1:${PORT}/json/list`)
        .then((r) => r.json())
        .catch(() => null)
    }
    // Каждая страница — в новой вкладке, старая закрывается: иначе соединения прошлых
    // страниц (поток событий) копятся, и через десяток переходов стенд перестаёт отвечать
    let cdp = null
    let current = pages.find((p) => p.type === 'page')?.id
    const open = async () => {
      const fresh = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, {
        method: 'PUT',
      }).then((r) => r.json())
      const next = await connect(fresh.webSocketDebuggerUrl)
      await next.send('Page.enable')
      await next.send('Runtime.enable')
      await next.send('Emulation.setDeviceMetricsOverride', {
        width: 1440,
        height: 900,
        deviceScaleFactor: 1,
        mobile: false,
      })
      await next.send('Page.addScriptToEvaluateOnNewDocument', { source: HELPERS })
      cdp?.close()
      if (current) await fetch(`http://127.0.0.1:${PORT}/json/close/${current}`).catch(() => null)
      cdp = next
      current = fresh.id
    }

    const js = async (expression) => {
      const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
        expression,
        awaitPromise: true,
        returnByValue: true,
      })
      if (exceptionDetails) throw new Error(exceptionDetails.exception?.description ?? expression)
      return result.value
    }

    // Ждём, пока уйдут заглушки загрузки, и ещё немного — на графики
    const settle = async (extra = 900) => {
      let calm = 0
      for (let i = 0; i < 150 && calm < 3; i++) {
        await sleep(200)
        const ready = await js(`document.querySelectorAll('.skeleton').length === 0 &&
          Boolean(document.querySelector('main .card, main .kpi, main .program-hero, .drawer'))`)
        calm = ready ? calm + 1 : 0
      }
      await sleep(extra)
    }

    const go = async (path, extra, wait = true) => {
      await open()
      const loaded = cdp.once('Page.loadEventFired')
      await cdp.send('Page.navigate', { url: BASE + path })
      await loaded
      if (wait) await settle(extra)
    }

    const as = async (email) => {
      const token = await login(email)
      await go('/login', 0, false)
      await js(`localStorage.setItem('hr-edu-token', ${JSON.stringify(token)});
                localStorage.setItem('hr-edu-theme', 'light')`)
    }

    const shot = async (name, selector, maxHeight = 1600) => {
      if (ONLY && !name.startsWith(ONLY)) return
      const rect = await js(`(() => {
        const el = ${selector}
        if (!el) return null
        const r = el.getBoundingClientRect()
        return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height }
      })()`)
      if (!rect) throw new Error(`${name}: не нашёлся ${selector}`)
      const pad = 12
      const clip = {
        x: Math.max(rect.x - pad, 0),
        y: Math.max(rect.y - pad, 0),
        width: rect.width + pad * 2,
        height: Math.min(rect.height + pad * 2, maxHeight),
        scale: 1,
      }
      const { data } = await cdp.send('Page.captureScreenshot', {
        format: 'png',
        clip,
        captureBeyondViewport: true,
      })
      writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
      console.log(`  ${name}.png`)
    }

    const main = "document.querySelector('main')"

    console.log('Специалист управления образования')
    await as('municipal@demo.ru')
    await go('/staffing?tab=dismissals')
    await js(`document.querySelectorAll('main td[data-label="Сотрудник"] strong')
      .forEach((el, i) => { el.textContent = 'Сотрудник ' + (i + 1) })
      document.querySelectorAll('main td[data-label="Приказ"] .muted')
      .forEach((el) => { el.textContent = 'приказ.pdf' })`)
    await shot('12-uvolennye', main, 1500)

    await go('/staffing', 1500)
    await shot('01-itog', "document.querySelector('.program-hero')")
    await shot('02-gruppy', "document.querySelector('.bucket-grid')")
    await shot('03-gde-vysvobozhdat', "__card('Где высвобождать')", 640)

    await go('/staffing?tab=positions')
    await shot('04-dolzhnosti', main, 1000)

    await go('/staffing?tab=cleaners', 1500)
    await shot('05-uborshchicy', main, 1250)
    await js("__click('Все школы')")
    await settle()
    await shot('06-uborshchicy-tablica', main, 900)

    await go('/staffing?tab=maintenance', 2000)
    await shot('07-hozotdel-zayavki', main, 1250)
    await shot('08-hozotdel-lyudi', "[...document.querySelectorAll('main .grid-2')].at(-1)")
    // Карточки «провалиться»: бригада и хозотдел школы
    const openRow = async (text) => {
      await js(`[...document.querySelectorAll('.row-button')]
        .find((b) => b.textContent.includes(${JSON.stringify(text)}))?.click()`)
      await sleep(400)
      await settle(800)
    }
    const closeDrawer = () => js("document.querySelector('.drawer [aria-label=\"Закрыть\"]')?.click()")
    await openRow(process.env.GUIDE_BRIGADE ?? 'Бригада')
    await shot('16-brigada', "document.querySelector('.drawer')", 900)
    await closeDrawer()
    await openRow(HOZ_SCHOOL)
    await shot('17-hozotdel-shkoly', "document.querySelector('.drawer')", 900)
    await closeDrawer()
    await js("__click('Расчёт ставок')")
    await settle()
    await shot('09-hozotdel-raschet', main, 1300)

    await go('/staffing?tab=schedule')
    await shot('10-shtatka', main, 800)
    const school = await fetch(`${BASE}/api/program/overview`, {
      headers: { Authorization: `Bearer ${await login('municipal@demo.ru')}` },
    })
      .then((r) => r.json())
      .then((d) => d.schools.find((s) => s.organization.includes(SCHOOL)) ?? d.schools[0])
    await go(`/staffing?tab=schedule&sched=${school.organization_id}`, 1500)
    await shot('11-shtatka-shkoly', "document.querySelector('.drawer')", 900)

    await go('/staffing?tab=explain', 1000)
    // Вопрос про одну должность: так лучше видна схема ответа «почему — откуда — как — дальше»
    for (let i = 0; i < 50; i++) {
      if (await js("document.querySelectorAll('.explain-filters select').length > 1")) break
      await sleep(200)
    }
    await js(`(() => {
      const select = document.querySelectorAll('.explain-filters select')[1]
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set
      setter.call(select, 'Уборщик служебных помещений')
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })()`)
    await sleep(8000)
    await js("__click('Что будет с сотрудниками на должности «Уборщик служебных помещений»?')")
    for (let i = 0; i < 120; i++) {
      await sleep(1000)
      if (await js("!document.querySelector('.assistant-input button:not(.primary)')")) break
    }
    await settle(500)
    await shot('13-pochemu-tak', "document.querySelector('.explain')", 1100)

    await go('/requests', 1500)
    await shot('14-zayavki', main, 900)

    console.log('Директор школы')
    await as('director@demo.ru')
    await go('/staffing', 1500)
    await shot('15-direktor', main, 1500)

    cdp.close()
  } finally {
    chrome.kill()
    await sleep(500)
    rmSync(profile, { recursive: true, force: true })
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
