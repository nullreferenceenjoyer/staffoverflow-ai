import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { StaffingMeta } from '../api'
import { useUser } from '../App'
import { Icon } from '../components/icons'
import { ScheduleDrawer } from '../components/staffing/Schedule'
import { Async, Page, Reveal, Tabs } from '../components/ui'
import { useApi } from '../lib'
import { Assistant } from './staffing/Assistant'
import { Cleaners } from './staffing/Cleaners'
import { Dismissals } from './staffing/Dismissals'
import { Explain } from './staffing/Explain'
import { Imports } from './staffing/Imports'
import { Maintenance } from './staffing/Maintenance'
import { Norms } from './staffing/Norms'
import { Positions } from './staffing/Positions'
import { Program } from './staffing/Program'
import { Schedules } from './staffing/Schedules'

// Итог анализа, должности, уборщицы, хозотдел, штатка, приказы об увольнении и
// разъяснения. Нормативы, загрузка из Excel и помощник — кнопками в шапке: нужны редко
type Tab =
  | 'summary'
  | 'positions'
  | 'cleaners'
  | 'maintenance'
  | 'schedule'
  | 'dismissals'
  | 'explain'
  | 'norms'
  | 'import'
  | 'assistant'

// Старые ссылки ведут на ближайшую новую вкладку
const OLD: Record<string, Tab> = {
  dashboard: 'summary',
  analysis: 'summary',
  fact: 'schedule',
  cleaning: 'cleaners',
  workload: 'maintenance',
}

export function Staffing() {
  const user = useUser()
  const meta = useApi<StaffingMeta>('/staffing/meta')
  const [params, setParams] = useSearchParams()
  const [version, setVersion] = useState(0)
  const director = user.role === 'director'

  function update(patch: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  const raw = params.get('tab') ?? 'summary'
  const tab = (OLD[raw] ?? raw) as Tab
  const schedule = Number(params.get('sched')) || null
  const changed = () => setVersion((v) => v + 1)

  return (
    <Async state={meta}>
      {(m) => {
        const year = params.get('year') ?? m.current_year
        const tabs: [Tab, string][] = [
          ['summary', 'Итог'],
          ['positions', 'Должности'],
        ]
        if (m.permissions.details) {
          tabs.push(['cleaners', 'Уборщицы'])
          tabs.push(['maintenance', 'Хозотдел'])
          tabs.push(['schedule', 'Штатка'])
          tabs.push(['dismissals', 'Уволенные'])
        }
        tabs.push(['explain', 'Почему так — ИИ'])
        const go = (t: Tab) => update({ tab: t === 'summary' ? null : t })
        return (
          <Page
            title={director ? (m.organization?.name ?? 'Моя школа') : 'Оптимизация штата'}
            hint={
              director
                ? 'Сколько ставок в школе нужно высвободить и за счёт чего, расчёт уборщиц и хозотдела.'
                : `${m.okrug ?? 'Округ'}: сколько ставок нужно высвободить в школах — вакансии, совмещение и сокращение занятых ставок.`
            }
            actions={
              <>
                {m.permissions.edit_norms && (
                  <button
                    className={tab === 'norms' ? 'primary' : 'ghost'}
                    onClick={() => go('norms')}
                  >
                    <Icon name="scale" size={16} /> Нормативы
                  </button>
                )}
                {m.permissions.import && (
                  <button
                    className={tab === 'import' ? 'primary' : 'ghost'}
                    onClick={() => go('import')}
                  >
                    <Icon name="upload" size={16} /> Из Excel
                  </button>
                )}
                <button
                  className={tab === 'assistant' ? 'primary' : 'ghost'}
                  onClick={() => go('assistant')}
                >
                  <Icon name="message" size={16} /> Помощник
                </button>
              </>
            }
          >
            <Tabs value={tab} onChange={go} tabs={tabs} />
            <Reveal id={tab}>
              {tab === 'summary' && (
                <Program meta={m} onGo={go} onOpenSchool={(id) => update({ sched: String(id) })} />
              )}
              {tab === 'positions' && <Positions />}
              {tab === 'cleaners' && <Cleaners meta={m} year={year} />}
              {tab === 'maintenance' && <Maintenance meta={m} year={year} />}
              {tab === 'schedule' && (
                <Schedules
                  meta={m}
                  year={year}
                  version={version}
                  onOpen={(id) => update({ sched: String(id) })}
                />
              )}
              {tab === 'dismissals' && m.permissions.details && <Dismissals />}
              {tab === 'explain' && <Explain meta={m} />}
              {tab === 'norms' && <Norms meta={m} />}
              {tab === 'assistant' && (
                <Assistant
                  meta={m}
                  year={year}
                  about={Number(params.get('about')) || null}
                  onAboutDone={() => params.get('about') && update({ about: null })}
                />
              )}
              {tab === 'import' && m.permissions.import && <Imports meta={m} onDone={changed} />}
            </Reveal>
            {schedule && m.permissions.details && (
              <ScheduleDrawer
                key={`${schedule}-${year}`}
                organizationId={schedule}
                year={year}
                onClose={() => update({ sched: null })}
                onChanged={changed}
              />
            )}
          </Page>
        )
      }}
    </Async>
  )
}
