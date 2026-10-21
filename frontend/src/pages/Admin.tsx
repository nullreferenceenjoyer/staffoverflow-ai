import { useState } from 'react'

import { Brigade, Municipality, Organization, RequestMeta, User } from '../api'
import { Page, Reveal, Tabs } from '../components/ui'
import { useApi } from '../lib'
import { Brigades, OnSiteStaff } from './admin/Brigades'
import { Organizations } from './admin/Organizations'
import { Audit, Users } from './admin/Users'

type Tab = 'users' | 'organizations' | 'brigades' | 'audit'

export function Admin() {
  const [tab, setTab] = useState<Tab>('users')
  const municipalities = useApi<Municipality[]>('/municipalities')
  const organizations = useApi<Organization[]>('/organizations')
  const brigades = useApi<Brigade[]>('/admin/brigades')
  const users = useApi<User[]>('/users')
  const meta = useApi<RequestMeta>('/requests/meta')
  const directory =
    municipalities.data && organizations.data && brigades.data
      ? {
          municipalities: municipalities.data,
          organizations: organizations.data,
          brigades: brigades.data.map((b) => ({ id: b.id, name: b.name })),
        }
      : null
  const topics = (meta.data?.topics ?? []).filter((t) => t.field)

  // Справочники меняются на соседних вкладках: после правок перечитываем их
  function reloadDirectory() {
    void municipalities.reload()
    void organizations.reload()
    void brigades.reload()
    void users.reload()
  }

  return (
    <Page
      title="Администрирование"
      hint="Пользователи и их привязка, учёт учреждений, хозяйственные работы (бригады и хозотделы школ) и журнал действий."
    >
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          ['users', 'Пользователи'],
          ['organizations', 'Учреждения'],
          ['brigades', 'Хозяйственные работы'],
          ['audit', 'Журнал'],
        ]}
      />
      <Reveal id={tab}>
        {!directory ? (
          <div className="skeleton" style={{ height: 240 }} />
        ) : tab === 'users' ? (
          <Users directory={directory} state={users} />
        ) : tab === 'organizations' ? (
          <Organizations municipalities={directory.municipalities} onChanged={reloadDirectory} />
        ) : tab === 'brigades' ? (
          <>
            <Brigades
              municipalities={directory.municipalities}
              topics={topics}
              users={users.data ?? []}
              onChanged={reloadDirectory}
            />
            <OnSiteStaff users={users.data ?? []} directory={directory} />
          </>
        ) : (
          <Audit />
        )}
      </Reveal>
    </Page>
  )
}
